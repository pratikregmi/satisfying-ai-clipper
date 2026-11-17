
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class SceneAnalysis(Base):
    __tablename__ = "scene_analyses"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    scene_id: Mapped[int] = mapped_column(
        ForeignKey("scenes.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    description: Mapped[str] = mapped_column(Text)

    characters: Mapped[str] = mapped_column(
        Text,
        default="[]",
    )

    actions: Mapped[str] = mapped_column(
        Text,
        default="[]",
    )

    objects: Mapped[str] = mapped_column(
        Text,
        default="[]",
    )

    setting: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    mood: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    raw_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    model_name: Mapped[str] = mapped_column(
        String(100),
        default="qwen3.5:4b",
    )

    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
