"""Backward-compat shim — delegates to src.api.cli.

Kept so existing command lines (`python analyze_codebase.py ...`) keep
working after the refactor. New code should import from `src.api.cli`
directly.
"""
from __future__ import annotations

import sys

from src.api.cli import main


if __name__ == "__main__":
    sys.exit(main())
