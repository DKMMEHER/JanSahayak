"""
Profile Extractor Service — Uses Sarvam-30B to parse conversation and extract structured citizen profile attributes.
"""

import json
from typing import Any

from langsmith import traceable

from jan_sahayak.logger import get_logger
from jan_sahayak.services.sarvam import sarvam_service

logger = get_logger(__name__)

# System prompt for structured profile extraction
EXTRACTION_SYSTEM_PROMPT = """
You are an expert data extraction assistant. Your task is to analyze the user's message or document text and extract structured demographic information to help identify government welfare eligibility.

Analyze the text and return a JSON object with the following fields:
- "name": The user's name (string or null). Ignore parent/spouse names (e.g. "S/O", "W/O").
- "state": The Indian state they reside in (standardized name, e.g. "Uttar Pradesh", "Maharashtra", or null). Look at address blocks if present.
- "district": The district they reside in (string or null). Look at address blocks if present.
- "annual_income": Their annual household income in Indian Rupees (number or null). Convert terms like "1.5 लाख" or "1.5 lakh" to 150000.
- "category": Their caste/reservation category (strictly one of: "SC", "ST", "OBC", "General", or null)
- "occupation": Their job or primary occupation (e.g. "farmer", "carpenter", "unemployed", "student", or null)
- "family_size": Number of members in their household (number or null)
- "age": Their age in years (number or null). CRITICAL: If a Date of Birth (DOB) or Year of Birth (YOB) like "1991" or "12/04/1991" is found, calculate the age relative to the year 2026 (e.g., 2026 - 1991 = 35). Do NOT output the birth year as the age!
- "gender": Their gender (strictly one of: "male", "female", or null). Can often be inferred from title (Mr/Ms) or relationships (S/O vs D/O).

Rules:
1. ONLY extract information that is explicitly stated or strongly implied in the message.
2. If a field is not mentioned, set it to null. Do not guess.
3. Respond ONLY with a valid JSON object. Do not include any markdown formatting, code blocks (like ```json), or conversational filler.
"""


