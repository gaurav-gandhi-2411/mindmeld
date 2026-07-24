from __future__ import annotations

"""
Unit tests for evals/finetune/assemble_data.py's `variant_source`
(spec-model-excellence.md WORKSTREAM C, item 10) -- pure logic, isolated
from the real ~544-word hinglish vocab and the 1.3M-line Aksharantar corpus
via monkeypatch, matching this repo's existing convention for testing
Aksharantar-dependent code (tests/test_spelling_robustness.py isolates
build_aksharantar_maps/aksharantar_variants_for_secret the same way rather
than reading the real corpus file in a unit test).
"""

from evals.finetune import assemble_data


def _patch_single_word_vocab(monkeypatch, words: frozenset[str], variants_by_word: dict) -> None:
    monkeypatch.setattr(assemble_data, "hinglish_sourced_words", lambda: words)
    monkeypatch.setattr(assemble_data, "build_aksharantar_maps", lambda path: ({}, {}))
    monkeypatch.setattr(
        assemble_data,
        "aksharantar_variants_for_secret",
        lambda word, rom_to_deva, deva_to_rom, max_variants: variants_by_word.get(word, []),
    )


class TestVariantSource:
    def test_excludes_held_out_anchor_word(self, monkeypatch):
        _patch_single_word_vocab(
            monkeypatch,
            frozenset({"baarish", "chaand"}),
            {"baarish": ["barish"], "chaand": ["chand"]},
        )
        mnrl, graded = assemble_data.variant_source(held_out={"baarish"})
        assert mnrl == [{"anchor": "chaand", "positive": "chand", "source": "variant"}]
        assert graded == [
            {
                "sentence1": "chaand",
                "sentence2": "chand",
                "score": assemble_data.ALIAS_SCORE,
                "source": "variant",
            }
        ]

    def test_excludes_held_out_variant_word(self, monkeypatch):
        _patch_single_word_vocab(
            monkeypatch, frozenset({"chaand"}), {"chaand": ["chand", "held_out_variant"]}
        )
        mnrl, _graded = assemble_data.variant_source(held_out={"held_out_variant"})
        assert mnrl == [{"anchor": "chaand", "positive": "chand", "source": "variant"}]

    def test_no_variants_produces_empty_lists(self, monkeypatch):
        _patch_single_word_vocab(monkeypatch, frozenset({"unseen"}), {})
        mnrl, graded = assemble_data.variant_source(held_out=set())
        assert mnrl == []
        assert graded == []

    def test_uses_alias_score_not_a_lower_score(self, monkeypatch):
        _patch_single_word_vocab(monkeypatch, frozenset({"baarish"}), {"baarish": ["barish"]})
        _mnrl, graded = assemble_data.variant_source(held_out=set())
        assert graded[0]["score"] == assemble_data.ALIAS_SCORE == 0.95

    def test_multiple_variants_for_one_word_all_kept(self, monkeypatch):
        _patch_single_word_vocab(
            monkeypatch, frozenset({"khushbu"}), {"khushbu": ["khushboo", "khushbhu"]}
        )
        mnrl, graded = assemble_data.variant_source(held_out=set())
        assert {r["positive"] for r in mnrl} == {"khushboo", "khushbhu"}
        assert len(graded) == 2

    def test_source_tagged_variant_not_alias(self, monkeypatch):
        _patch_single_word_vocab(monkeypatch, frozenset({"baarish"}), {"baarish": ["barish"]})
        mnrl, graded = assemble_data.variant_source(held_out=set())
        assert mnrl[0]["source"] == "variant"
        assert graded[0]["source"] == "variant"
