"""The owner's untailored base resumes as PDFs, for the web app's Quick apply tab.

They are compiled from `base/en` and `base/tr` exactly as they are, into `base-pdf/` (not
under `base/`, which would change every preset's input hash and mark them all outdated).
A manifest records the hash of `base/**`, so the workflow recompiles only after the base
changes. No LLM is involved.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from .build import compile_pdf, measure
from .config import load_config
from .ledger import now_utc
from .presets import _digest, _normalized, combined_hash

FOLDER = "base-pdf"
Status = Literal["up to date", "outdated", "never built"]


def base_hash(data_dir: Path) -> str:
    hashes = {f.relative_to(data_dir).as_posix(): _digest(_normalized(f))
              for f in sorted((data_dir / "base").rglob("*")) if f.is_file()}
    return combined_hash(hashes)


def _manifest(data_dir: Path) -> dict[str, object] | None:
    path = data_dir / FOLDER / "manifest.json"
    if not path.exists():
        return None
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return data


def status(data_dir: Path) -> Status:
    m = _manifest(data_dir)
    if m is None:
        return "never built"
    return "up to date" if m.get("input_hash") == base_hash(data_dir) else "outdated"


def report(data_dir: Path) -> dict[str, object]:
    m = _manifest(data_dir) or {}
    return {"folder": FOLDER, "status": status(data_dir), "built_at": m.get("built_at"),
            "files": m.get("files", {})}


def build(data_dir: Path) -> dict[str, str]:
    """Compiles both bases and writes base-pdf/. Returns the file names by language."""
    slug = load_config(data_dir).owner.slug
    names = {"en": f"{slug}_Resume.pdf", "tr": f"{slug}_Ozgecmis.pdf"}
    out = data_dir / FOLDER
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rt-base-") as tmp:
        for lang, name in names.items():
            work = Path(tmp) / lang
            shutil.copytree(data_dir / "base" / lang, work)
            pdf = compile_pdf(work)
            pages = measure(pdf).pages
            if pages != 1:
                raise RuntimeError(f"base/{lang} compiles to {pages} pages, not 1")
            shutil.copyfile(pdf, out / name)
    manifest = {"built_at": now_utc().isoformat(timespec="seconds"),
                "input_hash": base_hash(data_dir), "files": names}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
    return names
