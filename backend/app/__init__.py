"""RetinaScreen backend. Makes the repository's ML package (src/) importable without copying it."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/app/__init__.py -> repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
