import unittest
import tempfile
import os
from ase.learning.agent import LearningAgent, CommentClass

class TestLearningAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.agent = LearningAgent(db_path=self.tmp.name)

    def tearDown(self):
        self.agent.db.close()
        os.unlink(self.tmp.name)

    def test_classify_approval(self):
        self.assertEqual(self.agent.classify_comment("LGTM, looks good to me!"), CommentClass.APPROVAL)

    def test_classify_rejection(self):
        self.assertEqual(self.agent.classify_comment("NACK, wrong approach here."), CommentClass.REJECTION)

    def test_classify_change_request(self):
        self.assertEqual(self.agent.classify_comment("Please change the variable naming."), CommentClass.CHANGE_REQUEST)

    def test_classify_question(self):
        self.assertEqual(self.agent.classify_comment("Why did you choose this approach?"), CommentClass.QUESTION)

    def test_classify_unknown(self):
        self.assertEqual(self.agent.classify_comment("I see."), CommentClass.UNKNOWN)

    def test_process_comment_approval_updates_profile(self):
        self.agent.process_comment("curl/curl", 42, "LGTM, looks good!")
        profile = self.agent.get_profile("curl/curl")
        self.assertEqual(profile["positive_count"], 1)
        self.assertEqual(profile["negative_count"], 0)

    def test_process_comment_rejection_updates_profile(self):
        self.agent.process_comment("curl/curl", 43, "NACK, this is wrong.")
        profile = self.agent.get_profile("curl/curl")
        self.assertEqual(profile["negative_count"], 1)

    def test_get_profile_default_for_new_repo(self):
        profile = self.agent.get_profile("new/repo")
        self.assertEqual(profile["positive_count"], 0)
        self.assertEqual(profile["negative_count"], 0)

if __name__ == "__main__":
    unittest.main()
