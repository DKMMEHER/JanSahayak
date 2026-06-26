from fastapi import APIRouter, Depends, File, Form, UploadFile, Request
from livekit.api import AccessToken, VideoGrants
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.config import get_settings
from jan_sahayak.database import get_db
from jan_sahayak.exceptions import InvalidAudioError, LiveKitTokenError, SarvamSTTError
from jan_sahayak.logger import get_logger
from jan_sahayak.schemas.api import LiveKitTokenRequest, LiveKitTokenResponse, SchemeResponse, VoiceResponse
from jan_sahayak.services.conversation_manager import conversation_manager
from jan_sahayak.services.sarvam import sarvam_service
from jan_sahayak.limiter import limiter
from jan_sahayak.services.auth import get_current_user
from jan_sahayak.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api/voice", tags=["Voice"])


@router.post("/", response_model=VoiceResponse)
@limiter.limit("15/minute")
async def process_voice_input(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (WAV, MP3, etc.)"),
    language: str = Form("hindi", description="Language hint"),
    conversation_id: str | None = Form(None, description="Existing conversation ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Process voice input: Audio → STT → LLM → TTS → Audio response.
    Full voice-first pipeline using Sarvam AI APIs.
    """
    # Step 1: Read audio file
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise InvalidAudioError(detail="Empty audio file uploaded.")

    # Step 2: Speech-to-Text
    try:
        stt_result = await sarvam_service.speech_to_text(audio_bytes, language=language)
        transcript = stt_result["transcript"]
    except Exception as e:
        logger.error(f"STT error: {e}", exc_info=True)
        raise SarvamSTTError(detail=str(e))

    if not transcript.strip():
        raise InvalidAudioError(detail="Could not understand the audio. Please try again.")

    # Step 3: Detect language (if not provided)
    detected_language = language
    try:
        lang_result = await sarvam_service.detect_language(transcript)
        detected_language = lang_result["language_name"]
    except Exception as e:
        logger.warning(f"Language detection failed (using default): {e}")

    # Step 4: Process via conversation manager (updates context and matches schemes)
    result = await conversation_manager.process_message(
        db=db,
        user_message=transcript,
        conversation_id=conversation_id,
        language=detected_language,
        user_id=current_user.id,
    )

    reply = result["reply"]
    conversation_id_out = result["conversation_id"]
    matched_schemes = result["matched_schemes"]

    # Step 5: Text-to-Speech (convert reply to audio)
    audio_base64 = None
    try:
        audio_base64 = await sarvam_service.text_to_speech(reply, language=detected_language)
    except Exception as e:
        logger.warning(f"TTS failed (non-critical): {e}")

    # Convert Schemes to SchemeResponse
    schemes_response = [SchemeResponse.model_validate(s) for s in matched_schemes] if matched_schemes else None

    return VoiceResponse(
        transcript=transcript,
        detected_language=detected_language,
        reply=reply,
        conversation_id=conversation_id_out,
        matched_schemes=schemes_response,
        audio_base64=audio_base64,
    )


@router.post("/token", response_model=LiveKitTokenResponse)
@limiter.limit("10/minute")
async def get_livekit_token(
    request: Request,
    token_req: LiveKitTokenRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Generate an access token for a LiveKit room.
    Used by the frontend to join the real-time audio channel.
    """
    settings = get_settings()

    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise LiveKitTokenError(detail="LiveKit credentials are not configured on the server.")

    try:
        # Create an access token
        token = AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        # Configure user identity
        token.with_identity(token_req.identity)
        # Grant room permissions (join room and publish/subscribe audio)
        grant = VideoGrants(
            room_join=True,
            room=token_req.room_name,
            can_publish=True,
            can_subscribe=True,
        )
        token.with_grants(grant)

        # Serialize token to JWT string
        token_jwt = token.to_jwt()

        return LiveKitTokenResponse(token=token_jwt, server_url=settings.livekit_url)
    except Exception as e:
        logger.error(f"Failed to generate LiveKit token: {e}", exc_info=True)
        raise LiveKitTokenError(detail=str(e))

