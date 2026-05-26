import unittest
import tempfile
import shutil
from pathlib import Path
from ase.core.parsers.ingestion import RepoIngestionPipeline
from ase.core.embeddings.pipeline import CodeRAGQuery

class MockEmbedModel:
    def __init__(self, dimension=1024):
        self.dimension = dimension
        
    def __call__(self, text: str) -> list[float]:
        # Return a deterministic mock vector based on hash of text
        vec = [0.0] * self.dimension
        val = hash(text) % self.dimension
        vec[val] = 1.0
        return vec


class TestCodeRAGQuery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.staging_dir = tempfile.mkdtemp()
        
        # 1. Setup mock repository files
        self.py_code = """
def calculate_sum(a, b):
    # Adds a and b
    return a + b

def execute_shell_command(cmd):
    # Unsafe shell command execution sink
    import os
    return os.system(cmd)

def buffer_overflow_mitigation(buffer, size):
    # Fixes CVE buffer overflow check
    if len(buffer) > size:
        raise ValueError("Buffer size exceeded")
    return True
"""
        self.write_file("vulnerable.py", self.py_code)
        
        # 2. Run AST Ingestion to populate the staging JSON summaries
        self.ingestion_pipeline = RepoIngestionPipeline(staging_dir=self.staging_dir)
        self.ingestion_pipeline.process_file(
            Path(self.temp_dir) / "vulnerable.py",
            Path(self.temp_dir),
            "python"
        )
        
        # 3. Initialize CodeRAGQuery using mock 1024-dimensional embeddings (matching bge-large scale)
        self.mock_embed = MockEmbedModel(dimension=1024)
        self.query_engine = CodeRAGQuery(
            staging_dir=self.staging_dir,
            src_repo_dir=self.temp_dir,
            embed_model=self.mock_embed
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        shutil.rmtree(self.staging_dir, ignore_errors=True)

    def write_file(self, filename: str, content: str) -> Path:
        p = Path(self.temp_dir) / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_nodes_chunking(self):
        # Verify that chunker sliced the python file into exactly 3 function nodes
        self.assertEqual(len(self.query_engine.nodes), 3)
        
        # Assert metadata is loaded correctly
        node = self.query_engine.nodes[0]
        self.assertIn("calculate_sum", node.metadata["name"])
        self.assertEqual(node.metadata["language"], "python")

    def test_find_similar_functions(self):
        results = self.query_engine.find_similar_functions("def calculate_sum(x, y)", top_k=2)
        
        self.assertEqual(len(results), 2)
        # Verify results structure
        self.assertIn("text", results[0])
        self.assertIn("metadata", results[0])
        self.assertIn("score", results[0])

    def test_find_sink_patterns(self):
        results = self.query_engine.find_sink_patterns("system exec call", top_k=1)
        
        self.assertEqual(len(results), 1)
        # Search is expected to rank execute_shell_command highly due to sparse matching
        self.assertEqual(results[0]["metadata"]["name"], "execute_shell_command")

    def test_find_historical_fixes(self):
        results = self.query_engine.find_historical_fixes("cve mitigation overflow", top_k=1)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["name"], "buffer_overflow_mitigation")

if __name__ == "__main__":
    unittest.main()
