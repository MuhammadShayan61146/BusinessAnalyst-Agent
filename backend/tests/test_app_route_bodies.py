"""
Exercises the REAL route-function bodies in backend/app.py without FastAPI.

WHAT THIS IS: a minimal stand-in for the few FastAPI/pydantic names app.py uses
(decorators that return the function unchanged, Depends/Header markers,
HTTPException, FileResponse, BaseModel). It lets us import backend.app and call
each route function directly with a user dict or token, so mistakes in the route
logic (wrong names, wrong status codes, missing ownership checks) are caught.

"""
import base64
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
for _p in (ROOT, os.path.join(ROOT, "Business-Analyst-Agent-main"), os.path.join(ROOT, "tests_main_app")):
    sys.path.insert(0, _p)

REAL_FASTAPI = importlib.util.find_spec("fastapi") is not None


def _install_stub_modules():
    class HTTPException(Exception):
        def __init__(self, status_code, detail=None, headers=None):
            super().__init__(detail)
            self.status_code, self.detail, self.headers = status_code, detail, headers

    class FastAPI:
        def __init__(self, *a, **k): pass
        def add_middleware(self, *a, **k): pass
        def mount(self, *a, **k): pass
        def _route(self, *a, **k):
            return lambda fn: fn
        get = post = _route

    class FileResponse:
        def __init__(self, path, filename=None):
            self.path, self.filename = path, filename

    class _Field:
        def __init__(self, default=None, default_factory=None):
            self.default, self.default_factory = default, default_factory

    class BaseModel:
        def __init__(self, **kwargs):
            for name in getattr(type(self), "__annotations__", {}):
                if name in kwargs:
                    setattr(self, name, kwargs[name])
                else:
                    d = getattr(type(self), name, None)
                    setattr(self, name, d.default_factory() if isinstance(d, _Field) and d.default_factory
                            else (d.default if isinstance(d, _Field) else d))
            for k, v in kwargs.items():
                setattr(self, k, v)

    mods = {
        "fastapi": types.ModuleType("fastapi"),
        "fastapi.middleware": types.ModuleType("fastapi.middleware"),
        "fastapi.middleware.cors": types.ModuleType("fastapi.middleware.cors"),
        "fastapi.responses": types.ModuleType("fastapi.responses"),
        "fastapi.staticfiles": types.ModuleType("fastapi.staticfiles"),
        "pydantic": types.ModuleType("pydantic"),
    }
    mods["fastapi"].FastAPI = FastAPI
    mods["fastapi"].HTTPException = HTTPException
    mods["fastapi"].Depends = lambda fn=None: ("depends", fn)
    mods["fastapi"].Header = lambda default=None: default
    mods["fastapi.middleware.cors"].CORSMiddleware = object
    mods["fastapi.responses"].FileResponse = FileResponse
    mods["fastapi.staticfiles"].StaticFiles = type("StaticFiles", (), {"__init__": lambda self, *a, **k: None})
    mods["pydantic"].BaseModel = BaseModel
    mods["pydantic"].Field = lambda default=None, default_factory=None: _Field(default, default_factory)
    return mods


