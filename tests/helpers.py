from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid


@contextmanager
def workspace_temp_dir():
    root = Path.cwd() / ".tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
