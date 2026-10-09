"""Ready-made resume pairs per role family, and their staleness.

A preset is *outdated* when the hash of its inputs differs from the one in its manifest.
Inputs: every file under `base/`, `career-inventory.md`, and this preset's own entry in
`presets.yml` (so editing one preset does not stale the others). Line endings are
normalised first, so a Windows checkout does not mark everything outdated. Nothing is
rebuilt automatically: every rebuild costs API credits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from .config import Preset, load_presets
from .ledger import now_utc
from .models import PresetManifest

Status = Literal["up to date", "outdated", "never built"]


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def input_hashes(data_dir: Path, preset: Preset) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for f in sorted((data_dir / "base").rglob("*")):
        if f.is_file():
            hashes[f.relative_to(data_dir).as_posix()] = _digest(_normalized(f))
    hashes["career-inventory.md"] = _digest(_normalized(data_dir / "career-inventory.md"))
    entry = json.dumps(preset.model_dump(), sort_keys=True, ensure_ascii=False)
    hashes[f"presets.yml#{preset.id}"] = _digest(entry.encode("utf-8"))
    return hashes


def combined_hash(hashes: dict[str, str]) -> str:
    return _digest(json.dumps(hashes, sort_keys=True).encode("utf-8"))


def manifest_path(data_dir: Path, preset: Preset) -> Path:
    return data_dir / "presets" / preset.folder / "manifest.json"


def read_manifest(data_dir: Path, preset: Preset) -> PresetManifest | None:
    p = manifest_path(data_dir, preset)
    if not p.exists():
        return None
    return PresetManifest.model_validate_json(p.read_text(encoding="utf-8"))


def status(data_dir: Path, preset: Preset) -> Status:
    m = read_manifest(data_dir, preset)
    if m is None:
        return "never built"
    current = combined_hash(input_hashes(data_dir, preset))
    return "up to date" if m.input_hash == current else "outdated"


def changed_inputs(data_dir: Path, preset: Preset) -> list[str]:
    m = read_manifest(data_dir, preset)
    if m is None:
        return []
    now = input_hashes(data_dir, preset)
    keys = set(now) | set(m.inputs)
    return sorted(k for k in keys if now.get(k) != m.inputs.get(k))


def write_manifest(data_dir: Path, preset: Preset, provider: str, model: str, cost: float,
                   files: dict[str, str], tool_version: str) -> None:
    hashes = input_hashes(data_dir, preset)
    m = PresetManifest(
        preset_id=preset.id, built_at=now_utc().isoformat(timespec="seconds"),
        provider=provider, model=model, cost_usd=round(cost, 6), tool_version=tool_version,
        input_hash=combined_hash(hashes), inputs=hashes, files=files,
    )
    path = manifest_path(data_dir, preset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(m.model_dump_json(indent=2), encoding="utf-8")


def status_report(data_dir: Path) -> dict[str, object]:
    """Every preset's status, for the web app (it cannot hash the inputs itself: that
    needs the YAML entry in Python's canonical form). Written to `presets/status.json`."""
    rows: list[dict[str, object]] = []
    for p in load_presets(data_dir).presets:
        m = read_manifest(data_dir, p)
        rows.append({
            "id": p.id, "folder": p.folder, "position": p.position,
            "status": status(data_dir, p),
            "changed": changed_inputs(data_dir, p),
            "built_at": m.built_at if m else None,
            "provider": m.provider if m else None,
            "model": m.model if m else None,
            "cost_usd": m.cost_usd if m else None,
            "files": m.files if m else {},
        })
    from .basepdf import report as base_report

    return {"base": base_report(data_dir), "presets": rows}


def write_status_report(data_dir: Path) -> None:
    path = data_dir / "presets" / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(status_report(data_dir), ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
