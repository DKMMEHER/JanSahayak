"""
Unit tests for the Scheme Matching Engine.
Tests the rule-based matching score calculation.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.models.scheme import Scheme
from jan_sahayak.services.scheme_engine import scheme_engine


@pytest.mark.asyncio
async def test_calculate_match_score_success(db_session: AsyncSession):
    """Test matching a user profile to a scheme they are eligible for."""
    # 1. Create a sample scheme with eligibility criteria
    scheme = Scheme(
        name_en="Test Farmer Scheme",
        name_hi="परीक्षण किसान योजना",
        category="Agriculture",
        eligibility_criteria={
            "max_income": 300000,
            "categories": ["OBC", "SC", "ST"],
            "occupations": ["farmer", "agricultural laborer"],
        },
        state_specific=True,
        target_states=["Madhya Pradesh"],
        is_active=True,
    )
    db_session.add(scheme)
    await db_session.flush()

    # 2. Test user profile that matches perfectly
    profile_matching = {
        "annual_income": 150000,
        "category": "OBC",
        "occupation": "farmer",
        "state": "Madhya Pradesh",
    }

    score, reasons = scheme_engine._calculate_match_score(scheme, profile_matching)
    assert score > 0.5
    assert "Income" in reasons[0]
    assert "OBC" in reasons[1]
    assert "Madhya Pradesh" in reasons[2]


@pytest.mark.asyncio
async def test_calculate_match_score_income_too_high(db_session: AsyncSession):
    """Test user profile rejected due to income exceeding the threshold."""
    scheme = Scheme(
        name_en="Test Poor Welfare Scheme",
        eligibility_criteria={"max_income": 100000},
        is_active=True,
    )

    profile_high_income = {
        "annual_income": 150000,
    }

    score, reasons = scheme_engine._calculate_match_score(scheme, profile_high_income)
    assert score == 0.0
    assert len(reasons) == 0


@pytest.mark.asyncio
async def test_calculate_match_score_state_mismatch(db_session: AsyncSession):
    """Test user profile rejected due to target state mismatch."""
    scheme = Scheme(
        name_en="UP State Scheme",
        state_specific=True,
        target_states=["Uttar Pradesh"],
        is_active=True,
    )

    profile_mp = {
        "state": "Madhya Pradesh",
    }

    score, reasons = scheme_engine._calculate_match_score(scheme, profile_mp)
    assert score == 0.0
    assert len(reasons) == 0
