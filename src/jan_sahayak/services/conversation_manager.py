"""
Conversation Manager Service — Orchestrates the scheme intelligence pipeline.
Extracts profiles, queries matching schemes, and formats responses for the user.
"""

from typing import Any

from langsmith import traceable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from jan_sahayak.exceptions import ConversationNotFoundError
from jan_sahayak.logger import get_logger
from jan_sahayak.models.conversation import Conversation, Message
from jan_sahayak.models.user import User
from jan_sahayak.services.profile_extractor import profile_extractor
from jan_sahayak.services.sarvam import sarvam_service
from jan_sahayak.services.scheme_engine import scheme_engine


logger = get_logger(__name__)

# Language display names for system prompt clarity
LANGUAGE_DISPLAY_NAMES = {
    "hindi": "Hindi (हिंदी)",
    "english": "English",
    "bengali": "Bengali (বাংলা)",
    "tamil": "Tamil (தமிழ்)",
    "telugu": "Telugu (తెలుగు)",
    "marathi": "Marathi (मराठी)",
    "gujarati": "Gujarati (ગુજરાતી)",
    "kannada": "Kannada (ಕನ್ನಡ)",
    "malayalam": "Malayalam (മലയാളം)",
    "odia": "Odia (ଓଡ଼ିଆ)",
    "punjabi": "Punjabi (ਪੰਜਾਬੀ)",
    "assamese": "Assamese (অসমীয়া)",
    "urdu": "Urdu (اردو)",
}

# Master System Prompt that adapts to context
BASE_SYSTEM_PROMPT = """
You are Jan Sahayak, a friendly, respectful, and highly empathetic virtual AI assistant helping Indian citizens discover welfare schemes.
Your goal is to converse with the user, collect their profile details (state, income, occupation, category, family size, etc.) naturally, and suggest relevant schemes.

CRITICAL LANGUAGE RULE — YOU MUST FOLLOW THIS:
The citizen's language is: {language_display}.
You MUST reply ONLY in {language_display}. Do NOT use any other language.
If the language is English, reply entirely in English. If it is Hindi, reply entirely in Hindi. And so on for any other language.
Violating this rule is unacceptable.

CURRENT CITIZEN PROFILE:
{profile_summary}

ELIGIBILITY SCHEME MATCHES:
{scheme_matches}

MISSING PROFILE INFORMATION TO ASK FOR (ask one at a time naturally in conversation, do not list them all):
{missing_fields}

INSTRUCTIONS:
1. Respond ONLY in {language_display}. This is mandatory and non-negotiable.
2. If scheme matches are available, explain them simply (what they get, key eligibility, and where to apply).
3. If profile details are missing, ask for them politely and conversationally. Do not ask for more than one piece of information at a time.
4. If the user shares any new details, confirm you've noted them and adapt your tone to match their situation.
5. If they qualify for nothing, express empathy and offer to help search for other resources or verify their details.
"""


