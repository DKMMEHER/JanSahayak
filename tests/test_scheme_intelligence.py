"""
Unit tests for Scheme Intelligence components (ProfileExtractor, ConversationManager, and Chat endpoint integrations).
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.models.conversation import Message
from jan_sahayak.models.scheme import Scheme
from jan_sahayak.services.conversation_manager import conversation_manager
from jan_sahayak.services.profile_extractor import profile_extractor
from jan_sahayak.services.sarvam import sarvam_service


@pytest.mark.asyncio
async def test_profile_extractor_success(monkeypatch):
    """Test ProfileExtractor parses valid JSON returned by Sarvam Chat."""
    mock_response = json.dumps(
        {
            "name": "Ramesh",
            "state": "Bihar",
            "annual_income": 150000,
            "occupation": "farmer",
            "category": "OBC",
            "family_size": 4,
            "age": 42,
            "gender": "male",
        }
    )

    async def mock_chat(*args, **kwargs):
        return mock_response

    monkeypatch.setattr(sarvam_service, "chat", mock_chat)

    extracted = await profile_extractor.extract_profile("मैं बिहार का किसान हूँ, नाम रमेश है")
    assert extracted["name"] == "Ramesh"
    assert extracted["state"] == "Bihar"
    assert extracted["annual_income"] == 150000
    assert extracted["occupation"] == "farmer"
    assert extracted["category"] == "OBC"


@pytest.mark.asyncio
async def test_conversation_manager_updates_context_and_matches(db_session: AsyncSession, monkeypatch):
    """Test ConversationManager merges context and handles LLM response loop."""
    # 1. Setup a scheme in the database
    scheme = Scheme(
        name_en="Farmer Welfare Scheme",
        name_hi="किसान कल्याण",
        category="Agriculture",
        eligibility_criteria={"max_income": 200000, "occupations": ["farmer"]},
        state_specific=False,
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.flush()

    # 2. Mock profile extraction response
    async def mock_extract_profile(user_msg: str):
        return {"state": "Bihar", "occupation": "farmer", "annual_income": 150000}

    # 3. Mock chat completions response
    async def mock_chat(messages, *args, **kwargs):
        # Verify system prompt has matching schemes info inside it
        system_content = messages[0]["content"]
        assert "किसान कल्याण" in system_content or "Farmer Welfare Scheme" in system_content
        return "नमस्ते रमेश जी, आप किसान कल्याण योजना के पात्र हैं।"

    monkeypatch.setattr(profile_extractor, "extract_profile", mock_extract_profile)
    monkeypatch.setattr(sarvam_service, "chat", mock_chat)

    # 4. Process the message
    result = await conversation_manager.process_message(
        db=db_session, user_message="मैं बिहार का किसान हूँ और १.५ लाख कमाता हूँ", conversation_id=None, language="hindi"
    )

    # 5. Assert results
    assert result["reply"] == "नमस्ते रमेश जी, आप किसान कल्याण योजना के पात्र हैं।"
    assert result["conversation_id"] is not None
    assert len(result["matched_schemes"]) == 1
    assert result["matched_schemes"][0].name_en == "Farmer Welfare Scheme"
    assert result["updated_profile"]["occupation"] == "farmer"
    assert result["updated_profile"]["annual_income"] == 150000

    # 6. Verify messages saved to database
    query = select(Message).where(Message.conversation_id == result["conversation_id"])
    db_result = await db_session.execute(query)
    messages = db_result.scalars().all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_chat_endpoint_integration(client: AsyncClient, db_session: AsyncSession, auth_headers: dict, monkeypatch):
    """Test /api/chat/ endpoint returns matching schemes and profile updates."""
    # 1. Setup scheme
    scheme = Scheme(
        name_en="UP Student Scholarship",
        name_hi="छात्रवृत्ति",
        category="Education",
        eligibility_criteria={"max_income": 300000, "occupations": ["student"]},
        state_specific=True,
        target_states=["Uttar Pradesh"],
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.flush()

    # 2. Mock profile extractor
    async def mock_extract_profile(user_msg: str):
        return {"state": "Uttar Pradesh", "occupation": "student", "annual_income": 80000}

    # 3. Mock chat response
    async def mock_chat(*args, **kwargs):
        return "Congratulations! You qualify for the UP Student Scholarship."

    # 4. Mock text-to-speech
    async def mock_tts(*args, **kwargs):
        return "b64_audio_data"

    monkeypatch.setattr(profile_extractor, "extract_profile", mock_extract_profile)
    monkeypatch.setattr(sarvam_service, "chat", mock_chat)
    monkeypatch.setattr(sarvam_service, "text_to_speech", mock_tts)

    # 5. Send API Request
    payload = {
        "message": "I am a student in UP earning 80k",
        "language": "english",
        "conversation_id": None,
        "input_source": "voice"
    }
    response = await client.post("/api/chat/", json=payload, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Congratulations! You qualify for the UP Student Scholarship."
    assert data["conversation_id"] is not None
    assert data["audio_base64"] == "b64_audio_data"
    assert len(data["matched_schemes"]) == 1
    assert data["matched_schemes"][0]["name_en"] == "UP Student Scholarship"
