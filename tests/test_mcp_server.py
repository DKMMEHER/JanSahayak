"""
Unit tests for the Jan Sahayak MCP Server.
"""

import json
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.mcp_server import mcp
from jan_sahayak.models.scheme import Scheme
from jan_sahayak.services.sarvam import sarvam_service


@pytest.fixture(autouse=True)
def patch_mcp_db(db_session: AsyncSession, monkeypatch):
    """Automatically redirect MCP server database calls to the in-memory test database."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session():
        yield db_session

    monkeypatch.setattr("jan_sahayak.mcp_server.async_session", mock_session)


@pytest.fixture(autouse=True)
def disable_mcp_dns_protection():
    """Disable DNS rebinding protection during tests to allow client requests from any host."""
    original = mcp.settings.transport_security.enable_dns_rebinding_protection
    mcp.settings.transport_security.enable_dns_rebinding_protection = False
    yield
    mcp.settings.transport_security.enable_dns_rebinding_protection = original


@pytest.mark.asyncio
async def test_mcp_search_schemes_tool(db_session: AsyncSession):
    """Test the search_schemes tool via MCP interface."""
    # 1. Seed a test scheme
    scheme = Scheme(
        name_en="Farmers Direct Support",
        name_hi="किसान सीधा सहयोग",
        category="Agriculture",
        eligibility_criteria={
            "max_income": 250000,
            "occupations": ["farmer"],
        },
        state_specific=False,
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.commit()

    # 2. Call the tool through the MCP registry
    result = await mcp.call_tool("search_schemes", {
        "annual_income": 100000,
        "occupation": "farmer",
    })
    
    # FastMCP call_tool returns a tuple (list[ContentBlock], dict)
    result_text = result[0][0].text
    
    assert "Farmers Direct Support" in result_text
    assert "Agriculture" in result_text
    assert "Match Confidence" in result_text  # Verify that confidence score is displayed


@pytest.mark.asyncio
async def test_mcp_explain_scheme_tool(db_session: AsyncSession, monkeypatch):
    """Test the explain_scheme tool via MCP interface with mocked AI response."""
    # 1. Seed a test scheme
    scheme = Scheme(
        name_en="PM-Awas Yojana",
        name_hi="पीएम आवास योजना",
        category="Housing",
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.commit()

    # 2. Mock Sarvam AI response
    async def mock_chat(*args, **kwargs):
        return "यह एक आवास योजना है।"
    monkeypatch.setattr(sarvam_service, "chat", mock_chat)

    # 3. Call the explain tool
    result = await mcp.call_tool("explain_scheme", {
        "scheme_name": "PM-Awas Yojana",
        "language": "hindi",
    })
    
    result_text = result[0][0].text
    assert result_text == "यह एक आवास योजना है।"


@pytest.mark.asyncio
async def test_mcp_get_application_guide_tool(db_session: AsyncSession, monkeypatch):
    """Test the get_application_guide tool via MCP interface with mocked AI response."""
    # 1. Seed a test scheme
    scheme = Scheme(
        name_en="PM-KISAN",
        name_hi="पीएम किसान",
        category="Agriculture",
        documents_required=["Aadhaar", "Land Records"],
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.commit()

    # 2. Mock Sarvam AI response
    async def mock_chat(*args, **kwargs):
        return "1. आधार कार्ड लाएं।\n2. आवेदन भरें।"
    monkeypatch.setattr(sarvam_service, "chat", mock_chat)

    # 3. Call the application guide tool
    result = await mcp.call_tool("get_application_guide", {
        "scheme_name": "PM-KISAN",
        "state": "Uttar Pradesh",
        "language": "hindi",
    })
    
    result_text = result[0][0].text
    assert "आधार कार्ड लाएं" in result_text


@pytest.mark.asyncio
async def test_mcp_resources(db_session: AsyncSession):
    """Test MCP resources list and detail retrieval."""
    # 1. Seed a test scheme
    scheme = Scheme(
        name_en="Scholarship Scheme",
        name_hi="छात्रवृत्ति",
        category="Education",
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.commit()
    
    scheme_id = scheme.id

    # 2. Test schemes://list resource
    list_content = await mcp.read_resource("schemes://list")
    list_data = json.loads(list_content[0].content)
    
    assert len(list_data) > 0
    assert any(s["id"] == scheme_id for s in list_data)
    assert any(s["name_en"] == "Scholarship Scheme" for s in list_data)

    # 3. Test schemes://{scheme_id} resource
    detail_content = await mcp.read_resource(f"schemes://{scheme_id}")
    detail_data = json.loads(detail_content[0].content)
    
    assert detail_data["id"] == scheme_id
    assert detail_data["name_en"] == "Scholarship Scheme"
    assert detail_data["category"] == "Education"


@pytest.mark.asyncio
async def test_mcp_prompt_template():
    """Test the MCP prompt template retrieval."""
    # get_prompt is a coroutine returning GetPromptResult
    prompt_result = await mcp.get_prompt("check_citizen_eligibility", arguments={"language": "tamil"})
    prompt_text = prompt_result.messages[0].content.text
    
    assert "tamil" in prompt_text
    assert "search_schemes" in prompt_text


def test_mcp_fastapi_endpoints():
    """Test that FastAPI routes for the MCP server are correctly mounted on the application."""
    from jan_sahayak.main import app
    
    mcp_mount = None
    for route in app.routes:
        if getattr(route, "path", None) == "/mcp":
            mcp_mount = route
            break
            
    assert mcp_mount is not None
    assert mcp_mount.app is not None
