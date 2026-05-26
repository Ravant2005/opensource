import uvicorn
import os
import sys
from pathlib import Path

# Ensure project root is importable when running `python3 ase/run.py`.
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load .env from the project root (one level up from ase/)
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path, override=False)
    print(f"[ASE] Loaded environment from {env_path}")

if __name__ == "__main__":
    host = os.environ.get("ASE_HOST", "127.0.0.1")
    port = int(os.environ.get("ASE_PORT", "8001"))

    print("Starting Autonomous Security Engine (ASE) Platform...")
    print(f"API will be available at http://{host}:{port}")
    print(f"Swagger UI Documentation available at http://{host}:{port}/docs")
    print(f"GEMINI_API_KEY set: {'Yes' if os.environ.get('GEMINI_API_KEY') else 'No (add to .env)'}")
    print(f"GITHUB_TOKEN set:   {'Yes' if os.environ.get('GITHUB_TOKEN') else 'No (add to .env)'}")
    print(f"ASE_DRY_RUN:        {os.environ.get('ASE_DRY_RUN', 'true')}")
    reload_enabled = os.environ.get("ASE_RELOAD", "true").lower() == "true"

    uvicorn.run("ase.api.main:app", host=host, port=port, reload=reload_enabled)
