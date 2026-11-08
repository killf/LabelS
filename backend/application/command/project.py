from typing import List, Union, Literal
from pydantic import BaseModel, Field

from backend.domain.models.project import MediaType


class BasicConfigCommand(BaseModel):
    name: str = Field(description="description: project name", max_length=50)
    media_type: Union[MediaType, None] = Field(
        default=None, description="description: media type of project files"
    )
    description: str = Field(
        default=None, description="description: project description", max_length=500
    )
    tips: Union[str, None] = Field(
        default=None, description="description: project tips", max_length=1000
    )


class CollaboratorUpdateCommand(BaseModel):
    user_id: int = Field(description="description: user id")


class CollaboratorBatchCommand(BaseModel):
    user_ids: List[int] = Field(description="description: user ids")


class UpdateCommand(BaseModel):
    ai_algorithm: Literal["yolo"] = "yolo"
    ai_model_name: str | None = None
    name: Union[str, None] = Field(
        default=None, description="description: project name", max_length=50
    )
    description: Union[str, None] = Field(
        default=None, description="description: project description", max_length=500
    )
    tips: Union[str, None] = Field(
        default=None, description="description: project tips", max_length=1000
    )
    media_type: Union[MediaType, None] = Field(
        default=None, description="description: media type of project files"
    )
    config: Union[str, None] = Field(
        default=None, description="description: project config content"
    )
