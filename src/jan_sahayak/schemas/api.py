"""
Pydantic schemas for API request/response validation.
These define the shape of data that flows in and out of our API.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ========== Scheme Schemas ==========


class SchemeCreate(BaseModel):
    """Schema for creating a new scheme."""

    name_en: str = Field(..., min_length=1, max_length=500, description="Scheme name in English")
    name_hi: str | None = Field(None, max_length=500, description="Scheme name in Hindi")
    description_en: str | None = Field(None, description="Description in English")
    description_hi: str | None = Field(None, description="Description in Hindi")
    ministry: str | None = Field(None, max_length=255)
    category: str | None = Field(None, max_length=100, description="e.g. Agriculture, Education, Health")
    eligibility_criteria: dict | None = Field(None, description="Structured eligibility rules as JSON")
    benefits: str | None = None
    application_url: str | None = None
    documents_required: list[str] | None = None
    state_specific: bool = False
    target_states: list[str] | None = None
    is_active: bool = True
    source_url: str | None = None


class SchemeResponse(BaseModel):
    """Schema for scheme API response."""

    id: str
    name_en: str
    name_hi: str | None = None
    description_en: str | None = None
    description_hi: str | None = None
    ministry: str | None = None
    category: str | None = None
    eligibility_criteria: dict | None = None
    benefits: str | None = None
    application_url: str | None = None
    documents_required: list | None = None
    state_specific: bool = False
    target_states: list | None = None
    is_active: bool = True
    source_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SchemeListResponse(BaseModel):
    """Paginated list of schemes."""

    schemes: list[SchemeResponse]
    total: int
    page: int
    per_page: int


# ========== User Schemas ==========


class UserProfile(BaseModel):
    """Citizen profile extracted from conversation."""

    phone: str | None = None
    name: str | None = None
    preferred_language: str = "hindi"
    state: str | None = None
    district: str | None = None
    annual_income: float | None = None
    category: str | None = None  # SC/ST/OBC/General
    occupation: str | None = None
    family_size: int | None = None


class UserResponse(BaseModel):
    """User API response."""

    id: str
    phone: str
    name: str | None = None
    preferred_language: str
    state: str | None = None
    district: str | None = None
    annual_income: float | None = None
    category: str | None = None
    occupation: str | None = None
    family_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ========== Chat Schemas ==========


class ChatRequest(BaseModel):
    """Text chat request from citizen."""

    message: str = Field(..., min_length=1, max_length=2000, description="User's text message")
    conversation_id: str | None = Field(None, description="Existing conversation ID to continue")
    language: str = Field("hindi", description="Language of the message")
    input_source: str = Field("text", description="Source of input: 'text' or 'voice'")
    profile_overrides: dict | None = Field(None, description="Profile fields digitized/updated on the client side")


class ChatResponse(BaseModel):
    """Chat response from Jan Sahayak."""

    reply: str
    conversation_id: str
    language: str
    matched_schemes: list[SchemeResponse] | None = None
    audio_base64: str | None = Field(None, description="TTS audio as base64 string")
    updated_profile: dict | None = Field(None, description="Updated user profile context")


# ========== Voice Schemas ==========


class VoiceResponse(BaseModel):
    """Response after processing voice input."""

    transcript: str
    detected_language: str
    reply: str
    conversation_id: str
    matched_schemes: list[SchemeResponse] | None = None
    audio_base64: str | None = Field(None, description="TTS response audio as base64")


# ========== Common Schemas ==========


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    app_name: str
    version: str
    environment: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str | None = None


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    data: Any | None = None


# ========== LiveKit Schemas ==========


class LiveKitTokenRequest(BaseModel):
    """Request schema for generating a LiveKit token."""

    room_name: str = Field(..., description="Name of the room to join")
    identity: str = Field(..., description="Unique identity of the participant (e.g. phone number)")


class LiveKitTokenResponse(BaseModel):
    """Response schema containing the generated token and server details."""

    token: str
    server_url: str


# ========== Authentication Schemas ==========


class RegisterRequest(BaseModel):
    """Schema for user registration."""

    phone: str = Field(..., min_length=10, max_length=15, description="Mobile number")
    name: str | None = Field(None, max_length=255, description="User's full name")


class LoginRequest(BaseModel):
    """Schema for user login."""

    phone: str = Field(..., min_length=10, max_length=15, description="Mobile number")
    otp: str = Field(..., min_length=4, max_length=6, description="One-Time Password (mock)")


class AuthResponse(BaseModel):
    """Auth response containing JWT access token."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse

