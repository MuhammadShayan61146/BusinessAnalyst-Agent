
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

from services.document_service import save_doc  # noqa: E402  (real production source, unmodified)
from config.settings import OUTPUT_DIR  # noqa: E402

TEST_FILENAME = "zzz_regression_test_tmp_doc_never_collides_with_real_outputs.docx"


class SaveDocTests(unittest.TestCase):
    def tearDown(self):
        path = os.path.join(OUTPUT_DIR, TEST_FILENAME)
        if os.path.exists(path):
            os.remove(path)

    def test_save_doc_writes_a_file_and_returns_its_path(self):
        path = save_doc(TEST_FILENAME, "Test Title", [("Section A", ["line one", "line two"])])
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(TEST_FILENAME))

    def test_generated_docx_contains_the_title_and_section_heading(self):
        from docx import Document
        path = save_doc(TEST_FILENAME, "My Title", [("My Section", ["only line"])])
        doc = Document(path)
        all_text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("My Title", all_text)
        self.assertIn("My Section", all_text)
        self.assertIn("only line", all_text)

    def test_multiple_sections_each_get_their_own_heading(self):
        from docx import Document
        path = save_doc(
            TEST_FILENAME, "T",
            [("Alpha", ["a1", "a2"]), ("Beta", ["b1"])],
        )
        doc = Document(path)
        all_text = "\n".join(p.text for p in doc.paragraphs)
        for expected in ("Alpha", "a1", "a2", "Beta", "b1"):
            self.assertIn(expected, all_text)

    def test_empty_sections_list_still_produces_a_file_with_just_the_title(self):
        from docx import Document
        path = save_doc(TEST_FILENAME, "Only Title", [])
        doc = Document(path)
        all_text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Only Title", all_text)


if __name__ == "__main__":
    unittest.main()
