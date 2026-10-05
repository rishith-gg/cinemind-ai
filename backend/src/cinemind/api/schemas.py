"""Pydantic schemas at the API boundary."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    code: str
    message: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class JobStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    name: str
    status: str
    progress: float
    cache_key: str | None
    params_hash: str | None
    model_name: str
    model_version: str
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    media_id: str | None
    chain: str
    status: str
    progress: float
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stages: list[JobStageOut]


class JobEventOut(BaseModel):
    id: int
    job_id: str
    type: str
    data: dict[str, Any]
