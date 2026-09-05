"""Pytest path configuration and root fixtures for all tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root, scripts, and mcp_server/src are in sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (_REPO_ROOT, _REPO_ROOT / "scripts", _REPO_ROOT / "mcp_server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
