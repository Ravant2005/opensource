import unittest
import tempfile
import os
from ase.learning.dataset import HistoricalPatchDataset, PatchStyleExtractor

class TestHistoricalPatchDataset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = HistoricalPatchDataset(self.tmp.name)

    def tearDown(self):
        self.db.close()
        os.unlink(self.tmp.name)

    def test_store_and_retrieve(self):
        pid = self.db.store_pair(
            repo_slug="curl/curl",
            vulnerable="char *buf = malloc(size);\nstrcpy(buf, input);",
            fixed="char *buf = malloc(size);\nstrncpy(buf, input, size-1);",
            commit_msg="Fix CWE-119 buffer overflow CVE-2023-1234",
            accepted=1,
            cve_ids=["CVE-2023-1234"]
        )
        self.assertIsNotNone(pid)
        results = self.db.find_similar_fixes("CVE-2023-1234")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["repo_slug"], "curl/curl")

    def test_deduplication_on_same_pair(self):
        args = ("repo/a", "vuln_code", "fixed_code", "fix msg", 1)
        self.db.store_pair(*args)
        self.db.store_pair(*args)
        results = self.db.find_similar_fixes("vuln")
        # Should not matter for this query but ensures no crash
        self.assertIsInstance(results, list)

    def test_split_diff(self):
        patch = "-old line\n+new line\n context line"
        vuln, fixed = self.db._split_diff(patch)
        self.assertIn("old line", vuln)
        self.assertIn("new line", fixed)


class TestPatchStyleExtractor(unittest.TestCase):
    def test_goto_error_style(self):
        code = "if (err) goto cleanup_error;\ncleanup_error: free(ptr);"
        style = PatchStyleExtractor().extract([code])
        self.assertEqual(style["error_style"], "goto")

    def test_early_return_style(self):
        code = "if (!ptr) return NULL;\nif (size < 0) return -EINVAL;"
        style = PatchStyleExtractor().extract([code])
        self.assertEqual(style["error_style"], "early_return")

    def test_snake_case_naming(self):
        code = "int calculate_checksum(char *input_buf, int buf_size) { return 0; }"
        style = PatchStyleExtractor().extract([code])
        self.assertEqual(style["naming_style"], "snake_case")

    def test_javadoc_comment_style(self):
        code = "/** @param x input\n * @return result\n */\nvoid foo() {}"
        style = PatchStyleExtractor().extract([code])
        self.assertEqual(style["comment_style"], "javadoc")

if __name__ == "__main__":
    unittest.main()
