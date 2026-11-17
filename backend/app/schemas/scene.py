
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SceneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: int
    scene_number: int
    start_time: float
    end_time: float
    duration: float
    thumbnail_path: str | None
    created_at: datetime
