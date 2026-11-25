"""Tests for backend.knowledge_service.KnowledgeService (FakeVectorStore, no network)."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "Business-Analyst-Agent-main"))
sys.path.insert(0, os.path.join(ROOT, "tests_main_app"))

from _fake_vectorstore import FakeVectorStore  # noqa: E402
from backend.knowledge_service import KnowledgeError, KnowledgeService, safe_filename  # noqa: E402
from services.vector_store_service import VectorStoreService  # noqa: E402

DOC = ("Requirements should be testable and traceable. " * 12).encode()


class SafeFilenameTests(unittest.TestCase):
    def test_directory_parts_and_odd_characters_are_removed(self):
        self.assertEqual(safe_filename("../../etc/passwd.md"), "passwd.md")
        self.assertEqual(safe_filename("C:\\Users\\x\\my doc (1)!!.TXT"), "my-doc-1.txt")
        self.assertEqual(safe_filename("%%%.md"), "document.md")  # nothing usable left -> default stem
        with self.assertRaises(KnowledgeError):
            safe_filename("....md")  # only dots: no real extension, rejected rather than guessed

    def test_unsupported_or_missing_names_rejected(self):
        for bad in ("evil.exe", "script.py", "noextension", "", None, "   "):
            with self.subTest(name=bad):
                with self.assertRaises(KnowledgeError):
                    safe_filename(bad)


class KnowledgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kb_service_")
        self.kb = os.path.join(self.tmp, "kb")
        self.vs = os.path.join(self.tmp, "vs")
        os.makedirs(self.kb)
        self.svc = self._service()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _store(self):
        return VectorStoreService(persist_directory=self.vs, vectorstore=FakeVectorStore(self.vs))

    def _service(self, store_factory=None, max_bytes=5 * 1024 * 1024):
        return KnowledgeService(self.kb, store_factory or self._store, 200, 20, max_bytes=max_bytes)

    def test_upload_is_saved_inside_uploads_and_indexed(self):
        out = self.svc.add_document("guide.md", DOC)
        self.assertEqual(out["source"], "uploads/guide.md")
        self.assertEqual(out["status"], "added")
        self.assertGreater(out["chunks"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "uploads", "guide.md")))
        self.assertGreater(self._store().count(), 0)

    def test_uploaded_content_is_retrievable_with_a_relative_source(self):
        self.svc.add_document("guide.md", DOC)
        hits = self._store().similarity_search("testable traceable requirements", k=3, threshold=0.0)
        self.assertTrue(hits)
        self.assertTrue(all(h.source == "uploads/guide.md" for h in hits))

    def test_same_file_again_is_unchanged_and_does_not_duplicate(self):
        self.svc.add_document("guide.md", DOC)
        count = self._store().count()
        self.assertEqual(self.svc.add_document("guide.md", DOC)["status"], "unchanged")
        self.assertEqual(self._store().count(), count)

    def test_changed_content_updates_the_same_source(self):
        self.svc.add_document("guide.md", DOC)
        out = self.svc.add_document("guide.md", b"A completely different and much shorter document text here.")
        self.assertEqual(out["status"], "updated")
        self.assertEqual(self._store().count(), out["chunks"])

    def test_path_traversal_filename_cannot_escape_the_uploads_folder(self):
        out = self.svc.add_document("../../outside.md", DOC)
        self.assertEqual(out["source"], "uploads/outside.md")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "outside.md")))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "outside.md")))

    def test_rejections_leave_nothing_behind(self):
        cases = [("a.exe", DOC), ("empty.md", b""), ("blank.md", b"   \n  "),
                 ("broken.docx", b"this is not a zip file")]
        for name, data in cases:
            with self.subTest(name=name):
                with self.assertRaises(KnowledgeError):
                    self.svc.add_document(name, data)
        uploads = os.path.join(self.kb, "uploads")
        leftovers = os.listdir(uploads) if os.path.isdir(uploads) else []
        self.assertEqual(leftovers, [])
        self.assertEqual(self._store().count(), 0)

    def test_size_limit(self):
        svc = self._service(max_bytes=100)
        with self.assertRaises(KnowledgeError):
            svc.add_document("big.md", b"x" * 101)

    def test_failed_ingestion_removes_a_new_file(self):
        class Boom:
            def add_chunks(self, chunks):
                raise RuntimeError("embedding service down")
        svc = self._service(store_factory=lambda: Boom())
        with self.assertRaises(KnowledgeError) as ctx:
            svc.add_document("guide.md", DOC)
        self.assertIn("rolled back", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "uploads", "guide.md")))

    def test_failed_ingestion_restores_the_previous_version(self):
        self.svc.add_document("guide.md", DOC)

        class Boom:
            def add_chunks(self, chunks):
                raise RuntimeError("down")
        svc = self._service(store_factory=lambda: Boom())
        with self.assertRaises(KnowledgeError):
            svc.add_document("guide.md", b"Replacement text that must not survive the failure. " * 5)
        with open(os.path.join(self.kb, "uploads", "guide.md"), "rb") as f:
            self.assertEqual(f.read(), DOC)

    def test_list_documents_returns_relative_names_only(self):
        with open(os.path.join(self.kb, "seed.md"), "w") as f:
            f.write("seed document")
        self.svc.add_document("guide.md", DOC)
        listing = self.svc.list_documents()
        self.assertEqual(sorted(d["source"] for d in listing), ["seed.md", "uploads/guide.md"])
        self.assertNotIn(self.tmp, str(listing))

    def test_responses_never_contain_server_paths(self):
        out = self.svc.add_document("guide.md", DOC)
        self.assertNotIn(self.tmp, str(out))


if __name__ == "__main__":
    unittest.main()
