import unittest
from ase.patch.scorer import PatchQualityScorer

class TestPatchQualityScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = PatchQualityScorer()

    def test_minimal_diff_focused_patch(self):
        patch = "--- a/f.py\n+++ b/f.py\n@@ -5,1 +5,1 @@\n-    return os.system(cmd)\n+    return subprocess.run(shlex.split(cmd))\n"
        score = self.scorer._minimal_diff_score(patch)
        self.assertGreater(score, 0.0)

    def test_style_conformance_valid_python(self):
        code = "def foo(x):\n    return x + 1\n"
        self.assertEqual(self.scorer._style_conformance_score(code, "python"), 1.0)

    def test_style_conformance_invalid_python(self):
        code = "def foo(x)\n    return x"
        self.assertEqual(self.scorer._style_conformance_score(code, "python"), 0.0)

    def test_api_stability_unchanged(self):
        orig = "def calculate(a, b):\n    return a + b"
        patched = "def calculate(a, b):\n    if b == 0: return 0\n    return a + b"
        score = self.scorer._api_stability_score(orig, patched, ["calculate"])
        self.assertEqual(score, 1.0)

    def test_api_stability_changed_signature(self):
        orig = "def calculate(a, b):\n    return a + b"
        patched = "def calculate(a, b, c=0):\n    return a + b + c"
        score = self.scorer._api_stability_score(orig, patched, ["calculate"])
        self.assertLess(score, 1.0)

    def test_false_fix_os_system_remains(self):
        patched = "result = os.system(user_input)"
        score = self.scorer._false_fix_detection_score(patched)
        self.assertLess(score, 1.0)

    def test_false_fix_clean_code(self):
        patched = "result = subprocess.run(['ls', '-la'], capture_output=True)"
        score = self.scorer._false_fix_detection_score(patched)
        self.assertEqual(score, 1.0)

    def test_overall_score_structure(self):
        patch = "--- a/f.py\n+++ b/f.py\n-    bad()\n+    good()\n"
        orig = "def safe(x):\n    bad()\n"
        patched = "def safe(x):\n    good()\n"
        result = self.scorer.score(patch, orig, patched, language="python", public_api_names=["safe"])
        self.assertIn("overall", result)
        self.assertIn("passes_threshold", result)
        self.assertIsInstance(result["overall"], float)

if __name__ == "__main__":
    unittest.main()
