"""
Chat router — Text-based conversation with Jan Sahayak.
Uses the ConversationManager to parse profiles and match welfare schemes.
"""

import re

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.database import get_db
from jan_sahayak.schemas.api import ChatRequest, ChatResponse, SchemeResponse
from jan_sahayak.services.conversation_manager import conversation_manager
from jan_sahayak.services.sarvam import sarvam_service
from jan_sahayak.logger import get_logger
from jan_sahayak.limiter import limiter
from jan_sahayak.services.auth import get_current_user
from jan_sahayak.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


def detect_language(text: str, fallback_lang: str = "hindi") -> str:
    """Detect language based on Unicode script block counts."""
    counts = {
        "hindi": len(re.findall(r"[\u0900-\u097F]", text)),
        "bengali": len(re.findall(r"[\u0980-\u09FF]", text)),
        "punjabi": len(re.findall(r"[\u0A00-\u0A7F]", text)),
        "gujarati": len(re.findall(r"[\u0A80-\u0AFF]", text)),
        "odia": len(re.findall(r"[\u0B00-\u0B7F]", text)),
        "tamil": len(re.findall(r"[\u0B80-\u0BFF]", text)),
        "telugu": len(re.findall(r"[\u0C00-\u0C7F]", text)),
        "kannada": len(re.findall(r"[\u0C80-\u0CFF]", text)),
        "malayalam": len(re.findall(r"[\u0D00-\u0D7F]", text)),
        "urdu": len(re.findall(r"[\u0600-\u06FF]", text)),
        "english": len(re.findall(r"[a-zA-Z]", text)),
    }
    
    max_lang = fallback_lang
    max_count = 0
    total = 0
    for lang, count in counts.items():
        total += count
        if count > max_count:
            max_count = count
            max_lang = lang
            
    if total == 0:
        return fallback_lang
    return max_lang


@router.post("/", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat_with_assistant(
    request: Request,
    request_data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a text message to Jan Sahayak and get a response."""
    # Auto-detect language from the user's message text, falling back to the requested language
    detected_language = detect_language(request_data.message, fallback_lang=request_data.language)
    logger.info(f"Detected language: {detected_language} (from: {request_data.message[:50]}...)")

    result = await conversation_manager.process_message(
        db=db,
        user_message=request_data.message,
        conversation_id=request_data.conversation_id,
        language=detected_language,
        profile_overrides=request_data.profile_overrides,
        user_id=current_user.id,
    )

    reply = result["reply"]
    conversation_id = result["conversation_id"]
    matched_schemes = result["matched_schemes"]

    # Generate TTS audio only for voice input (ChatGPT-style behavior)
    audio_base64 = None
    if request_data.input_source == "voice":
        try:
            audio_base64 = await sarvam_service.text_to_speech(reply, language=detected_language)
        except Exception as e:
            logger.error(f"TTS generation failed: {e}", exc_info=True)

    # Convert Scheme database models to SchemeResponse schemas
    schemes_response = [SchemeResponse.model_validate(s) for s in matched_schemes] if matched_schemes else None

    return ChatResponse(
        reply=reply,
        conversation_id=conversation_id,
        language=detected_language,
        matched_schemes=schemes_response,
        audio_base64=audio_base64,
        updated_profile=result.get("updated_profile"),
    )


