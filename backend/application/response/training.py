from datetime import datetime

from pydantic import BaseModel

from backend.domain.models.training_run import TrainingStatus


class TrainingRunResponse(BaseModel):
    id: int
    task_id: int
    created_by: int
    initial_model: str
    parameters: dict
    status: TrainingStatus
    run_id: str | None
    model_name: str | None
    model_available: bool
    log_available: bool
    metrics: dict
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
