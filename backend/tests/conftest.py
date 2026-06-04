"""Pytest config — make the `app` package importable when running from project root."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
