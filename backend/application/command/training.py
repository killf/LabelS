from pydantic import BaseModel, ConfigDict, Field, field_validator


class StartTrainingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_model: str = Field(
        default="yolo26s.pt",
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.pt$",
        description="官方 YOLO26 权重名称，或当前任务已有的模型文件名",
    )
    epochs: int = Field(default=100, ge=1, le=10000, description="训练轮数")
    imgsz: int = Field(
        default=1024,
        ge=32,
        le=4096,
        multiple_of=32,
        description="输入图片尺寸，单位像素",
    )
    batch: int = Field(
        default=2, ge=-1, le=1024, description="每批图片数；-1 为自动选择"
    )

    @field_validator("batch")
    @classmethod
    def validate_batch(cls, value: int) -> int:
        if value == 0:
            raise ValueError("batch 必须为 -1 或正整数")
        return value
