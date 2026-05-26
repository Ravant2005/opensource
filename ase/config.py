"""
ASE Config — single source of truth for all environment variables.
Loads .env automatically so keys are available regardless of entry point.
"""
import os
from pathlib import Path

# Auto-load .env from project root (two levels up from this file)
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=_env_path, override=False)
    except ImportError:
        pass

# AI / LLM
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")

# GitHub
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")

# Neo4j
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Qdrant
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

# PostgreSQL
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "ase")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "ase")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

# Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# ASE Behaviour
ASE_DRY_RUN = os.environ.get("ASE_DRY_RUN", "true").lower() == "true"
ASE_MAX_PRS_PER_REPO_PER_WEEK = int(os.environ.get("ASE_MAX_PRS_PER_REPO_PER_WEEK", "1"))
ASE_PATCH_QUALITY_THRESHOLD = float(os.environ.get("ASE_PATCH_QUALITY_THRESHOLD", "0.75"))

# NVD (National Vulnerability Database) — optional but removes rate limiting
NVD_API_KEY = os.environ.get("NVD_API_KEY", "")

# Feature recommendation settings
ASE_MAX_FEATURE_RECOMMENDATIONS = int(os.environ.get("ASE_MAX_FEATURE_RECOMMENDATIONS", "3"))
ASE_ENABLE_FEATURE_MODE = os.environ.get("ASE_ENABLE_FEATURE_MODE", "true").lower() == "true"
ASE_ENABLE_CVE_ENRICHMENT = os.environ.get("ASE_ENABLE_CVE_ENRICHMENT", "true").lower() == "true"

# API Server
ASE_HOST = os.environ.get("ASE_HOST", "127.0.0.1")
ASE_PORT = int(os.environ.get("ASE_PORT", "8001"))
