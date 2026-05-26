"""
OCIS — Opensource Contributor Intelligence System
Entry point: python run.py
"""
import uvicorn
from ocis.config import OCIS_HOST, OCIS_PORT

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════╗
║   OCIS — Opensource Contributor Intelligence System  ║
╠══════════════════════════════════════════════════════╣
║   Dashboard : http://{OCIS_HOST}:{OCIS_PORT}/ui          ║
║   API Docs  : http://{OCIS_HOST}:{OCIS_PORT}/docs         ║
║   Health    : http://{OCIS_HOST}:{OCIS_PORT}/api/v1/health ║
╚══════════════════════════════════════════════════════╝
""")
    uvicorn.run(
        "ocis.api.main:app",
        host=OCIS_HOST,
        port=OCIS_PORT,
        reload=True,
        log_level="info",
    )
