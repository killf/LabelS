from typing import List, Union
from pydantic import BaseModel, Field

from backend.domain.models.task import MediaType


class BasicConfigCommand(BaseModel):
    dataset_data_source_id: int = Field(description="YOLO 数据集的目标 S3 数据源")
    dataset_prefix: str = Field(default="", description="数据集目录，相对于数据源前缀")
    name: str = Field(description="description: task name", max_length=50)
    media_type: Union[MediaType, None] = Field(
        default=None, description="description: media type of task files"
    )
    description: str = Field(
        default=None, description="description: task description", max_length=500
    )
    tips: Union[str, None] = Field(
        default=None, description="description: task tips", max_length=1000
    )


class CollaboratorUpdateCommand(BaseModel):
    user_id: int = Field(description="description: user id")


class CollaboratorBatchCommand(BaseModel):
    user_ids: List[int] = Field(description="description: user ids")


class UpdateCommand(BaseModel):
    ai_model_name: str | None = None
    dataset_data_source_id: int | None = None
    dataset_prefix: str | None = None
    name: Union[str, None] = Field(
        default=None, description="description: task name", max_length=50
    )
    description: Union[str, None] = Field(
        default=None, description="description: task description", max_length=500
    )
    tips: Union[str, None] = Field(
        default=None, description="description: task tips", max_length=1000
    )
    media_type: Union[MediaType, None] = Field(
        default=None, description="description: media type of task files"
    )
    config: Union[str, None] = Field(
        default=None, description="description: task config content"
    )
