
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class MomentCandidate(Base):
    __tablename__ = "moment_candidates"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        default="Untitled moment",
    )

    summary: Mapped[str] = mapped_column(Text)

    start_time: Mapped[float] = mapped_column(Float)

    end_time: Mapped[float] = mapped_column(Float)

    duration: Mapped[float] = mapped_column(Float)

    scene_ids: Mapped[str] = mapped_column(
        Text,
        default="[]",
    )

    transcript_excerpt: Mapped[str] = mapped_column(
        Text,
        default="",
    )

    humor_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    storytelling_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    visual_interest_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    completeness_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    overall_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    evidence: Mapped[str] = mapped_column(
        Text,
        default="{}",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        index=True,
    )

    discovery_version: Mapped[str] = mapped_column(
        String(50),
        default="v1",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index(
            "ix_moment_candidates_video_score",
            "video_id",
            "overall_score",
        ),
        Index(
            "ix_moment_candidates_video_time",
            "video_id",
            "start_time",
        ),
    )
