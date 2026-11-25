"""
 ArtifactService.

Associates a session with its run-specific output_dir and
resolves client-supplied, opaque artifact_id values against a
SERVER-COMPUTED listing of that directory's own files — the client
NEVER supplies, and this service never accepts, a filename or path
directly. artifact_id is a short hash of the real filename, recomputed
fresh on every lookup from the directory's actual current contents, so
there is no persistent mapping to go stale, and no way to request a
file that isn't actually present in the session's own, server-assigned
directory.
"""
from __future__ import annotations

import hashlib
import os


class ArtifactNotFoundError(Exception):
    pass


_CONTENT_TYPES = {
    ".json": "application/json",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".svg": "image/svg+xml",
}


def _guess_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _artifact_id_for(filename: str) -> str:
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()[:12]


class ArtifactService:
    def __init__(self, resolver=None):
        # session_id -> output_dir. Populated ONLY by register_run(), or by the
        # optional `resolver(session_id) -> output_dir | None` callable, which the
        # web app points at the (persistent) session store. Both sources hold values
        # that came from the graph's own state, never from client input. The
        # resolver is what lets downloads keep working after a server restart.
        self._session_output_dirs: dict = {}
        self._resolver = resolver

    def register_run(self, session_id: str, output_dir: str) -> None:
        if output_dir:
            self._session_output_dirs[session_id] = output_dir

    def _owned_output_dir(self, session_id: str) -> str:
        output_dir = self._session_output_dirs.get(session_id)
        if output_dir is None and self._resolver is not None:
            output_dir = self._resolver(session_id)
        if output_dir is None:
            # Distinguishes "session exists but has no run yet" from "no
            # such session" at the caller level (SessionService already
            # raised SessionNotFoundError for the latter) — here it just
            # means nothing is available to list/download yet.
            raise ArtifactNotFoundError("no artifacts registered for this session")
        return output_dir

    def list_artifacts(self, session_id: str) -> list:
        try:
            output_dir = self._owned_output_dir(session_id)
        except ArtifactNotFoundError:
            return []
        if not os.path.isdir(output_dir):
            return []
        artifacts = []
        for filename in sorted(os.listdir(output_dir)):
            full_path = os.path.join(output_dir, filename)
            if not os.path.isfile(full_path):
                continue
            artifacts.append({
                "artifact_id": _artifact_id_for(filename),
                "filename": filename,
                "content_type": _guess_content_type(filename),
                "size_bytes": os.path.getsize(full_path),
            })
        return artifacts

    def get_artifact_path(self, session_id: str, artifact_id: str) -> str:
        """
        Resolves artifact_id to a real filesystem path, scoped strictly
        to this session's own output_dir. Raises ArtifactNotFoundError
        for: an unknown session, an artifact_id that doesn't match any
        file currently in that session's directory, or (defense in
        depth) a resolved path that somehow falls outside output_dir —
        the client-supplied artifact_id is used ONLY as a comparison
        target against hashes this method computes itself; it is never
        joined into a filesystem path.
        """
        output_dir = self._owned_output_dir(session_id)  # raises if unknown
        if not os.path.isdir(output_dir):
            raise ArtifactNotFoundError(artifact_id)

        real_output_dir = os.path.realpath(output_dir)
        for filename in os.listdir(output_dir):
            full_path = os.path.join(output_dir, filename)
            if not os.path.isfile(full_path):
                continue
            if _artifact_id_for(filename) != artifact_id:
                continue
            resolved = os.path.realpath(full_path)
            if not resolved.startswith(real_output_dir + os.sep):
                # Defense in depth only — filename here always came from
                # os.listdir(output_dir) itself, so this should be
                # unreachable, but the check costs nothing and guards
                # against any future refactor accidentally weakening this.
                raise ArtifactNotFoundError(artifact_id)
            return resolved
        raise ArtifactNotFoundError(artifact_id)