class ConversationManager:
    """Manages the full scheme intelligence session cycle."""

    @traceable(name="Process Conversation Turn")
    async def process_message(
        self,
        db: AsyncSession,
        user_message: str,
        conversation_id: str | None = None,
        language: str = "hindi",
        profile_overrides: dict | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Process a single chat message from the user.

        1. Find or create the conversation.
        2. Run profile extraction on the new user message.
        3. Merge the new fields into the conversation context profile.
        4. Match schemes if we have basic profile data.
        5. Prompt the LLM using the current context and get a response.
        6. Persist changes.

        Returns:
            Dict containing:
                "reply": The response text from Jan Sahayak
                "conversation_id": The ID of the conversation
                "matched_schemes": List of Scheme instances matched
                "updated_profile": The updated profile dict
        """
        # Sanitization: Strip control characters (\x00-\x1f except \n) and limit length
        import re
        user_message = re.sub(r'[\x00-\x09\x0b-\x1f]', '', user_message)[:2000]

        # 1. Fetch or create conversation
        if conversation_id:
            query = select(Conversation).where(Conversation.id == conversation_id)
            result = await db.execute(query)
            conversation = result.scalar_one_or_none()
            if not conversation:
                raise ConversationNotFoundError(conversation_id)
            # Sync user ID if not present
            if user_id and not conversation.user_id:
                conversation.user_id = user_id
        else:
            conversation = Conversation(language=language, context={}, user_id=user_id)
            db.add(conversation)
            await db.flush()  # Generate ID

        # Copy context to a new dict to ensure SQLAlchemy detects the mutation
        current_profile = dict(conversation.context or {})

        # 2. Extract profile fields from the new message
        extracted = await profile_extractor.extract_profile(user_message)

        # 3. Merge extracted fields into current profile (do not overwrite with nulls)
        for k, v in extracted.items():
            if v is not None:
                current_profile[k] = v

        # Apply any explicit overrides from the client (e.g. digitized document data)
        # Validate profile_overrides keys against allowed set
        allowed_keys = {
            "name", "state", "district", "annual_income", "occupation",
            "category", "family_size", "age", "gender"
        }
        if profile_overrides:
            cleaned_overrides = {
                k: v for k, v in profile_overrides.items()
                if k in allowed_keys and v is not None
            }
            for k, v in cleaned_overrides.items():
                current_profile[k] = v

        # Reassign to trigger SQLAlchemy change detection on JSON column
        conversation.context = current_profile
        flag_modified(conversation, "context")
        logger.info(f"Merged profile (after overrides): {current_profile}")


        # Save user message
        db.add(Message(conversation_id=conversation.id, role="user", content=user_message, language=language))

        # 4. Find matched schemes based on current profile
        matched_schemes_data = []
        if self._has_sufficient_matching_data(current_profile):
            logger.info(f"Sufficient profile data found for matching: {current_profile}")
            matched_schemes_data = await scheme_engine.find_matching_schemes(db, current_profile, limit=3)
        else:
            logger.info(f"Profile data too sparse for automatic matching: {current_profile}")

        # Extract Scheme models from matches
        matched_schemes = [m["scheme"] for m in matched_schemes_data]

        # 5. Compile system prompt
        profile_summary = self._generate_profile_summary(current_profile)
        scheme_matches = self._generate_schemes_summary(matched_schemes_data, language)
        missing_fields = self._get_missing_fields_guideline(current_profile)

        system_prompt = BASE_SYSTEM_PROMPT.format(
            profile_summary=profile_summary,
            scheme_matches=scheme_matches,
            missing_fields=missing_fields,
            language_display=LANGUAGE_DISPLAY_NAMES.get(language, language),
        )

        # Build message history for LLM
        # Limit history to last 8 messages to prevent context bloat
        history_query = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(8)
        )
        history_result = await db.execute(history_query)
        recent_messages = list(history_result.scalars().all())
        recent_messages.reverse()

        llm_messages = [{"role": "system", "content": system_prompt}]
        for msg in recent_messages:
            # Skip user message we just added since we'll append it explicitly if not present,
            # but actually it is already in the DB and returned by history_query.
            llm_messages.append({"role": msg.role, "content": msg.content})

        # 6. Call LLM to get conversational response
        reply = await sarvam_service.chat(llm_messages, temperature=0.5)

        # Save assistant message
        db.add(Message(conversation_id=conversation.id, role="assistant", content=reply, language=language))

        # Sync profile changes back to the User model if available
        if user_id:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user:
                if "name" in current_profile and current_profile["name"]:
                    user.name = current_profile["name"]
                if "state" in current_profile and current_profile["state"]:
                    user.state = current_profile["state"]
                if "district" in current_profile and current_profile["district"]:
                    user.district = current_profile["district"]
                if "annual_income" in current_profile and current_profile["annual_income"] is not None:
                    user.annual_income = current_profile["annual_income"]
                if "category" in current_profile and current_profile["category"]:
                    user.category = current_profile["category"]
                if "occupation" in current_profile and current_profile["occupation"]:
                    user.occupation = current_profile["occupation"]
                if "family_size" in current_profile and current_profile["family_size"] is not None:
                    user.family_size = current_profile["family_size"]

        # Commit all changes to DB
        await db.commit()


        return {
            "reply": reply,
            "conversation_id": conversation.id,
            "matched_schemes": matched_schemes,
            "updated_profile": current_profile,
        }

    def _has_sufficient_matching_data(self, profile: dict[str, Any]) -> bool:
        """Check if profile has at least state, income, or occupation to start matching."""
        identifying_fields = ["state", "annual_income", "occupation", "category"]
        filled_count = sum(1 for field in identifying_fields if profile.get(field) is not None)
        return filled_count >= 1

    def _generate_profile_summary(self, profile: dict[str, Any]) -> str:
        if not profile:
            return "No profile details collected yet."

        lines = []
        for key, val in profile.items():
            lines.append(f"- {key.replace('_', ' ').capitalize()}: {val}")
        return "\n".join(lines)

    def _generate_schemes_summary(self, matches: list[dict[str, Any]], language: str) -> str:
        if not matches:
            return "No eligible scheme matches found yet. Collect more profile details."

        lines = []
        for idx, item in enumerate(matches, 1):
            scheme = item["scheme"]
            name = scheme.name_hi if language.lower() == "hindi" and scheme.name_hi else scheme.name_en
            desc = (
                scheme.description_hi
                if language.lower() == "hindi" and scheme.description_hi
                else scheme.description_en
            )
            desc_text = (desc or "No details available")[:150]
            lines.append(f"{idx}. {name}\n   - Benefits: {scheme.benefits or 'N/A'}\n   - Details: {desc_text}...")
        return "\n".join(lines)

    def _get_missing_fields_guideline(self, profile: dict[str, Any]) -> str:
        all_fields = {
            "state": "State of residence",
            "annual_income": "Annual income",
            "occupation": "Occupation (e.g. farmer, laborer)",
            "category": "Caste/Reservation category (SC/ST/OBC/General)",
            "family_size": "Family size",
            "age": "Age",
            "gender": "Gender",
        }
        needed = [desc for field, desc in all_fields.items() if profile.get(field) is None]

        if not needed:
            return "All profile details collected. Focus on guiding user to apply for eligible schemes."

        return ", ".join(needed)


# Singleton instance
conversation_manager = ConversationManager()
