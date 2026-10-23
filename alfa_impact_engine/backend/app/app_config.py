"""Local paths and opt-in environment; never load configuration from uploaded files."""
import os
from pathlib import Path
from threading import RLock
from dotenv import load_dotenv
from fastapi import Request

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env', override=False)
LOCK = RLock()


def get_service(request: Request):
    with LOCK:
        if getattr(request.app.state, 'research', None) is None:
            from .research import ResearchService
            runtime = Path(os.getenv('APP_RUNTIME_DIR', ROOT / '.runtime')).resolve()
            request.app.state.research = ResearchService(os.getenv('DATABASE_URL', str(runtime / 'impact.sqlite')),
                os.getenv('MATERIALS_DIR', str(ROOT / 'materials')), runtime,
                demo=os.getenv('APP_DEMO_ENABLED', 'true').lower() == 'true')
        return request.app.state.research
