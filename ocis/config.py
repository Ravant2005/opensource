"""
OCIS Config — single source of truth. All free-tier resources.
"""
import os
from pathlib import Path

_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=_env_path, override=False)
    except ImportError:
        pass

# OpenRouter (free models) — https://openrouter.ai
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", FREE_MODELS[0])

# GitHub
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")

# Free scraping
HN_ALGOLIA_URL    = "https://hn.algolia.com/api/v1"
GITHUB_API_BASE   = "https://api.github.com"
LIBRARIES_IO_KEY  = os.environ.get("LIBRARIES_IO_KEY", "")
REDDIT_CLIENT_ID  = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_SECRET     = os.environ.get("REDDIT_SECRET", "")

# Storage
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///ocis.db")

# Qdrant
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

# Behaviour
OCIS_DRY_RUN                   = False  # Force real actions for legit results
OCIS_MAX_PRS_PER_REPO_PER_WEEK = int(os.environ.get("OCIS_MAX_PRS_PER_REPO_PER_WEEK", "1"))
OCIS_CONTRIBUTION_QUALITY_MIN  = float(os.environ.get("OCIS_CONTRIBUTION_QUALITY_MIN", "0.70"))
OCIS_MAX_CONCURRENT_PIPELINES  = int(os.environ.get("OCIS_MAX_CONCURRENT_PIPELINES", "3"))

# API Server
OCIS_HOST = os.environ.get("OCIS_HOST", "127.0.0.1")
OCIS_PORT = int(os.environ.get("OCIS_PORT", "8001"))
