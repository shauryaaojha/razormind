"""Make the repo root importable so tests can reach ``scripts/``.

The API source itself is on ``PYTHONPATH`` via the container image
(``apps/api/Dockerfile``), not via this file.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
