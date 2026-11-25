"""Project paths and environment configuration."""
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")


# OUTPUT_DIR is kept exactly as before for backward compatibility: it is
# still the parent directory for all generated artifacts, and any
# existing caller that imports it directly (e.g. services/document_service.py's
# default, or the pre-existing test suite) keeps working unchanged.
OUTPUT_DIR = str(PROJECT_ROOT / "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")

VECTOR_STORE_DIR = str(PROJECT_ROOT / "vector_store")
KNOWLEDGE_BASE_DIR = str(PROJECT_ROOT / "knowledge_base")
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "800"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
# Relevance score from langchain's similarity_search_with_relevance_scores
# is normalized to roughly [0, 1], higher = more relevant. A chunk scoring
# below this threshold is treated as not relevant enough to cite.
RAG_RELEVANCE_THRESHOLD = float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.25"))

_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _sanitize_for_path(text: str, fallback: str = "project", max_len: int = 40) -> str:
    """
    Turns arbitrary, untrusted text (e.g. a client-supplied project name)
    into a short, filesystem-safe slug. Never used as the sole source of
    uniqueness for a run directory (see new_run_id below) — this exists
    only to make run directories human-readable, and must itself be safe
    even if the input contains path separators, "..", null bytes, or is
    empty/entirely non-alphanumeric.
    """
    if not isinstance(text, str):
        return fallback
    # Strip anything that isn't ASCII letters/digits before slugging, so
    # path separators, "..", drive letters, null bytes, and non-ASCII
    # homoglyph tricks are all removed outright rather than escaped.
    cleaned = _SAFE_SLUG_RE.sub("-", text.strip().lower()).strip("-")
    cleaned = cleaned[:max_len].strip("-")
    return cleaned or fallback


def new_run_id(project_name: str = "") -> str:
    """
    Generates a new, unique, filesystem-safe run ID. Uniqueness comes
    ENTIRELY from the timestamp + random suffix — the sanitized project
    name, if any, is only a human-readable prefix and is never relied on
    for collision avoidance, so two runs with the identical project name
    (even identical malicious/unusual names) can never collide.
    """
    slug = _sanitize_for_path(project_name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{slug}_{timestamp}_{suffix}"


_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


def make_run_output_dir(run_id: str) -> str:
    """
    Creates (if needed) and returns the output directory for one run.

    run_id is expected to come from new_run_id() (already a safe,
    structured token). This function does NOT re-slug it — doing so
    would mangle the timestamp/underscores a valid ID already contains.
    Instead it validates defensively: any run_id that is not a plain
    token of letters/digits/underscore/hyphen (no path separators, no
    "..", no null bytes) is rejected outright rather than silently
    rewritten, since an unsafe value here means a caller bypassed
    new_run_id() and should be fixed at the call site, not patched here.
    """
    if not isinstance(run_id, str) or not _SAFE_RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            f"Unsafe or malformed run_id {run_id!r}; run_id must come from new_run_id()."
        )
    path = os.path.join(RUNS_DIR, run_id)
    os.makedirs(path, exist_ok=True)
    return path

# ---------------------------------------------------------------------------
# Web backend: persistence, authentication and uploads.
#
#   DATA_DIR               where the backend keeps its SQLite files
#   SESSION_PERSISTENCE    "sqlite" (default) keeps conversations across server
#                          restarts; "memory" keeps them only while it runs
#   ADMIN_USERNAMES        comma-separated usernames reserved for administrators.
#                          They cannot be self-registered; create them with
#                          `python3 scripts/create_user.py --admin <name>`
#   ALLOW_REGISTRATION     "true" (default) lets people self-register as normal users
#   AUTH_TOKEN_TTL_HOURS   how long a login token stays valid
#   MAX_UPLOAD_BYTES       size limit for knowledge-base uploads
# ---------------------------------------------------------------------------
DATA_DIR = os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))
SESSION_PERSISTENCE = os.getenv("SESSION_PERSISTENCE", "sqlite").strip().lower()
APP_DB_PATH = os.path.join(DATA_DIR, "app.sqlite")
CHECKPOINT_DB_PATH = os.path.join(DATA_DIR, "checkpoints.sqlite")
ADMIN_USERNAMES = tuple(u.strip() for u in os.getenv("ADMIN_USERNAMES", "").split(",") if u.strip())
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "true").strip().lower() in ("1", "true", "yes")
AUTH_TOKEN_TTL_HOURS = float(os.getenv("AUTH_TOKEN_TTL_HOURS", "12"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
