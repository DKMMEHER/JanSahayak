"""
Jan Sahayak — LiveKit Real-time Voice Agent.
Orchestrates real-time conversational STT -> LLM -> TTS pipelines with tool calling.
"""

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, function_tool
from livekit.plugins import sarvam
from sqlalchemy import select

from jan_sahayak.config import get_settings
from jan_sahayak.logger import get_logger, setup_logging

# Load environment variables from .env file
load_dotenv()

# Configure centralized logging (called once)
setup_logging()
logger = get_logger("jan_sahayak.agent")


# =============================================================================
# Agent Tools (Function Calling)
# =============================================================================


@function_tool
async def search_schemes(
    state: str = "",
    occupation: str = "",
    annual_income: float = 0.0,
    category: str = "",
) -> str:
    """
    Search for eligible government schemes in the database based on profile details.

    Args:
        state: State of residence (e.g., "Uttar Pradesh", "Bihar").
        occupation: Citizen's primary job (e.g., "farmer", "carpenter", "unemployed").
        annual_income: Annual household income in Rupees (e.g., 150000).
        category: Caste category (strictly one of: "SC", "ST", "OBC", "General").
    """
    from jan_sahayak.database import async_session
    from jan_sahayak.services.scheme_engine import scheme_engine

    profile = {}
    if state:
        profile["state"] = state
    if occupation:
        profile["occupation"] = occupation
    if annual_income > 0:
        profile["annual_income"] = annual_income
    if category:
        profile["category"] = category

    logger.info(f"Tool called: search_schemes with profile={profile}")

    async with async_session() as db:
        matches = await scheme_engine.find_matching_schemes(db, profile, limit=3)
        if not matches:
            return "No matching schemes found for these profile criteria."

        lines = []
        for idx, item in enumerate(matches, 1):
            scheme = item["scheme"]
            lines.append(
                f"{idx}. {scheme.name_en} (Hindi: {scheme.name_hi or 'N/A'})\n"
                f"   Ministry: {scheme.ministry or 'N/A'}\n"
                f"   Benefits: {scheme.benefits or 'N/A'}\n"
                f"   Brief details: {scheme.description_en or 'N/A'}"
            )
        return "\n\n".join(lines)


@function_tool
async def explain_scheme(scheme_name: str) -> str:
    """
    Explain a specific government scheme in simple language.

    Args:
        scheme_name: The name or English/Hindi name of the scheme (e.g. "PM-KISAN" or "Pradhan Mantri Awas Yojana").
    """
    from jan_sahayak.database import async_session
    from jan_sahayak.models.scheme import Scheme
    from jan_sahayak.services.scheme_engine import scheme_engine

    logger.info(f"Tool called: explain_scheme with scheme_name={scheme_name}")

    async with async_session() as db:
        query = select(Scheme).where(
            (Scheme.name_en.ilike(f"%{scheme_name}%")) | (Scheme.name_hi.ilike(f"%{scheme_name}%"))
        )
        result = await db.execute(query)
        scheme = result.scalar_one_or_none()

        if not scheme:
            return f"Scheme '{scheme_name}' not found in our database."

        explanation = await scheme_engine.explain_scheme(scheme, language="hindi")
        return explanation


@function_tool
async def get_application_guide(scheme_name: str, state: str = "") -> str:
    """
    Get step-by-step instructions and list of required documents to apply for a scheme.

    Args:
        scheme_name: The name of the scheme (e.g. "PM-KISAN").
        state: The citizen's state of residence for any state-specific instructions.
    """
    from jan_sahayak.database import async_session
    from jan_sahayak.models.scheme import Scheme
    from jan_sahayak.services.scheme_engine import scheme_engine

    logger.info(f"Tool called: get_application_guide with scheme_name={scheme_name}, state={state}")

    async with async_session() as db:
        query = select(Scheme).where(
            (Scheme.name_en.ilike(f"%{scheme_name}%")) | (Scheme.name_hi.ilike(f"%{scheme_name}%"))
        )
        result = await db.execute(query)
        scheme = result.scalar_one_or_none()

        if not scheme:
            return f"Scheme '{scheme_name}' not found."

        guide = await scheme_engine.generate_application_guide(
            scheme=scheme,
            user_profile={"state": state} if state else {},
            language="hindi",
        )
        return guide


# =============================================================================
# LiveKit Entrypoint
# =============================================================================


async def entrypoint(ctx: JobContext):
    """Entry point for incoming LiveKit agent jobs."""
    logger.info(f"🏛️ Job received! Connecting to room: {ctx.room.name}...")
    await ctx.connect()
    logger.info("🔌 Connected to LiveKit Room.")

    # 1. Initialize Sarvam AI components
    # Using 'unknown' language setting to enable dynamic Indic language auto-detection for STT
    stt = sarvam.STT(model="saaras:v3", language="unknown")
    tts = sarvam.TTS(target_language_code="hi-IN")
    llm = sarvam.LLM(model="sarvam-30b")

    # 2. Configure Agent Behavior, Instructions, and Tools
    agent = Agent(
        instructions=(
            "You are Jan Sahayak (जन सहायक), a warm and friendly AI assistant helping Indian citizens discover government welfare schemes. "
            "Speak in a simple, polite, and helpful manner. "
            "Ask questions one at a time to understand their profile (income, occupation, state, category). "
            "When you have enough information, use the 'search_schemes' tool to find eligible schemes. "
            "If they want details about a scheme, use the 'explain_scheme' tool. "
            "If they ask how to apply, use the 'get_application_guide' tool. "
            "Always respond in the same language the user uses. Be patient and respectful."
        ),
        stt=stt,
        llm=llm,
        tts=tts,
        tools=[search_schemes, explain_scheme, get_application_guide],
    )

    # 3. Create AgentSession
    session = AgentSession(
        turn_detection="stt",
        min_endpointing_delay=0.8,
    )

    logger.info("🚀 Starting agent session...")
    await session.start(agent, room=ctx.room)
    logger.info("✨ Agent session is running and listening.")


if __name__ == "__main__":
    # Ensure settings are loaded so LangSmith environment is exported
    get_settings()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
