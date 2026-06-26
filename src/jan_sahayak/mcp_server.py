"""
Jan Sahayak — MCP Server implementation.
Exposes Scheme search engine capabilities, scheme explanations, application guides,
and database resources to any compliant MCP Client.
"""

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from jan_sahayak.database import async_session
from jan_sahayak.models.scheme import Scheme
from jan_sahayak.services.scheme_engine import scheme_engine

# Initialize FastMCP Server
mcp = FastMCP("Jan Sahayak Scheme Explorer")


# =============================================================================
# Tools (Executable actions)
# =============================================================================

@mcp.tool()
async def search_schemes(
    annual_income: Optional[float] = None,
    category: Optional[str] = None,
    occupation: Optional[str] = None,
    state: Optional[str] = None,
    gender: Optional[str] = None,
    age: Optional[int] = None,
) -> str:
    """
    Search for eligible government schemes based on citizen demographic and financial profile.

    Args:
        annual_income: Citizen's annual household income in Rupees (e.g. 150000.0).
        category: Caste/social category. strictly one of: SC, ST, OBC, General.
        occupation: Citizen's primary occupation (e.g. farmer, student, unemployed, weaver).
        state: Indian State of residence (e.g. Uttar Pradesh, Madhya Pradesh, Bihar).
        gender: Gender of the citizen (e.g. male, female).
        age: Age of the citizen in years.
    """
    profile = {}
    if annual_income is not None:
        profile["annual_income"] = annual_income
    if category:
        profile["category"] = category
    if occupation:
        profile["occupation"] = occupation
    if state:
        profile["state"] = state
    if gender:
        profile["gender"] = gender
    if age is not None:
        profile["age"] = age

    async with async_session() as db:
        matches = await scheme_engine.find_matching_schemes(db, profile, limit=5)
        if not matches:
            return "No eligible government schemes found matching these criteria."

        output = []
        for i, item in enumerate(matches, 1):
            s = item["scheme"]
            score = item["score"]
            reasons = ", ".join(item["reasons"])
            output.append(
                f"### {i}. {s.name_en} (Hindi: {s.name_hi or 'N/A'})\n"
                f"- **ID**: {s.id}\n"
                f"- **Ministry**: {s.ministry or 'N/A'}\n"
                f"- **Category**: {s.category or 'N/A'}\n"
                f"- **Match Confidence**: {score * 100:.0f}%\n"
                f"- **Eligibility Reasons**: {reasons}\n"
                f"- **Benefits**: {s.benefits or 'N/A'}\n"
                f"- **Description**: {s.description_en or 'N/A'}\n"
            )
        return "\n".join(output)


@mcp.tool()
async def explain_scheme(scheme_name: str, language: str = "hindi") -> str:
    """
    Explain a specific government scheme in simple language using AI.

    Args:
        scheme_name: The name or English/Hindi title of the scheme (e.g. "PM-KISAN" or "Pradhan Mantri Awas Yojana").
        language: The target language for the explanation (e.g. hindi, english, tamil).
    """
    async with async_session() as db:
        query = select(Scheme).where(
            (Scheme.name_en.ilike(f"%{scheme_name}%")) | (Scheme.name_hi.ilike(f"%{scheme_name}%"))
        )
        result = await db.execute(query)
        scheme = result.scalar_one_or_none()

        if not scheme:
            return f"Scheme '{scheme_name}' not found in the Jan Sahayak database."

        explanation = await scheme_engine.explain_scheme(scheme, language=language)
        return explanation


@mcp.tool()
async def get_application_guide(scheme_name: str, state: str = "", language: str = "hindi") -> str:
    """
    Get personalized step-by-step instructions and required documents to apply for a scheme.

    Args:
        scheme_name: The name or English/Hindi title of the scheme.
        state: Citizen's state of residence for any state-specific application procedures.
        language: The target language for the guide.
    """
    async with async_session() as db:
        query = select(Scheme).where(
            (Scheme.name_en.ilike(f"%{scheme_name}%")) | (Scheme.name_hi.ilike(f"%{scheme_name}%"))
        )
        result = await db.execute(query)
        scheme = result.scalar_one_or_none()

        if not scheme:
            return f"Scheme '{scheme_name}' not found."

        profile = {"state": state} if state else {}
        guide = await scheme_engine.generate_application_guide(scheme, user_profile=profile, language=language)
        return guide


# =============================================================================
# Resources (Read-only data endpoints)
# =============================================================================

@mcp.resource("schemes://list")
async def list_all_schemes() -> str:
    """Read-only list of all active welfare schemes available in Jan Sahayak."""
    async with async_session() as db:
        result = await db.execute(select(Scheme).where(Scheme.is_active == True))
        schemes = result.scalars().all()
        
        list_data = []
        for s in schemes:
            list_data.append({
                "id": s.id,
                "name_en": s.name_en,
                "name_hi": s.name_hi,
                "ministry": s.ministry,
                "category": s.category,
                "uri": f"schemes://{s.id}"
            })
        return json.dumps(list_data, indent=2, ensure_ascii=False)


@mcp.resource("schemes://{scheme_id}")
async def get_scheme_detail(scheme_id: str) -> str:
    """Detailed JSON representation of a specific scheme by its ID."""
    async with async_session() as db:
        result = await db.execute(select(Scheme).where(Scheme.id == scheme_id))
        scheme = result.scalar_one_or_none()
        
        if not scheme:
            return json.dumps({"error": f"Scheme with ID '{scheme_id}' not found."})
            
        data = {
            "id": scheme.id,
            "name_en": scheme.name_en,
            "name_hi": scheme.name_hi,
            "description_en": scheme.description_en,
            "description_hi": scheme.description_hi,
            "ministry": scheme.ministry,
            "category": scheme.category,
            "eligibility_criteria": scheme.eligibility_criteria,
            "benefits": scheme.benefits,
            "application_url": scheme.application_url,
            "documents_required": scheme.documents_required,
            "state_specific": scheme.state_specific,
            "target_states": scheme.target_states,
            "source_url": scheme.source_url,
            "created_at": scheme.created_at.isoformat() if scheme.created_at else None,
            "updated_at": scheme.updated_at.isoformat() if scheme.updated_at else None,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)


# =============================================================================
# Prompts (Reusable instruction templates)
# =============================================================================

@mcp.prompt()
def check_citizen_eligibility(language: str = "hindi") -> str:
    """
    Template for interviewing a citizen to check their eligibility for government schemes.
    """
    return (
        f"You are the Jan Sahayak scheme agent. Help the user check their eligibility for schemes in {language}.\n\n"
        "Follow these steps:\n"
        "1. Warmly greet the citizen in their preferred language.\n"
        "2. Ask them questions one by one to gather their details:\n"
        "   - Indian State of residence\n"
        "   - Category (SC/ST/OBC/General)\n"
        "   - Occupation (e.g. farmer, student, etc.)\n"
        "   - Annual household income\n"
        "   - Age and Gender\n"
        "3. Do not ask all questions at once. Ask them naturally, one at a time.\n"
        "4. Once you have gathered their information, call the `search_schemes` tool to find matching schemes.\n"
        "5. Present the matching schemes to the user. Ask if they want you to explain any specific scheme (using `explain_scheme`) or get the application guide (using `get_application_guide`)."
    )


if __name__ == "__main__":
    # When run as a script, default to stdio transport for local tools like Claude Desktop/Cursor
    mcp.run()