@unittest.skipIf(REAL_FASTAPI, "real fastapi is installed; test_api.py covers the HTTP layer")
class RouteBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._stubs = _install_stub_modules()
        cls._saved = {k: sys.modules.get(k) for k in cls._stubs}
        sys.modules.update(cls._stubs)
        sys.modules.pop("backend.app", None)
        sys.modules.pop("backend.schemas", None)
        import config.settings as settings
        with mock.patch.object(settings, "SESSION_PERSISTENCE", "memory"):
            import backend.app as app_module
        cls.app = app_module
        cls.HTTPException = cls._stubs["fastapi"].HTTPException

        from backend.auth_service import AuthService
        from backend.session_service import SessionService
        from backend.tests._fake_graph_runner import FakeGraphRunner
        cls.tmp = tempfile.mkdtemp(prefix="route_bodies_")
        app_module._auth = AuthService(app_module._db, admin_usernames=("boss",))
        app_module._session_service = SessionService(
            FakeGraphRunner(output_root=os.path.join(cls.tmp, "runs")), store=app_module._store)
        app_module._auth.create_user("boss", "admin password 1", "admin")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        for k, v in cls._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("backend.app", None)
        sys.modules.pop("backend.schemas", None)

    # helpers
    n = 0

    def user(self):
        RouteBodyTests.n += 1
        name = f"person{RouteBodyTests.n}"
        out = self.app.register(types.SimpleNamespace(username=name, password="a good password"))
        return self.app.current_user("Bearer " + out.token), "Bearer " + out.token

    def status_of(self, fn, *a, **k):
        with self.assertRaises(self.HTTPException) as ctx:
            fn(*a, **k)
        return ctx.exception.status_code

    def complete(self, u):
        sid = self.app.create_session(user=u).session_id
        body = lambda m: types.SimpleNamespace(message=m)
        self.app.submit_message(sid, body("Proj"), user=u)
        out = self.app.submit_message(sid, body("Desc"), user=u)
        self.assertEqual(out.status, "completed")
        return sid

    # tests
    def test_auth_header_parsing_and_errors(self):
        self.assertEqual(self.status_of(self.app.current_user, None), 401)
        self.assertEqual(self.status_of(self.app.current_user, "Basic abc"), 401)
        self.assertEqual(self.status_of(self.app.current_user, "Bearer nope"), 401)

    def test_register_login_me_logout(self):
        body = types.SimpleNamespace(username="dana_1", password="a good password")
        out = self.app.register(body)
        self.assertEqual((out.user.username, out.user.role), ("dana_1", "user"))
        self.assertEqual(self.status_of(self.app.register, body), 409)
        self.assertEqual(self.status_of(self.app.register, types.SimpleNamespace(username="x", password="a good password")), 400)
        self.assertEqual(self.status_of(self.app.register, types.SimpleNamespace(username="boss", password="a good password")), 409)
        login = self.app.login(body)
        user = self.app.current_user("Bearer " + login.token)
        self.assertEqual(self.app.me(user=user).username, "dana_1")
        self.app.logout(authorization="Bearer " + login.token, user=user)
        self.assertEqual(self.status_of(self.app.current_user, "Bearer " + login.token), 401)
        self.assertEqual(self.status_of(self.app.login, types.SimpleNamespace(username="dana_1", password="wrong password")), 401)

    def test_session_flow_hides_internal_fields(self):
        u, _ = self.user()
        created = self.app.create_session(user=u)
        for attr in ("output_dir", "run_id", "user_id"):
            self.assertFalse(hasattr(created, attr))
        sid = self.complete(u)
        self.assertEqual(self.status_of(self.app.submit_message, sid, types.SimpleNamespace(message="x"), user=u), 400)
        self.assertEqual(self.status_of(self.app.submit_message, sid, types.SimpleNamespace(message="x"), user=u), 400)

    def test_empty_message_and_unknown_session(self):
        u, _ = self.user()
        sid = self.app.create_session(user=u).session_id
        self.assertEqual(self.status_of(self.app.submit_message, sid, types.SimpleNamespace(message="  "), user=u), 400)
        self.assertEqual(self.status_of(self.app.get_session, "nope", user=u), 404)

    def test_other_users_get_404_everywhere(self):
        a, _ = self.user()
        b, _ = self.user()
        sid = self.complete(a)
        aid = self.app.list_artifacts(sid, user=a).artifacts[0].artifact_id
        self.assertEqual(self.status_of(self.app.get_session, sid, user=b), 404)
        self.assertEqual(self.status_of(self.app.submit_message, sid, types.SimpleNamespace(message="x"), user=b), 404)
        self.assertEqual(self.status_of(self.app.list_artifacts, sid, user=b), 404)
        self.assertEqual(self.status_of(self.app.download_artifact, sid, aid, user=b), 404)
        self.assertEqual(self.status_of(self.app.resolve_triage, sid, types.SimpleNamespace(concern_ids="all"), user=b), 404)
        self.assertTrue(os.path.isfile(self.app.download_artifact(sid, aid, user=a).path))

    def test_traversal_artifact_id_is_404(self):
        u, _ = self.user()
        sid = self.complete(u)
        for bad in ("../../etc/passwd", "requirements.json", ""):
            self.assertEqual(self.status_of(self.app.download_artifact, sid, bad, user=u), 404)

    def test_history_is_per_user(self):
        a, _ = self.user()
        b, _ = self.user()
        sid_a = self.app.create_session(user=a).session_id
        self.app.create_session(user=b)
        self.assertEqual([s["session_id"] for s in self.app.list_sessions(user=a).sessions], [sid_a])

    def test_resolve_triage_validation_paths(self):
        u, _ = self.user()
        pending = self.app.create_session(user=u).session_id
        self.assertEqual(self.status_of(self.app.resolve_triage, pending, types.SimpleNamespace(concern_ids="all"), user=u), 400)
        sid = self.complete(u)
        self.assertEqual(self.status_of(self.app.resolve_triage, sid, types.SimpleNamespace(concern_ids=7), user=u), 400)
        # completed, but no canonical file written by the fake runner -> clear 400, not a crash
        self.assertEqual(self.status_of(self.app.resolve_triage, sid, types.SimpleNamespace(concern_ids="all"), user=u), 400)

    def test_admin_dependency_and_knowledge_upload(self):
        user, _ = self.user()
        self.assertEqual(self.status_of(self.app.admin_user, user), 403)
        admin_token = self.app.login(types.SimpleNamespace(username="boss", password="admin password 1")).token
        admin = self.app.current_user("Bearer " + admin_token)
        self.assertEqual(self.app.admin_user(admin)["role"], "admin")

        from backend.knowledge_service import KnowledgeService
        from services.vector_store_service import VectorStoreService
        from _fake_vectorstore import FakeVectorStore
        kb, vs = os.path.join(self.tmp, "kb"), os.path.join(self.tmp, "vs")
        os.makedirs(kb, exist_ok=True)
        svc = KnowledgeService(kb, lambda: VectorStoreService(persist_directory=vs, vectorstore=FakeVectorStore(vs)), 200, 20)
        with mock.patch.object(self.app, "_knowledge_service", lambda: svc):
            good = types.SimpleNamespace(filename="../x/guide.md",
                                         content_base64=base64.b64encode(b"Requirements must be testable. " * 20).decode())
            out = self.app.upload_knowledge_document(good, admin=admin)
            self.assertEqual(out["source"], "uploads/guide.md")
            self.assertIn("uploads/guide.md", [d["source"] for d in self.app.list_knowledge_documents(admin=admin)["documents"]])
            self.assertEqual(self.status_of(self.app.upload_knowledge_document,
                             types.SimpleNamespace(filename="a.md", content_base64="%%%"), admin=admin), 400)
            self.assertEqual(self.status_of(self.app.upload_knowledge_document,
                             types.SimpleNamespace(filename="a.exe", content_base64=base64.b64encode(b"zz").decode()), admin=admin), 400)

    def test_health_reports_independent_flags(self):
        h = self.app.health()
        self.assertEqual(h.status, "ok")
        self.assertIsInstance(h.gemini_configured, bool)
        self.assertEqual(h.vector_store_initialized, h.vector_store_chunk_count > 0)

    def test_workflow_unavailable_gives_503(self):
        with mock.patch.object(self.app, "_session_service", None), \
             mock.patch.object(self.app, "_graph_runner_init_error", "langgraph missing"):
            self.assertEqual(self.status_of(self.app._get_session_service), 503)


if __name__ == "__main__":
    unittest.main()
