"""Staged files must survive Streamlit reruns until the worker finishes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import uuid

from core.formats import SUPPORTED_EXTENSIONS

ROOT = Path(__file__).resolve().parents[2]


def upload_root() -> Path:
    root = Path(os.getenv('DOCUMIND_UPLOAD_DIR', str(ROOT / '.uploads'))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def stage_upload(filename: str, content: bytes) -> str:
    name = Path(filename.replace('\\', '/')).name
    if not name or Path(name).suffix.lower().lstrip('.') not in SUPPORTED_EXTENSIONS:
        raise ValueError('Select PDF, PPT, PPTX, DOCX, MOL2 or CIF')
    if not content:
        raise ValueError('The uploaded file is empty')
    if len(content) > 200 * 1024 * 1024:
        raise ValueError('Upload exceeds the 200 MB limit')
    folder = upload_root() / uuid.uuid4().hex
    folder.mkdir()
    path = folder / name
    try:
        path.write_bytes(content)
    except Exception:
        shutil.rmtree(folder)
        raise
    return f'{folder.name}/{name}'


def resolve_upload(key: str) -> Path:
    root = upload_root()
    relative = Path(key)
    if relative.is_absolute() or len(relative.parts) != 2:
        raise ValueError('Invalid staged upload key')
    folder, name = relative.parts
    if len(folder) != 32 or any(char not in '0123456789abcdef' for char in folder):
        raise ValueError('Invalid staged upload folder')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.parent.parent != root:
        raise ValueError('Staged upload path escapes upload directory')
    return path


def cleanup_upload(key: str) -> None:
    path = resolve_upload(key)
    path.unlink(missing_ok=True)
    if path.parent.exists():
        path.parent.rmdir()
