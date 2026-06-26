"""
Custom exceptions for Jan Sahayak.

All custom exceptions inherit from JanSahayakError so they can be
caught and rendered as clean JSON responses by the FastAPI exception handlers.

Usage:
    from jan_sahayak.exceptions import SchemeNotFoundError
    raise SchemeNotFoundError("PM-KISAN")
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jan_sahayak.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Base Exception
# =============================================================================


class JanSahayakError(Exception):
    """
    Base exception for all Jan Sahayak errors.
    Every custom exception should inherit from this.
    """

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(self.message)


# =============================================================================
# Sarvam AI Errors
# =============================================================================


class SarvamAPIError(JanSahayakError):
    """Raised when a Sarvam AI API call fails."""

    def __init__(self, service: str, detail: str = ""):
        super().__init__(
            message=f"Sarvam AI {service} service is temporarily unavailable. Please try again. {detail}".strip(),
            status_code=503,
            error_code="SARVAM_API_ERROR",
        )


class SarvamSTTError(SarvamAPIError):
    """Raised when Speech-to-Text fails."""

    def __init__(self, detail: str = ""):
        super().__init__(service="Speech-to-Text", detail=detail)


class SarvamTTSError(SarvamAPIError):
    """Raised when Text-to-Speech fails."""

    def __init__(self, detail: str = ""):
        super().__init__(service="Text-to-Speech", detail=detail)


class SarvamChatError(SarvamAPIError):
    """Raised when the LLM Chat API fails."""

    def __init__(self, detail: str = ""):
        super().__init__(service="Chat", detail=detail)


class SarvamTranslationError(SarvamAPIError):
    """Raised when the Translation API fails."""

    def __init__(self, detail: str = ""):
        super().__init__(service="Translation", detail=detail)


# =============================================================================
# Scheme Errors
# =============================================================================


class SchemeNotFoundError(JanSahayakError):
    """Raised when a scheme cannot be found by ID or name."""

    def __init__(self, identifier: str = ""):
        msg = f"Scheme '{identifier}' not found." if identifier else "Scheme not found."
        super().__init__(
            message=msg,
            status_code=404,
            error_code="SCHEME_NOT_FOUND",
        )


class NoMatchingSchemesError(JanSahayakError):
    """Raised when no schemes match the citizen's profile."""

    def __init__(self):
        super().__init__(
            message="No matching government schemes found for your profile. Please provide more details so we can help you better.",
            status_code=404,
            error_code="NO_MATCHING_SCHEMES",
        )


# =============================================================================
# Conversation Errors
# =============================================================================


class ConversationNotFoundError(JanSahayakError):
    """Raised when a conversation ID is invalid or expired."""

    def __init__(self, conversation_id: str = ""):
        msg = f"Conversation '{conversation_id}' not found." if conversation_id else "Conversation not found."
        super().__init__(
            message=msg,
            status_code=404,
            error_code="CONVERSATION_NOT_FOUND",
        )


class ProfileExtractionError(JanSahayakError):
    """Raised when profile extraction from conversation fails."""

    def __init__(self, detail: str = ""):
        super().__init__(
            message=f"Could not extract profile information from conversation. {detail}".strip(),
            status_code=422,
            error_code="PROFILE_EXTRACTION_ERROR",
        )


# =============================================================================
# Voice / Audio Errors
# =============================================================================


class InvalidAudioError(JanSahayakError):
    """Raised when the uploaded audio file is invalid or unreadable."""

    def __init__(self, detail: str = ""):
        super().__init__(
            message=f"Invalid audio file. Please upload a valid WAV or MP3 file. {detail}".strip(),
            status_code=400,
            error_code="INVALID_AUDIO",
        )


class AudioTooShortError(JanSahayakError):
    """Raised when the audio is too short to transcribe meaningfully."""

    def __init__(self):
        super().__init__(
            message="Audio is too short. Please speak for at least 1 second and try again.",
            status_code=400,
            error_code="AUDIO_TOO_SHORT",
        )


# =============================================================================
# LiveKit Errors
# =============================================================================


class LiveKitError(JanSahayakError):
    """Raised when a LiveKit operation fails."""

    def __init__(self, detail: str = ""):
        super().__init__(
            message=f"Real-time voice service error. {detail}".strip(),
            status_code=503,
            error_code="LIVEKIT_ERROR",
        )


class LiveKitTokenError(LiveKitError):
    """Raised when LiveKit token generation fails."""

    def __init__(self, detail: str = ""):
        super().__init__(detail=f"Could not generate room access token. {detail}".strip())


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(JanSahayakError):
    """Raised when required configuration is missing or invalid."""

    def __init__(self, key: str = ""):
        msg = f"Missing required configuration: {key}. Please check your .env file." if key else "Configuration error."
        super().__init__(
            message=msg,
            status_code=500,
            error_code="CONFIGURATION_ERROR",
        )


# =============================================================================
# FastAPI Exception Handlers
# =============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register custom exception handlers with the FastAPI app.
    Call this in create_app() in main.py.

    Ensures all JanSahayakError subclasses return consistent JSON:
    {
        "error": "SCHEME_NOT_FOUND",
        "message": "Scheme 'xyz' not found.",
        "status_code": 404
    }
    """

    @app.exception_handler(JanSahayakError)
    async def jan_sahayak_error_handler(request: Request, exc: JanSahayakError):
        """Handle all custom Jan Sahayak exceptions."""
        logger.error(
            f"[{exc.error_code}] {exc.message} | path={request.url.path} | method={request.method}",
            exc_info=False,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "status_code": exc.status_code,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        """Catch-all for unhandled exceptions — log full traceback, return clean JSON."""
        logger.error(
            f"[UNHANDLED] {type(exc).__name__}: {exc} | path={request.url.path}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
                "status_code": 500,
            },
        )
