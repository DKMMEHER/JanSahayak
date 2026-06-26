"""
User model — represents a citizen using Jan Sahayak.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jan_sahayak.database import Base


class User(Base):
    """A citizen who uses Jan Sahayak to discover government schemes."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone: Mapped[str] = mapped_column(String(15), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(20), default="hindi")
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    annual_income: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # SC/ST/OBC/General
    occupation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    family_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    conversations = relationship("Conversation", back_populates="user", lazy="selectin")
    scheme_matches = relationship("SchemeMatch", back_populates="user", lazy="selectin")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, phone={self.phone}, name={self.name})>"
