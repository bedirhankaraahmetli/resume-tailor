"""Folder and file names (PROMPT.md §5 "Naming"), and where Desktop really is."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .text import slug_ascii

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def clean_component(text: str) -> str:
    """Remove Windows-invalid characters and collapse spaces. Turkish letters stay."""
    text = _INVALID.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def folder_name(company: str | None, position: str) -> str:
    company = clean_component(company or "") or "Unknown Company"
    name = f"{company} - {clean_component(position) or 'Position'}"
    # Windows drops a trailing dot or space from a folder name; "A.Ş." mid-name is fine.
    name = name.rstrip(". ")
    if name.upper() in _RESERVED:
        name = f"_{name}"
    return name


def unique_folder(name: str, *parents: Path) -> str:
    """Append ' (2)', ' (3)', … until the name is free under every parent."""
    candidate, n = name, 1
    while any((p / candidate).exists() for p in parents):
        n += 1
        candidate = f"{name} ({n})"
    return candidate


def pdf_names(owner_slug: str, position: str) -> dict[str, str]:
    slug = slug_ascii(position) or "Position"
    return {
        "en": f"{owner_slug}_{slug}_Resume.pdf",
        "tr": f"{owner_slug}_{slug}_Ozgecmis.pdf",
    }


def desktop_dir() -> Path:
    """The real Desktop, including OneDrive-redirected ones on Windows."""
    if sys.platform == "win32":
        try:
            return Path(_known_folder_desktop())
        except OSError:
            pass
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            value, _ = winreg.QueryValueEx(key, "Desktop")
            return Path(os.path.expandvars(value))
        except OSError:
            pass
    return Path.home() / "Desktop"


def _known_folder_desktop() -> str:
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    # FOLDERID_Desktop
    u = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
    guid = GUID(u.fields[0], u.fields[1], u.fields[2],
                (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
    path = ctypes.c_wchar_p()
    windll = getattr(ctypes, "windll")  # noqa: B009 - Windows-only; plain access fails mypy on Linux
    shell32 = windll.shell32
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    if hr != 0:
        raise OSError(f"SHGetKnownFolderPath failed: {hr}")
    try:
        return str(path.value)
    finally:
        windll.ole32.CoTaskMemFree(path)


def default_out_dir() -> Path:
    return desktop_dir() / "Job Applications"
