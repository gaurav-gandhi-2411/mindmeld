from __future__ import annotations

"""
Manifest emitter for Mindmeld payload builds.

The manifest is a public JSON file listing all generated payloads.
It contains NO secret information — only dates, file sizes, and model metadata.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from config import MANIFEST_VERSION, MODELS


def build_manifest(
    lang_days: dict[str, list[dict]],
) -> dict:
    """
    Build a manifest dict from per-lang day records.

    Parameters
    ----------
    lang_days:
        Mapping of lang → list of {"date": str, "file": str, "bytes": int}

    Returns
    -------
    dict
        Manifest ready for json.dumps. No secret info included.
    """
    langs_section: dict[str, dict] = {}
    for lang, days in lang_days.items():
        langs_section[lang] = {
            "model": MODELS.get(lang, "unknown"),
            "days": days,
        }

    return {
        "v": MANIFEST_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "langs": langs_section,
    }


def write_manifest(manifest: dict, out_dir: Path) -> Path:
    """Write the manifest dict as pretty-printed JSON to out_dir/manifest.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "manifest.json"
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path
