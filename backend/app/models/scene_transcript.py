from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class SceneTranscriptMatch(Base):
    __tablename__ = "scene_transcript_matches"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
    )

    scene_id: Mapped[int] = mapped_column(
        ForeignKey("scenes.id", ondelete="CASCADE"),
        index=True,
    )

    transcript_segment_id: Mapped[int] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE"),
        index=True,
    )

    overlap_duration: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "transcript_segment_id",
            name="uq_scene_transcript_match",
        ),
        Index(
            "ix_scene_transcript_video_scene",
            "video_id",
            "scene_id",
        ),
    )
