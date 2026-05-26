import unittest
from ase.security.behavioral.analyzer import BehavioralAnalyzer, BehavioralFinding

class TestBehavioralAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = BehavioralAnalyzer()

    def test_race_condition_detected(self):
        fns = [{"name": "update_counter", "file_path": "counter.c", "language": "c",
                "body": "counter++;", "calls": [], "accesses_globals": True}]
        findings = self.analyzer.analyze_functions(fns)
        race = [f for f in findings if f.category == "race_condition"]
        self.assertEqual(len(race), 1)
        self.assertEqual(race[0].function_name, "update_counter")

    def test_no_race_condition_with_mutex(self):
        fns = [{"name": "safe_update", "file_path": "safe.c", "language": "c",
                "body": "pthread_mutex_lock(&m);\ncounter++;\npthread_mutex_unlock(&m);",
                "calls": [], "accesses_globals": True}]
        findings = self.analyzer.analyze_functions(fns)
        race = [f for f in findings if f.category == "race_condition"]
        self.assertEqual(len(race), 0)

    def test_privilege_escalation_detected(self):
        fns = [
            {"name": "main", "file_path": "main.c", "language": "c",
             "body": "handle_request();", "calls": ["handle_request"], "accesses_globals": False},
            {"name": "handle_request", "file_path": "main.c", "language": "c",
             "body": "setuid(0);", "calls": ["setuid"], "accesses_globals": False},
        ]
        findings = self.analyzer.analyze_functions(fns)
        priv = [f for f in findings if f.category == "privilege_escalation"]
        self.assertGreater(len(priv), 0)
        self.assertEqual(priv[0].severity, "CRITICAL")

    def test_unsafe_memory_malloc_no_bounds(self):
        fns = [{"name": "alloc_buf", "file_path": "buf.c", "language": "c",
                "body": "char *p = malloc(size);\nstrcpy(p, input);",
                "calls": [], "accesses_globals": False}]
        findings = self.analyzer.analyze_functions(fns)
        mem = [f for f in findings if f.category == "unsafe_memory"]
        self.assertEqual(len(mem), 1)
        self.assertIn("malloc", mem[0].evidence[0])

    def test_use_after_free_detected(self):
        fns = [{"name": "bad_free", "file_path": "uaf.c", "language": "c",
                "body": "free(ptr);\nptr->val = 1;",
                "calls": [], "accesses_globals": False}]
        findings = self.analyzer.analyze_functions(fns)
        mem = [f for f in findings if f.category == "unsafe_memory"]
        uaf = [e for f in mem for e in f.evidence if "use-after-free" in e]
        self.assertTrue(len(uaf) > 0)

    def test_to_dict(self):
        f = BehavioralFinding("race_condition", "desc", "f.c", "foo", ["ev1"])
        d = f.to_dict()
        self.assertIn("category", d)
        self.assertIn("evidence", d)

if __name__ == "__main__":
    unittest.main()
