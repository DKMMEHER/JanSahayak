"""
Scheme and SchemeMatch models — represents welfare schemes and user eligibility matches.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jan_sahayak.database import Base


class Scheme(Base):
    """A government welfare scheme."""

    __tablename__ = "schemes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name_en: Mapped[str] = mapped_column(String(500), nullable=False)
    name_hi: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_hi: Mapped[str | None] = mapped_column(Text, nullable=True)
    ministry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    eligibility_criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    documents_required: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    state_specific: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    target_states: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    matches = relationship("SchemeMatch", back_populates="scheme", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Scheme(id={self.id}, name_en={self.name_en})>"


class SchemeMatch(Base):
    """Tracks a scheme matched to a user during a conversation."""

    __tablename__ = "scheme_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scheme_id: Mapped[str] = mapped_column(String(36), ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Numeric(3, 2), default=0.0, nullable=False)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="scheme_matches")
    scheme = relationship("Scheme", back_populates="matches")

    def __repr__(self) -> str:
        return f"<SchemeMatch(id={self.id}, user_id={self.user_id}, scheme_id={self.scheme_id}, score={self.score})>"
