from enum import Enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from backend.common.db import Base


class AutoLabelStatus(str, Enum):
    PENDING = "PENDING"

    PROCESSING = "PROCESSING"

    COMPLETED = "COMPLETED"

    FAILED = "FAILED"


class AutoLabelJob(Base):
    __tablename__ = "auto_label_job"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    project_id = Column(Integer, ForeignKey("project.id"), index=True)
    created_by = Column(Integer, ForeignKey("user.id"))
    status = Column(String(32), default=AutoLabelStatus.PENDING.value)
    sample_count = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    model_name = Column(
        String(1024),
        nullable=False,
        default="",
        server_default="",
        comment="本批次使用的权重文件名",
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.now, onupdate=datetime.now
    )
