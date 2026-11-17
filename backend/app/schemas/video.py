
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VideoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    duration: float
    width: int
    height: int
    frame_rate: str
    has_audio: bool
    file_size: int
    thumbnail_path: str | None
    source_name: str | None
    commercial_rights_confirmed: bool
    created_at: datetime
