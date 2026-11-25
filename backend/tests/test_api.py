"""
API-level tests using FastAPI's TestClient against backend.app:app.


Run (from the repository root):
    python3 -m unittest backend.tests.test_api -v

The tests replace the app's database/auth/session services with in-memory
ones and the LangGraph runner with FakeGraphRunner, so no langgraph, no
key - only fastapi (+ httpx for TestClient).
"""
import base64
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
for _p in (ROOT, os.path.join(ROOT, "Business-Analyst-Agent-main"), os.path.join(ROOT, "tests_main_app")):
    sys.path.insert(0, _p)

_FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi is not installed in this environment")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import backend.app as app_module
        from backend.auth_service import AuthService
        from backend.db import Database
        from backend.session_service import SessionService
        from backend.session_store import SessionStore
        from backend.tests._fake_graph_runner import FakeGraphRunner

        cls.tmp = tempfile.mkdtemp(prefix="api_test_")
        db = Database(":memory:")
        app_module._db = db
        app_module._auth = AuthService(db, admin_usernames=("boss",), max_failures=5)
        app_module._store = SessionStore(db)
        cls.runner = FakeGraphRunner(output_root=os.path.join(cls.tmp, "runs"))
        app_module._session_service = SessionService(cls.runner, store=app_module._store)
        cls.app_module = app_module
        cls.client = TestClient(app_module.app)
        app_module._auth.create_user("boss", "admin password 1", "admin")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------------
    _counter = 0

    def _new_user(self, role_name=None):
        ApiTests._counter += 1
        name = role_name or f"user{ApiTests._counter}"
        r = self.client.post("/api/auth/register", json={"username": name, "password": "a good password"})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": "Bearer " + r.json()["token"]}

    def _admin(self):
        r = self.client.post("/api/auth/login", json={"username": "boss", "password": "admin password 1"})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": "Bearer " + r.json()["token"]}

    def _complete_session(self, headers):
        sid = self.client.post("/api/sessions", headers=headers).json()["session_id"]
        self.client.post(f"/api/sessions/{sid}/messages", json={"message": "Project"}, headers=headers)
        r = self.client.post(f"/api/sessions/{sid}/messages", json={"message": "Does things"}, headers=headers)
        self.assertEqual(r.json()["status"], "completed")
        return sid

    # -- health -------------------------------------------------------------------
    def test_health_is_public_and_structured(self):
        body = self.client.get("/api/health").json()
        for key in ("gemini_configured", "langgraph_available", "vector_store_initialized", "persistence"):
            self.assertIn(key, body)

    # -- authentication ----------------------------------------------------------
    def test_endpoints_require_a_token(self):
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)
        self.assertEqual(self.client.post("/api/sessions").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/sessions", headers={"Authorization": "Bearer nope"}).status_code, 401)

    def test_register_login_me_logout(self):
        r = self.client.post("/api/auth/register", json={"username": "carol_x", "password": "a good password"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"], {"username": "carol_x", "role": "user"})
        self.assertEqual(self.client.post("/api/auth/register",
                                          json={"username": "carol_x", "password": "a good password"}).status_code, 409)
        login = self.client.post("/api/auth/login", json={"username": "carol_x", "password": "a good password"})
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).json()["username"], "carol_x")
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_bad_registration_and_login(self):
        self.assertEqual(self.client.post("/api/auth/register",
                                          json={"username": "x", "password": "a good password"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register",
                                          json={"username": "validname", "password": "short"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register",
                                          json={"username": "boss", "password": "a good password"}).status_code, 409)
        self.assertEqual(self.client.post("/api/auth/login",
                                          json={"username": "nobody", "password": "whatever123"}).status_code, 401)

    # -- sessions -----------------------------------------------------------------
    def test_full_conversation_and_no_internal_paths_in_responses(self):
        h = self._new_user()
        created = self.client.post("/api/sessions", headers=h).json()
        self.assertEqual(created["status"], "waiting_for_input")
        for forbidden in ("output_dir", "run_id", "user_id"):
            self.assertNotIn(forbidden, created)
        sid = created["session_id"]
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/messages", json={"message": "P"}, headers=h)
                         .json()["status"], "waiting_for_input")
        done = self.client.post(f"/api/sessions/{sid}/messages", json={"message": "D"}, headers=h).json()
        self.assertEqual(done["status"], "completed")
        self.assertNotIn(self.tmp, json.dumps(done))

    def test_invalid_input_and_unknown_session(self):
        h = self._new_user()
        self.assertEqual(self.client.get("/api/sessions/does-not-exist", headers=h).status_code, 404)
        self.assertEqual(self.client.post("/api/sessions/bogus/messages", json={"message": "x"}, headers=h).status_code, 404)
        sid = self.client.post("/api/sessions", headers=h).json()["session_id"]
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/messages", json={"message": "  "}, headers=h).status_code, 400)

    def test_message_after_completion_is_rejected(self):
        h = self._new_user()
        sid = self._complete_session(h)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/messages", json={"message": "c"}, headers=h).status_code, 400)

    def test_history_lists_only_my_sessions(self):
        a, b = self._new_user(), self._new_user()
        sid_a = self.client.post("/api/sessions", headers=a).json()["session_id"]
        self.client.post("/api/sessions", headers=b)
        mine = [s["session_id"] for s in self.client.get("/api/sessions", headers=a).json()["sessions"]]
        self.assertEqual(mine, [sid_a])

    def test_another_user_gets_404_for_session_artifacts_and_downloads(self):
        a, b = self._new_user(), self._new_user()
        sid = self._complete_session(a)
        artifacts = self.client.get(f"/api/sessions/{sid}/artifacts", headers=a).json()["artifacts"]
        self.assertGreater(len(artifacts), 0)
        aid = artifacts[0]["artifact_id"]
        self.assertEqual(self.client.get(f"/api/sessions/{sid}", headers=b).status_code, 404)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/messages", json={"message": "x"}, headers=b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}/artifacts", headers=b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}/artifacts/{aid}", headers=b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}/artifacts/{aid}", headers=a).status_code, 200)

    def test_path_traversal_artifact_id_rejected(self):
        h = self._new_user()
        sid = self._complete_session(h)
        r = self.client.get(f"/api/sessions/{sid}/artifacts/..%2F..%2Fetc%2Fpasswd", headers=h)
        self.assertIn(r.status_code, (400, 404, 422))

    # -- triage resolution -------------------------------------------------------------
    def _write_canonical_with_concern(self, sid):
        from adapter.adapter import adapt
        from ba_contract_prototype.validator import validate
        legacy = {
            "project": {"name": "P", "description": "D", "type": "web"}, "qa": [], "ui": {}, "validation": {},
            "analysis": {"objectives": ["o"], "stakeholders": [], "risks": [], "data_entities": ["E"],
                         "functional_requirements": [{"id": "FR-1", "text": "The system shall export", "feature": "e"}],
                         "non_functional_requirements": ["fast"], "scope": {"in": ["x"], "out": []},
                         "business_case": "bc", "tasks": ["t"]},
            "user_stories": [{"id": "US-1", "as_a": "u", "i_want": "w", "so_that": "s", "fr_ids": ["FR-1"], "priority": "Must"}],
            "acceptance_criteria": [{"id": "AC-1", "story_id": "US-1", "given": "g", "when": "w", "then": "t"}],
        }
        result = adapt(legacy)
        result.contract["human_flagged_concerns"] = [
            {"id": "TRI-001", "type": "ambiguity", "description": "vague", "related_ids": ["NFR-001"], "resolved": False}]
        vr = validate(result.contract)
        out_dir = self.app_module._store.get(sid)["output_dir"]
        with open(os.path.join(out_dir, "canonical_requirements.json"), "w") as f:
            json.dump({"canonical_status": vr.state, "canonical_contract": result.contract}, f)
        return vr.state

    def test_resolving_triage_recomputes_status_through_the_validator(self):
        h = self._new_user()
        sid = self._complete_session(h)
        self.assertEqual(self._write_canonical_with_concern(sid), "requires_human_review")
        r = self.client.post(f"/api/sessions/{sid}/triage/resolve", json={"concern_ids": ["TRI-001"]}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["result"]["canonical_status"], "passed")

    def test_triage_resolve_validation_and_ownership(self):
        a, b = self._new_user(), self._new_user()
        sid = self._complete_session(a)
        self._write_canonical_with_concern(sid)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/triage/resolve", json={"concern_ids": ["TRI-001"]}, headers=b).status_code, 404)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/triage/resolve", json={"concern_ids": ["TRI-999"]}, headers=a).status_code, 400)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/triage/resolve", json={"concern_ids": 5}, headers=a).status_code, 400)

    # -- knowledge base (admin only) --------------------------------------------------
    def _patch_knowledge(self):
        from backend.knowledge_service import KnowledgeService
        from services.vector_store_service import VectorStoreService
        from _fake_vectorstore import FakeVectorStore
        kb, vs = os.path.join(self.tmp, "kb"), os.path.join(self.tmp, "vs")
        os.makedirs(kb, exist_ok=True)
        svc = KnowledgeService(kb, lambda: VectorStoreService(persist_directory=vs, vectorstore=FakeVectorStore(vs)), 200, 20)
        self.app_module._knowledge_service = lambda: svc

    def test_knowledge_endpoints_are_admin_only(self):
        self._patch_knowledge()
        user = self._new_user()
        body = {"filename": "a.md", "content_base64": base64.b64encode(b"hello world " * 20).decode()}
        self.assertEqual(self.client.get("/api/knowledge/documents").status_code, 401)
        self.assertEqual(self.client.get("/api/knowledge/documents", headers=user).status_code, 403)
        self.assertEqual(self.client.post("/api/knowledge/documents", json=body, headers=user).status_code, 403)

    def test_admin_can_upload_and_list_and_bad_uploads_are_rejected(self):
        self._patch_knowledge()
        admin = self._admin()
        body = {"filename": "../../guide.md", "content_base64": base64.b64encode(b"Requirements must be testable. " * 20).decode()}
        r = self.client.post("/api/knowledge/documents", json=body, headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["source"], "uploads/guide.md")
        listing = self.client.get("/api/knowledge/documents", headers=admin).json()["documents"]
        self.assertIn("uploads/guide.md", [d["source"] for d in listing])
        self.assertEqual(self.client.post("/api/knowledge/documents", headers=admin,
                         json={"filename": "x.md", "content_base64": "%%%not base64"}).status_code, 400)
        self.assertEqual(self.client.post("/api/knowledge/documents", headers=admin,
                         json={"filename": "x.exe", "content_base64": base64.b64encode(b"abc").decode()}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
