"""
Scheme Engine — Matches government schemes to citizen profiles.

Uses a combination of:
1. Rule-based filtering (income, state, category)
2. LLM-powered matching via Sarvam-30B for nuanced eligibility
"""

from typing import Any

from langsmith import traceable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.logger import get_logger
from jan_sahayak.models.scheme import Scheme
from jan_sahayak.services.sarvam import sarvam_service

logger = get_logger(__name__)


class SchemeEngine:
    """Matches government schemes to citizen profiles."""

    @traceable(name="Find Matching Schemes")
    async def find_matching_schemes(
        self,
        db: AsyncSession,
        user_profile: dict[str, Any],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find government schemes that match a citizen's profile.

        Args:
            db: Database session
            user_profile: Extracted citizen profile with keys like
                          income, state, category, occupation, family_size
            limit: Maximum number of schemes to return

        Returns:
            List of matching schemes with match details
        """
        # Step 1: Get all active schemes from database
        query = select(Scheme).where(Scheme.is_active == True)  # noqa: E712
        result = await db.execute(query)
        all_schemes = result.scalars().all()

        if not all_schemes:
            return []

        # Step 2: Rule-based filtering
        filtered_schemes = []
        for scheme in all_schemes:
            score, reasons = self._calculate_match_score(scheme, user_profile)
            if score > 0:
                filtered_schemes.append(
                    {
                        "scheme": scheme,
                        "score": score,
                        "reasons": reasons,
                    }
                )

        # Sort by match score (highest first)
        filtered_schemes.sort(key=lambda x: x["score"], reverse=True)

        return filtered_schemes[:limit]

    def _calculate_match_score(self, scheme: Scheme, profile: dict[str, Any]) -> tuple[float, list[str]]:
        """
        Calculate how well a scheme matches a user profile.
        Hard disqualification on any criteria mismatch.

        Returns:
            (score from 0.0 to 1.0, list of matching reasons)
        """
        score = 0.0
        reasons = []
        criteria = scheme.eligibility_criteria or {}

        # --- Hard disqualification checks (return 0 if mismatch) ---

        # 1. Income check
        if "max_income" in criteria and profile.get("annual_income") is not None:
            if profile["annual_income"] <= criteria["max_income"]:
                score += 0.25
                reasons.append(f"Income ≤ ₹{criteria['max_income']:,.0f}")
            else:
                return 0.0, []  # Income too high

        # 2. Category check (SC/ST/OBC/General)
        if "categories" in criteria and profile.get("category"):
            if profile["category"].upper() in [c.upper() for c in criteria["categories"]]:
                score += 0.15
                reasons.append(f"Category: {profile['category']}")
            else:
                return 0.0, []  # Category mismatch

        # 3. State check
        if scheme.state_specific and scheme.target_states:
            if profile.get("state") and profile["state"] in scheme.target_states:
                score += 0.15
                reasons.append(f"State: {profile['state']}")
            elif profile.get("state"):
                return 0.0, []  # Wrong state
        else:
            score += 0.05
            reasons.append("All-India scheme")

        # 4. Occupation check
        if "occupations" in criteria and profile.get("occupation"):
            if profile["occupation"].lower() in [o.lower() for o in criteria["occupations"]]:
                score += 0.2
                reasons.append(f"Occupation: {profile['occupation']}")
            else:
                return 0.0, []  # Occupation mismatch

        # 5. Gender check
        if "gender" in criteria and profile.get("gender"):
            if profile["gender"].lower() == criteria["gender"].lower():
                score += 0.1
                reasons.append(f"Gender: {profile['gender']}")
            else:
                return 0.0, []  # Gender mismatch

        # 6. Age range check
        user_age = profile.get("age")
        if user_age is not None:
            if "min_age" in criteria and user_age < criteria["min_age"]:
                return 0.0, []  # Too young
            if "max_age" in criteria and user_age > criteria["max_age"]:
                return 0.0, []  # Too old
            if "min_age" in criteria or "max_age" in criteria:
                score += 0.1
                min_a = criteria.get("min_age", "any")
                max_a = criteria.get("max_age", "any")
                reasons.append(f"Age {user_age} in range [{min_a}–{max_a}]")

        # Base score for schemes with no specific criteria (general welfare)
        if score == 0.0 and not criteria:
            score = 0.05
            reasons.append("General welfare scheme")

        return min(score, 1.0), reasons

    @traceable(name="Explain Scheme")
    async def explain_scheme(self, scheme: Scheme, language: str = "hindi") -> str:
        """
        Use Sarvam-30B to explain a scheme in simple language.

        Args:
            scheme: The scheme to explain
            language: Target language for explanation

        Returns:
            Simple explanation of the scheme
        """
        system_prompt = (
            "You are Jan Sahayak, a helpful government scheme assistant for Indian citizens. "
            "Explain government schemes in very simple, easy-to-understand language. "
            "Use short sentences. Avoid complex words. "
            f"Respond in {language}."
        )

        scheme_info = (
            f"Scheme Name: {scheme.name_en}\n"
            f"Hindi Name: {scheme.name_hi or 'N/A'}\n"
            f"Ministry: {scheme.ministry or 'N/A'}\n"
            f"Description: {scheme.description_en or 'N/A'}\n"
            f"Benefits: {scheme.benefits or 'N/A'}\n"
            f"Documents Required: {', '.join(scheme.documents_required) if scheme.documents_required else 'N/A'}\n"
            f"How to Apply: {scheme.application_url or 'N/A'}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Please explain this government scheme in simple {language}:\n\n{scheme_info}",
            },
        ]

        explanation = await sarvam_service.chat(messages, temperature=0.5)
        return explanation

    @traceable(name="Generate Application Guide")
    async def generate_application_guide(
        self, scheme: Scheme, user_profile: dict[str, Any], language: str = "hindi"
    ) -> str:
        """
        Use Sarvam-30B to generate a personalized step-by-step application guide.

        Args:
            scheme: The scheme to apply for
            user_profile: Citizen profile details
            language: Target language for the guide

        Returns:
            Personalized step-by-step guide
        """
        system_prompt = (
            "You are Jan Sahayak, a helpful guide who provides clear, step-by-step instructions on "
            "how to apply for government welfare schemes. "
            "Write simple, numbered steps. "
            f"Respond in {language}."
        )

        scheme_info = (
            f"Scheme Name: {scheme.name_en}\n"
            f"Ministry: {scheme.ministry or 'N/A'}\n"
            f"Documents Required: {', '.join(scheme.documents_required) if scheme.documents_required else 'N/A'}\n"
            f"Application URL/Office: {scheme.application_url or 'N/A'}"
        )

        profile_info = ", ".join(f"{k}: {v}" for k, v in user_profile.items() if v is not None)

        user_content = (
            f"Provide a step-by-step application guide for this scheme:\n\n{scheme_info}\n\n"
            f"Personalized for a citizen with these profile details:\n{profile_info}\n\n"
            f"Format the response in simple {language} as a numbered list."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        guide = await sarvam_service.chat(messages, temperature=0.5)
        return guide


# Singleton instance
scheme_engine = SchemeEngine()
