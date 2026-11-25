"""Chunks loaded from a directory carry RELATIVE source names, never server paths."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

from services.document_ingestion_service import DocumentIngestionService  # noqa: E402


class RelativeSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kb_rel_")
        os.makedirs(os.path.join(self.tmp, "uploads"))
        with open(os.path.join(self.tmp, "top.md"), "w") as f:
            f.write("Top level document about requirements. " * 10)
        with open(os.path.join(self.tmp, "uploads", "sub.md"), "w") as f:
            f.write("Uploaded document about security. " * 10)
        self.svc = DocumentIngestionService(chunk_size=200, chunk_overlap=20)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_directory_uses_relative_forward_slash_sources(self):
        sources = {c.source_path for c in self.svc.load_directory(self.tmp).chunks}
        self.assertEqual(sources, {"top.md", "uploads/sub.md"})

    def test_no_chunk_source_or_id_contains_the_absolute_directory(self):
        for c in self.svc.load_directory(self.tmp).chunks:
            self.assertNotIn(self.tmp, c.source_path)
            self.assertNotIn(self.tmp, c.chunk_id)

    def test_chunk_ids_do_not_depend_on_where_the_folder_lives(self):
        other = tempfile.mkdtemp(prefix="kb_rel_other_")
        try:
            shutil.copytree(self.tmp, os.path.join(other, "copy"))
            a = [c.chunk_id for c in self.svc.load_directory(self.tmp).chunks]
            b = [c.chunk_id for c in self.svc.load_directory(os.path.join(other, "copy")).chunks]
            self.assertEqual(sorted(a), sorted(b))
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_load_document_without_base_dir_keeps_old_behaviour(self):
        path = os.path.join(self.tmp, "top.md")
        self.assertEqual(self.svc.load_document(path).chunks[0].source_path, path)


if __name__ == "__main__":
    unittest.main()
