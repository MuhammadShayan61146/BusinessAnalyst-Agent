"""
Pydantic request/response schemas.

Requires `pydantic` (installed automatically alongside `fastapi`).
Imported only by backend/app.py.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    gemini_configured: bool
    langgraph_available: bool
    vector_store_initialized: bool
    vector_store_chunk_count: int
    persistence: str = "memory"
    registration_open: bool = True


class CredentialsRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    username: str
    role: str


class AuthResponse(BaseModel):
    token: str
    user: UserInfo


class SessionStateResponse(BaseModel):
    session_id: str
    status: str  # "waiting_for_input" | "completed" | "error"
    question: Optional[str] = None
    options: list = Field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[dict] = None
    previews: list = Field(default_factory=list)
    triage: list = Field(default_factory=list)


class SessionHistoryItem(BaseModel):
    session_id: str
    title: str
    status: str
    created_at: Optional[float] = None
    updated_at: Optional[float] = None


class SessionHistoryResponse(BaseModel):
    sessions: list  # list[SessionHistoryItem]


class MessageRequest(BaseModel):
    message: str


class TriageResolveRequest(BaseModel):
    # a list of concern ids such as ["TRI-001"], or the string "all"
    concern_ids: Any


class ArtifactInfo(BaseModel):
    artifact_id: str
    filename: str
    content_type: str
    size_bytes: int


class ArtifactListResponse(BaseModel):
    artifacts: list  # list[ArtifactInfo]


class KnowledgeUploadRequest(BaseModel):
    filename: str
    content_base64: str


class ErrorResponse(BaseModel):
    detail: str
