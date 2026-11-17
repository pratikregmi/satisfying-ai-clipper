
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    file_path: Mapped[str] = mapped_column(String(1000))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    duration: Mapped[float] = mapped_column(Float, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    frame_rate: Mapped[str] = mapped_column(String(30), default="unknown")
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)

    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commercial_rights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
