from __future__ import annotations

"""
publish._run_build must feed embed_vocab the SAME Devanagari-patched input as
build.py / build_packs.py / build_onboarding.py (hi-en only). Before this fix,
publish.py embedded the raw romanized vocab, so published hi-en payloads silently
lacked the L2 lever that build.py applies.
"""

from datetime import date
from pathlib import Path

import pytest

import build as build_mod
import schedule as schedule_mod
from publish import _run_build
from vocab import apply_devanagari_patch, load_devanagari_patch

_VOCAB = ["junoon", "dost", "registan", "ghar"]


class _StopBuild(Exception):
    """Raised by the fake embed_vocab to stop _run_build right after capture."""


def _capture_embed_input(monkeypatch: pytest.MonkeyPatch, lang: str, tmp_path: Path) -> list[str]:
    captured: list[list[str]] = []

    def fake_embed_vocab(vocab: list[str], lang_: str, **_kw: object) -> None:
        captured.append(list(vocab))
        raise _StopBuild

    monkeypatch.setitem(build_mod.LANG_LOADERS, lang, lambda: list(_VOCAB))
    monkeypatch.setattr(schedule_mod, "validate_schedule", lambda *a, **k: None)
    monkeypatch.setattr("embeddings.embed_vocab", fake_embed_vocab)
    with pytest.raises(_StopBuild):
        _run_build(days=1, langs=[lang], out_dir=tmp_path, start=date(2026, 11, 1))
    return captured[0]


def test_hien_embed_input_is_devanagari_patched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch = load_devanagari_patch()
    assert "junoon" in patch  # guard: the test is meaningless with an empty patch file
    got = _capture_embed_input(monkeypatch, "hi-en", tmp_path)
    assert got == apply_devanagari_patch(_VOCAB)
    assert got[0] == patch["junoon"]
    assert got[1] == "dost"  # unpatched words pass through unchanged


def test_en_embed_input_is_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    got = _capture_embed_input(monkeypatch, "en", tmp_path)
    assert got == _VOCAB
