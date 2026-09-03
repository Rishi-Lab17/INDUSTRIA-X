"""Shared pytest bootstrap. Imported before any test module: isolated temp
SQLite DB, fast bcrypt, backend on sys.path. No test file may override
DATABASE_URL — one database per pytest session."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["APP_ENV"] = "local"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))
