
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))
sys.path.insert(0, os.path.dirname(__file__))

from _fake_vectorstore import FakeVectorStore  # noqa: E402
from services.document_ingestion_service import (  # noqa: E402
    DocumentIngestionService, IngestionError, chunk_text, compute_chunk_id, compute_document_hash,
)
from services.vector_store_service import VectorStoreService  # noqa: E402


class ChunkTextTests(unittest.TestCase):
    def test_empty_text_yields_no_chunks(self):
        self.assertEqual(chunk_text("   ", 100, 10), [])

    def test_short_text_yields_one_chunk(self):
        self.assertEqual(chunk_text("hello world", 100, 10), ["hello world"])

    def test_chunking_is_deterministic(self):
        text = "word " * 500
        self.assertEqual(chunk_text(text, 200, 40), chunk_text(text, 200, 40))

    def test_overlap_must_be_smaller_than_chunk_size(self):
        with self.assertRaises(ValueError):
            chunk_text("x" * 1000, 100, 100)

    def test_long_text_produces_multiple_chunks_each_within_size_bound(self):
        text = "word " * 1000
        chunks = chunk_text(text, 200, 30)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 200)


class ChunkIdAndHashTests(unittest.TestCase):
    def test_chunk_id_is_stable_for_identical_inputs(self):
        self.assertEqual(
            compute_chunk_id("/a/b.txt", 0, "hello"),
            compute_chunk_id("/a/b.txt", 0, "hello"),
        )

    def test_chunk_id_differs_for_different_index(self):
        self.assertNotEqual(
            compute_chunk_id("/a/b.txt", 0, "hello"),
            compute_chunk_id("/a/b.txt", 1, "hello"),
        )

    def test_document_hash_changes_when_content_changes(self):
        self.assertNotEqual(compute_document_hash("a"), compute_document_hash("b"))

    def test_document_hash_stable_for_identical_content(self):
        self.assertEqual(compute_document_hash("same"), compute_document_hash("same"))


class DocumentIngestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ingestion_test_")
        self.service = DocumentIngestionService(chunk_size=100, chunk_overlap=20)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_load_txt_document_produces_chunks_with_source_metadata(self):
        path = self._write("doc.txt", "hello world " * 50)
        result = self.service.load_document(path)
        self.assertGreater(len(result.chunks), 0)
        for c in result.chunks:
            self.assertEqual(c.source_path, path)

    def test_empty_document_raises_ingestion_error(self):
        path = self._write("empty.txt", "   ")
        with self.assertRaises(IngestionError):
            self.service.load_document(path)

    def test_unsupported_extension_raises_ingestion_error(self):
        path = self._write("doc.xyz", "some content")
        with self.assertRaises(IngestionError):
            self.service.load_document(path)

    def test_load_directory_skips_unsupported_and_continues_past_bad_files(self):
        self._write("good.txt", "This is a perfectly good document. " * 10)
        self._write("empty.txt", "")
        self._write("ignored.xyz", "unsupported")
        result = self.service.load_directory(self.tmp)
        self.assertGreater(len(result.chunks), 0)  # good.txt still got ingested
        self.assertEqual(len(result.errors), 1)     # empty.txt failed, reported
        self.assertEqual(result.errors[0][0], os.path.join(self.tmp, "empty.txt"))
        self.assertEqual(len(result.skipped_unsupported), 1)

    def test_load_directory_on_missing_directory_reports_error_not_crash(self):
        result = self.service.load_directory("/no/such/directory/at/all")
        self.assertEqual(result.chunks, [])
        self.assertEqual(len(result.errors), 1)

    def test_repeat_load_of_identical_document_produces_identical_chunk_ids(self):
        path = self._write("stable.txt", "Stable content for dedup testing. " * 20)
        first = self.service.load_document(path)
        second = self.service.load_document(path)
        self.assertEqual([c.chunk_id for c in first.chunks], [c.chunk_id for c in second.chunks])


class VectorStoreServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vectorstore_test_")
        self.ingestion = DocumentIngestionService(chunk_size=200, chunk_overlap=20)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_store(self):
        fake_backend = FakeVectorStore(persist_directory=self.tmp)
        return VectorStoreService(persist_directory=self.tmp, vectorstore=fake_backend)

    def _write_and_load(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return self.ingestion.load_document(path).chunks

    def test_empty_store_reports_zero_count_and_empty_search(self):
        store = self._make_store()
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.similarity_search("anything", k=3, threshold=0.0), [])

    def test_add_chunks_then_count_reflects_added_chunks(self):
        store = self._make_store()
        chunks = self._write_and_load("doc.txt", "Checkout flow best practices content. " * 20)
        summary = store.add_chunks(chunks)
        self.assertEqual(summary["added_sources"], [chunks[0].source_path])
        self.assertEqual(store.count(), len(chunks))

    def test_reingesting_unchanged_document_is_skipped_not_duplicated(self):
        store = self._make_store()
        chunks = self._write_and_load("doc.txt", "Unchanging content here. " * 20)
        store.add_chunks(chunks)
        count_after_first = store.count()

        chunks_again = self._write_and_load("doc.txt", "Unchanging content here. " * 20)
        summary = store.add_chunks(chunks_again)
        self.assertEqual(summary["skipped_unchanged_sources"], [chunks_again[0].source_path])
        self.assertEqual(summary["added_sources"], [])
        self.assertEqual(store.count(), count_after_first)  # no duplicate accumulation

    def test_changed_document_replaces_old_chunks_not_accumulates(self):
        store = self._make_store()
        path = os.path.join(self.tmp, "doc.txt")
        with open(path, "w") as f:
            f.write("Original content version one. " * 30)
        chunks_v1 = self.ingestion.load_document(path).chunks
        store.add_chunks(chunks_v1)
        count_v1 = store.count()

        with open(path, "w") as f:
            f.write("Totally different content version two, much shorter.")
        chunks_v2 = self.ingestion.load_document(path).chunks
        summary = store.add_chunks(chunks_v2)

        self.assertEqual(summary["updated_sources"], [path])
        self.assertEqual(store.count(), len(chunks_v2))
        self.assertNotEqual(store.count(), count_v1 + len(chunks_v2))  # old ones were removed, not kept

    def test_store_persists_and_is_visible_from_a_new_instance_pointed_at_same_dir(self):
        store_a = self._make_store()
        chunks = self._write_and_load("doc.txt", "Persisted content for reopen test. " * 20)
        store_a.add_chunks(chunks)

        # Simulate "reopening": brand-new VectorStoreService AND a brand-new
        # FakeVectorStore instance, both pointed at the same persist_directory.
        store_b = self._make_store()
        self.assertEqual(store_b.count(), store_a.count())

    def test_similarity_search_returns_source_and_chunk_id_metadata(self):
        store = self._make_store()
        chunks = self._write_and_load("doc.txt", "Guest checkout reduces cart abandonment. " * 10)
        store.add_chunks(chunks)
        results = store.similarity_search("checkout abandonment", k=3, threshold=0.0)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r.source, chunks[0].source_path)
            self.assertTrue(r.chunk_id)
            self.assertIsInstance(r.score, float)

    def test_similarity_search_threshold_filters_low_relevance_results(self):
        store = self._make_store()
        chunks = self._write_and_load("doc.txt", "Completely unrelated filler content about gardening.")
        store.add_chunks(chunks)
        results = store.similarity_search("quantum financial derivatives", k=3, threshold=0.99)
        self.assertEqual(results, [])  # nothing scores that high against unrelated content


if __name__ == "__main__":
    unittest.main()