class ProfileExtractor:
    """Extracts structured citizen profiles from conversation turns using Sarvam AI."""

    def _extract_regex(self, text: str) -> dict[str, Any]:
        """Attempt to extract profile fields using regex and dictionary matching."""
        import re
        extracted = {}
        text_lower = text.lower()

        # 1. Extract State
        states_map = {
            "uttar pradesh": "Uttar Pradesh", "उत्तर प्रदेश": "Uttar Pradesh", "यूपी": "Uttar Pradesh", "up": "Uttar Pradesh",
            "madhya pradesh": "Madhya Pradesh", "मध्य प्रदेश": "Madhya Pradesh", "एमपी": "Madhya Pradesh", "mp": "Madhya Pradesh",
            "bihar": "Bihar", "बिहार": "Bihar",
            "maharashtra": "Maharashtra", "महाराष्ट्र": "Maharashtra",
            "rajasthan": "Rajasthan", "राजस्थान": "Rajasthan",
            "delhi": "Delhi", "दिल्ली": "Delhi",
            "haryana": "Haryana", "हरियाणा": "Haryana",
            "punjab": "Punjab", "पंजाब": "Punjab",
            "gujarat": "Gujarat", "गुजरात": "Gujarat",
            "karnataka": "Karnataka", "कर्नाटक": "Karnataka",
            "tamil nadu": "Tamil Nadu", "तमिलनाडु": "Tamil Nadu",
            "west bengal": "West Bengal", "पश्चिम बंगाल": "West Bengal",
            "andhra pradesh": "Andhra Pradesh", "आंध्र प्रदेश": "Andhra Pradesh",
            "telangana": "Telangana", "तेलंगाना": "Telangana",
            "odisha": "Odisha", "ओडिशा": "Odisha",
            "kerala": "Kerala", "केरल": "Kerala",
            "jharkhand": "Jharkhand", "झारखंड": "Jharkhand",
            "assam": "Assam", "असम": "Assam",
            "chhattisgarh": "Chhattisgarh", "छत्तीसगढ़": "Chhattisgarh",
        }
        for kw, state_name in states_map.items():
            if kw in text_lower:
                extracted["state"] = state_name
                break

        # 2. Extract Category
        categories_map = {
            "sc": "SC", "एससी": "SC", "अनुसूचित जाति": "SC",
            "st": "ST", "एसटी": "ST", "अनुसूचित जनजाति": "ST",
            "obc": "OBC", "ओबीसी": "OBC", "पिछड़ा वर्ग": "OBC", "अन्य पिछड़ा वर्ग": "OBC",
            "general": "General", "सामान्य": "General", "अनारक्षित": "General", "gen": "General",
        }
        for kw, cat_name in categories_map.items():
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower) or kw in text_lower:
                extracted["category"] = cat_name
                break

        # 3. Extract Gender
        genders_map = {
            "female": "female", "महिला": "female", "स्त्री": "female", "लड़की": "female", "girl": "female", "woman": "female",
            "male": "male", "पुरुष": "male", "आदमी": "male", "boy": "male", "man": "male",
        }
        for kw, gender_name in genders_map.items():
            if kw in text_lower:
                extracted["gender"] = gender_name
                break

        # 4. Extract Age
        # Look for age patterns like "30 साल", "उम्र 35", "30 years"
        age_patterns = [
            r"\b(1[89]|[2-9]\d)\b\s*(साल|वर्ष|years|year|age)",
            r"(उम्र|umar|umar|आयु|age)\s*(की|के|है)?\s*\b(1[89]|[2-9]\d)\b",
            r"\b(1[89]|[2-9]\d)\b\s*(साल का हूँ|साल की हूँ|years old)"
        ]
        for pattern in age_patterns:
            match = re.search(pattern, text_lower)
            if match:
                for g in match.groups():
                    if g and g.isdigit():
                        extracted["age"] = int(g)
                        break
                if "age" in extracted:
                    break

        # 5. Extract Annual Income
        # Look for patterns like "1.5 लाख", "1.5 lakh", "50000", "50 हजार"
        income_patterns = [
            r"\b(\d+(\.\d+)?)\s*(lakh|lacs|lakhs|लाख|l)\b",
            r"\b(\d+)\s*(thousand|हजार|हज़ार|k)\b",
            r"\b(\d{5,7})\b"
        ]
        for idx, pattern in enumerate(income_patterns):
            match = re.search(pattern, text_lower)
            if match:
                val_str = match.group(1)
                try:
                    val = float(val_str)
                    if idx == 0:  # Lakh
                        extracted["annual_income"] = int(val * 100000)
                    elif idx == 1:  # Thousand
                        extracted["annual_income"] = int(val * 1000)
                    else:  # Raw 5-7 digit number
                        extracted["annual_income"] = int(val)
                    break
                except ValueError:
                    pass

        # 6. Extract Occupation
        occupations_map = {
            "farmer": "farmer", "किसान": "farmer", "खेती": "farmer", "कृषि": "farmer",
            "carpenter": "carpenter", "बढ़ई": "carpenter",
            "student": "student", "छात्र": "student", "विद्यार्थी": "student", "पढ़ाई": "student",
            "unemployed": "unemployed", "बेरोजगार": "unemployed", "बेरोज़गार": "unemployed", "कोई नौकरी नहीं": "unemployed",
            "tailor": "tailor", "दर्जी": "tailor", "दर्ज़ी": "tailor",
            "barber": "barber", "नाई": "barber",
            "mason": "mason", "राजमिस्त्री": "mason", "मिस्त्री": "mason",
            "blacksmith": "blacksmith", "लोहार": "blacksmith",
            "goldsmith": "goldsmith", "सुनार": "goldsmith",
            "weaver": "weaver", "बुनकर": "weaver",
        }
        for kw, occ_name in occupations_map.items():
            if kw in text_lower:
                extracted["occupation"] = occ_name
                break

        return extracted

    def _is_demographic_related(self, text: str) -> bool:
        """Check if the text contains any keywords or patterns related to demographics.

        Supports Hindi, English, and other Indic languages (Odia, Bengali, Tamil, etc.).
        If the text contains non-ASCII Indic script characters, we assume it may contain
        profile information and let the LLM extractor handle it.
        """
        import re
        text_lower = text.lower()

        # 1. Check for numbers (age, income, family size) — universal across all languages
        if re.search(r"\d", text_lower):
            return True

        # 2. If text contains significant Indic script characters (non-Latin, non-ASCII),
        #    assume it may contain demographic info and let the LLM extractor handle it.
        #    This covers Odia, Bengali, Tamil, Telugu, Kannada, Malayalam, Gujarati, Punjabi, etc.
        indic_ranges = (
            r"[\u0900-\u097F]"   # Devanagari (Hindi, Marathi)
            r"|[\u0980-\u09FF]" # Bengali, Assamese
            r"|[\u0A00-\u0A7F]" # Gurmukhi (Punjabi)
            r"|[\u0A80-\u0AFF]" # Gujarati
            r"|[\u0B00-\u0B7F]" # Odia
            r"|[\u0B80-\u0BFF]" # Tamil
            r"|[\u0C00-\u0C7F]" # Telugu
            r"|[\u0C80-\u0CFF]" # Kannada
            r"|[\u0D00-\u0D7F]" # Malayalam
            r"|[\u0600-\u06FF]" # Arabic/Urdu
        )
        indic_chars = len(re.findall(indic_ranges, text))
        if indic_chars >= 5:
            return True

        # 3. Check for state names (Hindi and English)
        states = [
            "uttar pradesh", "उत्तर प्रदेश", "यूपी", "up",
            "madhya pradesh", "मध्य प्रदेश", "एमपी", "mp",
            "bihar", "बिहार", "maharashtra", "महाराष्ट्र",
            "rajasthan", "राजस्थान", "delhi", "दिल्ली",
            "haryana", "हरियाणा", "punjab", "पंजाब",
            "gujarat", "गुजरात", "karnataka", "कर्नाटक",
            "tamil nadu", "तमिलनाडु", "west bengal", "पश्चिम बंगाल",
            "andhra pradesh", "आंध्र प्रदेश", "telangana", "तेलंगाना",
            "odisha", "ओडिशा", "ଓଡ଼ିଶା", "kerala", "केरल",
            "jharkhand", "झारखंड", "assam", "असম", "chhattisgarh", "छत्तीसगढ़"
        ]
        if any(s in text_lower for s in states):
            return True

        # 4. Check for categories
        categories = ["sc", "st", "obc", "general", "सामान्य", "अनारक्षित", "ओबीसी", "एससी", "एसटी", "पिछड़ा वर्ग", "जाति", "caste"]
        if any(c in text_lower for c in categories):
            return True

        # 5. Check for gender
        genders = ["male", "female", "महिला", "पुरुष", "स्त्री", "आदमी", "लड़की", "लड़का", "gender", "ling", "sex"]
        if any(g in text_lower for g in genders):
            return True

        # 6. Check for occupations
        occupations = [
            "farmer", "किसान", "खेती", "कृषि", "carpenter", "बढ़ई", "student", "छात्र", "विद्यार्थी", "पढ़ाई",
            "unemployed", "बेरोजगार", "बेरोज़गार", "नौकरी", "tailor", "दर्जी", "दर्ज़ी", "barber", "नाई",
            "mason", "राजमिस्त्री", "मिस्त्री", "blacksmith", "लोहार", "goldsmith", "सुनार", "weaver", "बुनकर",
            "job", "work", "engineer", "doctor", "teacher", "driver", "laborer", "labourer"
        ]
        if any(o in text_lower for o in occupations):
            return True

        # 7. Check for profile introduction keywords (Hindi + English)
        intro_keywords = [
            "मेरा नाम", "my name", "नाम है", "रहता हूँ", "रहती हूँ", "रहने वाला", "रहने वाली", "रहता हूं", "रहती हूं",
            "आय", "कमाई", "income", "salary", "कमाते", "कमाता", "कमाती", "काम करता", "काम करती", "काम करते",
            "परिवार", "family", "सदस्य", "members", "साल का", "साल की", "उम्र", "years old", "age",
            "i am", "i live", "i earn", "i work", "name is", "live in", "from"
        ]
        if any(ik in text_lower for ik in intro_keywords):
            return True

        return False

    @traceable(name="Extract Profile Fields")
    async def extract_profile(self, user_message: str) -> dict[str, Any]:
        """
        Analyze a single user message and extract any mentioned profile fields.

        Args:
            user_message: The text of the user's input

        Returns:
            Dict containing the extracted profile fields
        """
        # 1. Skip extraction for very short messages (greetings, yes/no, conversational filler)
        words = user_message.strip().split()
        if len(words) < 3:
            logger.info(f"Short message '{user_message}' - skipping profile extraction.")
            return {}

        # 2. Skip extraction if message does not contain any demographic-related keywords
        if not self._is_demographic_related(user_message):
            logger.info(f"Message '{user_message}' contains no demographic context. Skipping extraction.")
            return {}

        # Run regex extraction as a baseline/fallback
        regex_extracted = self._extract_regex(user_message)

        # 4. Fallback to LLM extraction only for longer/unmatched messages
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract fields from this message: '{user_message}'"},
        ]

        try:
            logger.info(f"Extracting profile fields via LLM fallback from: '{user_message[:60]}...'")
            response_text = await sarvam_service.chat(messages, temperature=0.0)

            # Clean response text in case LLM wraps it in markdown code blocks
            clean_json = response_text.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            clean_json = clean_json.strip()

            try:
                extracted_data = json.loads(clean_json)
            except json.JSONDecodeError:
                # Attempt regex search for JSON block
                import re

                match = re.search(r"\{.*\}", clean_json, re.DOTALL)
                if match:
                    try:
                        extracted_data = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        logger.warning(f"Regex matched block but failed to parse JSON: {match.group(0)}")
                        extracted_data = {}
                else:
                    logger.warning(f"No JSON object pattern found in LLM response: {clean_json}")
                    extracted_data = {}

            # Filter out keys that are not in our target schema or are null
            valid_keys = {
                "name",
                "state",
                "district",
                "annual_income",
                "category",
                "occupation",
                "family_size",
                "age",
                "gender",
            }

            filtered_data = {k: v for k, v in extracted_data.items() if k in valid_keys and v is not None}

            # Merge with regex results if any existed
            for k, v in regex_extracted.items():
                if k not in filtered_data:
                    filtered_data[k] = v

            if filtered_data:
                logger.info(f"Extracted fields: {filtered_data}")
            else:
                logger.info("No profile fields extracted from message.")

            return filtered_data

        except Exception as e:
            logger.warning(f"Error during profile extraction: {e}. Falling back to empty profile.", exc_info=True)
            return regex_extracted


# Singleton instance
profile_extractor = ProfileExtractor()
