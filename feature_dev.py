"""Shim — delegates to src.api.feature_cli.

Lets `python feature_dev.py ...` work from the repo root, mirroring
analyze_codebase.py.
"""
from __future__ import annotations

import sys

from src.api.feature_cli import main


if __name__ == "__main__":
    sys.exit(main())
