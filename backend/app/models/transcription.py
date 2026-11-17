
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


class Transcription(Base):
    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30), default="pending"
    )

    language: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )

    model_name: Mapped[str] = mapped_column(
        String(50), default="base"
    )

    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
    )

    start_time: Mapped[float] = mapped_column(Float)

    end_time: Mapped[float] = mapped_column(Float)

    text: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "ix_transcript_segments_video_start",
            "video_id",
            "start_time",
        ),
    )
