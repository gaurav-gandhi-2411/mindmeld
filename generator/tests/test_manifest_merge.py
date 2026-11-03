from __future__ import annotations

"""
Regression tests for the manifest clobber (issue #12): a hi-en-only publish on
2026-07-25 overwrote the published manifest.json with one that had no `en`
section, and the live manifest stayed broken for 100 days.
"""

import json
from pathlib import Path

from manifest import merge_manifests
from publish import _collect_sync_plan


def _day(d: str, n: int = 100) -> dict:
    return {"date": d, "file": f"x/{d}.json.gz", "bytes": n}


def _manifest(langs: dict[str, list[dict]], generated_at: str = "t0") -> dict:
    return {
        "v": 1,
        "generated_at": generated_at,
        "langs": {k: {"model": f"m-{k}", "days": v} for k, v in langs.items()},
    }


class TestMergeManifests:
    def test_single_lang_publish_keeps_other_lang(self) -> None:
        existing = _manifest({"en": [_day("2026-07-01")], "hi-en": [_day("2026-07-01")]})
        new = _manifest({"hi-en": [_day("2026-07-01", 200)]}, generated_at="t1")
        merged = merge_manifests(existing, new)
        assert set(merged["langs"]) == {"en", "hi-en"}
        assert merged["langs"]["en"] == existing["langs"]["en"]
        assert merged["generated_at"] == "t1"

    def test_days_unioned_new_wins_sorted(self) -> None:
        existing = _manifest({"en": [_day("2026-07-01"), _day("2026-07-02")]})
        new = _manifest({"en": [_day("2026-07-03"), _day("2026-07-02", 999)]})
        days = merge_manifests(existing, new)["langs"]["en"]["days"]
        assert [d["date"] for d in days] == ["2026-07-01", "2026-07-02", "2026-07-03"]
        assert days[1]["bytes"] == 999

    def test_new_lang_added_and_model_from_new(self) -> None:
        existing = _manifest({"en": [_day("2026-07-01")]})
        new = {"v": 1, "generated_at": "t1", "langs": {"en": {"model": "m2", "days": []}}}
        merged = merge_manifests(existing, new)
        assert merged["langs"]["en"]["model"] == "m2"
        assert [d["date"] for d in merged["langs"]["en"]["days"]] == ["2026-07-01"]

    def test_empty_existing(self) -> None:
        new = _manifest({"en": [_day("2026-07-01")]})
        assert merge_manifests({}, new) == new


class TestSyncPlanMergesManifest:
    def test_partial_build_does_not_drop_published_lang(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        payloads = tmp_path / "payloads"
        src.mkdir()
        payloads.mkdir()
        published = _manifest({"en": [_day("2026-07-01")], "hi-en": [_day("2026-07-01")]})
        (payloads / "manifest.json").write_text(json.dumps(published), encoding="utf-8")
        built = _manifest({"hi-en": [_day("2026-07-02")]})
        (src / "manifest.json").write_text(json.dumps(built), encoding="utf-8")

        plan = _collect_sync_plan(src, payloads, ["hi-en"])

        src_manifest = next(s for s, d in plan if d.name == "manifest.json")
        synced = json.loads(src_manifest.read_text(encoding="utf-8"))
        assert set(synced["langs"]) == {"en", "hi-en"}
        assert [d["date"] for d in synced["langs"]["hi-en"]["days"]] == [
            "2026-07-01",
            "2026-07-02",
        ]

    def test_no_published_manifest_copies_build_verbatim(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        src.mkdir()
        built = _manifest({"en": [_day("2026-07-01")]})
        text = json.dumps(built)
        (src / "manifest.json").write_text(text, encoding="utf-8")
        _collect_sync_plan(src, tmp_path / "payloads", ["en"])
        assert (src / "manifest.json").read_text(encoding="utf-8") == text
