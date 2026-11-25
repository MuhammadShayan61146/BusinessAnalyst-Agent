"""
FastAPI application: a thin HTTP layer.

All real logic lives in auth_service.py, session_service.py,
artifact_service.py, knowledge_service.py, triage_resolution.py and
graph_runner.py (none import FastAPI). This file translates HTTP requests
into calls on those classes and their results back into HTTP responses.

Run :
    uvicorn backend.app:app --reload --port 8000

Authentication: every endpoint except /api/health, /api/auth/register and
/api/auth/login needs the header   Authorization: Bearer <token>.
Knowledge-base endpoints additionally need the "admin" role.
"""
from __future__ import annotations

import base64
import binascii
import os
import sys

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_DIR = os.path.join(_REPO_ROOT, "Business-Analyst-Agent-main")
for _p in (_APP_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config.settings import (  # noqa: E402
    ADMIN_USERNAMES, ALLOW_REGISTRATION, APP_DB_PATH, AUTH_TOKEN_TTL_HOURS, CHECKPOINT_DB_PATH,
    GEMINI_API_KEY, KNOWLEDGE_BASE_DIR, MAX_UPLOAD_BYTES, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE,
    SESSION_PERSISTENCE, VECTOR_STORE_DIR,
)

from backend.artifact_service import ArtifactNotFoundError, ArtifactService  # noqa: E402
from backend.auth_service import (  # noqa: E402
    AuthService, InvalidCredentialsError, InvalidInputError, InvalidTokenError,
    RegistrationDisabledError, TooManyAttemptsError, UsernameTakenError,
)
from backend.db import Database  # noqa: E402
from backend.graph_runner import RealGraphRunner  # noqa: E402
from backend.knowledge_service import KnowledgeError, KnowledgeService  # noqa: E402
from backend.schemas import (  # noqa: E402
    ArtifactInfo, ArtifactListResponse, AuthResponse, CredentialsRequest, HealthResponse,
    KnowledgeUploadRequest, MessageRequest, SessionHistoryResponse, SessionStateResponse,
    TriageResolveRequest, UserInfo,
)
from backend.session_service import (  # noqa: E402
    InvalidMessageError, SessionAlreadyCompletedError, SessionNotFoundError, SessionService,
)
from backend.session_store import SessionStore  # noqa: E402
from backend.triage_resolution import TriageResolutionError, TriageResolutionService  # noqa: E402

app = FastAPI(title="Business Analyst Agent API", version="1.0")

# Permissive CORS for local development. Authentication uses a bearer header
# (not cookies), so a wildcard origin does not expose logged-in users.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- shared services -----------------------------------------------------------------
_db = Database(APP_DB_PATH if SESSION_PERSISTENCE == "sqlite" else ":memory:")
_auth = AuthService(_db, admin_usernames=ADMIN_USERNAMES, allow_registration=ALLOW_REGISTRATION,
                    token_ttl_seconds=int(AUTH_TOKEN_TTL_HOURS * 3600))
_store = SessionStore(_db)
_artifact_service = ArtifactService(resolver=lambda sid: (_store.get(sid) or {}).get("output_dir"))
_session_service: SessionService = None  # built lazily, see _get_session_service()
_graph_runner_init_error: str = None


def _get_session_service() -> SessionService:
    """Builds the SessionService (and the real LangGraph runner inside it) on
    first use, so the API can still answer /api/health when langgraph or the
    checkpoint package is missing, and report that honestly."""
    global _session_service, _graph_runner_init_error
    if _session_service is None and _graph_runner_init_error is None:
        try:
            runner = RealGraphRunner(persistence=SESSION_PERSISTENCE, checkpoint_db=CHECKPOINT_DB_PATH)
            _session_service = SessionService(runner, store=_store)
        except Exception as e:  # reported via the server log + a generic 503
            _graph_runner_init_error = str(e)
            print(f"[backend] Workflow engine unavailable: {e}")
    if _session_service is None:
        raise HTTPException(status_code=503, detail="The BA workflow engine is not available on this server.")
    return _session_service


def _knowledge_service() -> KnowledgeService:
    def store_factory():
        from services.vector_store_service import VectorStoreService
        return VectorStoreService(persist_directory=VECTOR_STORE_DIR)
    return KnowledgeService(KNOWLEDGE_BASE_DIR, store_factory, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP,
                            max_bytes=MAX_UPLOAD_BYTES)


_triage_service: TriageResolutionService = None


def _get_triage_service() -> TriageResolutionService:
    global _triage_service
    if _triage_service is None:
        from ba_contract_prototype.validator import validate
        _triage_service = TriageResolutionService(validate)
    return _triage_service


# --- authentication dependencies --------------------------------------------------------
def _token_from_header(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.",
                            headers={"WWW-Authenticate": "Bearer"})
    return authorization[7:].strip()


def current_user(authorization: str = Header(default=None)) -> dict:
    try:
        return _auth.authenticate(_token_from_header(authorization))
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Your login has expired. Please sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


def _owned_session(session_id: str, user: dict):
    """Returns the session if `user` owns it; otherwise 404 (never 403), so
    session ids cannot be probed."""
    try:
        return _get_session_service().get_session(session_id, user["user_id"])
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found.")


# --- health ----------------------------------------------------------------------------------
@app.get("/api/health", response_model=HealthResponse)
def health():
    """Reports readiness WITHOUT claiming Gemini or the vector database is
    operational merely because this process started."""
    try:
        import langgraph  # noqa: F401
        langgraph_available = True
    except ImportError:
        langgraph_available = False

    from services.vector_store_service import read_manifest_chunk_count
    chunk_count = read_manifest_chunk_count(VECTOR_STORE_DIR)
    return HealthResponse(
        status="ok", gemini_configured=bool(GEMINI_API_KEY), langgraph_available=langgraph_available,
        vector_store_initialized=chunk_count > 0, vector_store_chunk_count=chunk_count,
        persistence=SESSION_PERSISTENCE, registration_open=ALLOW_REGISTRATION,
    )


# --- authentication ---------------------------------------------------------------------------
@app.post("/api/auth/register", response_model=AuthResponse)
def register(body: CredentialsRequest):
    try:
        _auth.register(body.username, body.password)
        token, user = _auth.login(body.username, body.password)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UsernameTakenError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RegistrationDisabledError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return AuthResponse(token=token, user=UserInfo(username=user["username"], role=user["role"]))


@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: CredentialsRequest):
    try:
        token, user = _auth.login(body.username, body.password)
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TooManyAttemptsError as e:
        raise HTTPException(status_code=429, detail=str(e))
    return AuthResponse(token=token, user=UserInfo(username=user["username"], role=user["role"]))


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default=None), user: dict = Depends(current_user)):
    _auth.logout(_token_from_header(authorization))
    return {"ok": True}


@app.get("/api/auth/me", response_model=UserInfo)
def me(user: dict = Depends(current_user)):
    return UserInfo(username=user["username"], role=user["role"])


# --- sessions ---------------------------------------------------------------------------------
@app.get("/api/sessions", response_model=SessionHistoryResponse)
def list_sessions(user: dict = Depends(current_user)):
    """The signed-in user's own session history (newest first)."""
    records = _get_session_service().list_sessions(user["user_id"])
    return SessionHistoryResponse(sessions=[r.to_history_item() for r in records])


@app.post("/api/sessions", response_model=SessionStateResponse)
def create_session(user: dict = Depends(current_user)):
    record = _get_session_service().create_session(user_id=user["user_id"])
    return SessionStateResponse(**record.to_public_dict())


@app.get("/api/sessions/{session_id}", response_model=SessionStateResponse)
def get_session(session_id: str, user: dict = Depends(current_user)):
    return SessionStateResponse(**_owned_session(session_id, user).to_public_dict())


@app.post("/api/sessions/{session_id}/messages", response_model=SessionStateResponse)
def submit_message(session_id: str, body: MessageRequest, user: dict = Depends(current_user)):
    _owned_session(session_id, user)
    try:
        record = _get_session_service().submit_message(session_id, body.message, user["user_id"])
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found.")
    except SessionAlreadyCompletedError:
        raise HTTPException(status_code=400, detail="This session has already completed.")
    except InvalidMessageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SessionStateResponse(**record.to_public_dict())


@app.post("/api/sessions/{session_id}/triage/resolve", response_model=SessionStateResponse)
def resolve_triage(session_id: str, body: TriageResolveRequest, user: dict = Depends(current_user)):
    """Human triage: mark flagged concerns as reviewed. The new validation
    status is recomputed by the deterministic validator, not set by the caller."""
    record = _owned_session(session_id, user)
    if record.status != "completed" or not record.output_dir:
        raise HTTPException(status_code=400, detail="Triage is available after the analysis has completed.")
    ids = body.concern_ids
    if not (ids == "all" or (isinstance(ids, list) and all(isinstance(i, str) for i in ids))):
        raise HTTPException(status_code=400, detail="concern_ids must be a list of ids, or \"all\".")
    try:
        outcome = _get_triage_service().resolve(record.output_dir, ids, user["username"])
    except TriageResolutionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    updated = _get_session_service().update_result_fields(session_id, {
        "canonical_status": outcome["canonical_status"],
        "canonical_gaps": outcome["canonical_gaps"],
        "canonical_concerns": outcome["canonical_concerns"],
    })
    return SessionStateResponse(**updated.to_public_dict())


# --- artifacts -------------------------------------------------------------------------------
@app.get("/api/sessions/{session_id}/artifacts", response_model=ArtifactListResponse)
def list_artifacts(session_id: str, user: dict = Depends(current_user)):
    _owned_session(session_id, user)
    return ArtifactListResponse(artifacts=[ArtifactInfo(**a) for a in _artifact_service.list_artifacts(session_id)])


@app.get("/api/sessions/{session_id}/artifacts/{artifact_id}")
def download_artifact(session_id: str, artifact_id: str, user: dict = Depends(current_user)):
    _owned_session(session_id, user)
    try:
        path = _artifact_service.get_artifact_path(session_id, artifact_id)
    except ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(path, filename=os.path.basename(path))


# --- knowledge base (administrators only) -------------------------------------------------------
@app.get("/api/knowledge/documents")
def list_knowledge_documents(admin: dict = Depends(admin_user)):
    return {"documents": _knowledge_service().list_documents()}


@app.post("/api/knowledge/documents")
def upload_knowledge_document(body: KnowledgeUploadRequest, admin: dict = Depends(admin_user)):
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64.")
    try:
        return _knowledge_service().add_document(body.filename, data)
    except KnowledgeError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Serves the static frontend at "/" so one `uvicorn backend.app:app` is enough.
_frontend_dir = os.path.join(_REPO_ROOT, "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
