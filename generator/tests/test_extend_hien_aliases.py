from __future__ import annotations

"""
Unit tests for evals/finetune/extend_hien_aliases.py's pure/deterministic
gating + rendering logic (spelling-variance fix, docs/model-excellence-
final-report.md finding #2). No test here depends on the Aksharantar corpus
file or a live model call -- all inputs are small synthetic candidate lists,
matching this repo's existing convention (see test_spelling_robustness.py)
of testing pure logic directly and leaving corpus-scale/model-dependent code
to the real pipeline run.
"""

from evals.finetune.extend_hien_aliases import gate_candidates, render_new_file_text


class TestGateCandidatesFalseMergeRisks:
    """The single biggest risk this module guards against: two genuinely
    different words folding together."""

    def test_vocab_collision_excluded(self):
        # "wordb" is itself a DIFFERENT canonical vocab word -- adding it as
        # a variant of "worda" would corrupt lookups for "wordb".
        result = gate_candidates(
            [("worda", "wordb")],
            vocab_set={"worda", "wordb"},
            existing_alias_map={},
        )
        assert result["n_final_added"] == 0
        assert len(result["excluded"]["vocab_collisions"]) == 1
        assert result["excluded"]["vocab_collisions"][0]["collides_with_vocab_word"] == "wordb"

    def test_existing_alias_collision_excluded(self):
        # "variant" already resolves to a DIFFERENT canonical in the
        # pre-extension file -- adding it for "worda" too would silently
        # corrupt the existing mapping.
        result = gate_candidates(
            [("worda", "variant")],
            vocab_set={"worda", "wordc"},
            existing_alias_map={"variant": "wordc"},
        )
        assert result["n_final_added"] == 0
        assert len(result["excluded"]["existing_alias_collisions"]) == 1
        assert result["excluded"]["existing_alias_collisions"][0]["existing_canonical"] == "wordc"

    def test_internal_batch_conflict_excluded_both_sides(self):
        # Two candidates in the SAME new batch normalize the same "shared"
        # string for two different canonicals -- neither survives, since
        # there's no principled way to pick a winner without risking a
        # false merge for whichever one loses silently.
        result = gate_candidates(
            [("worda", "shared"), ("wordb", "shared")],
            vocab_set={"worda", "wordb"},
            existing_alias_map={},
        )
        assert result["n_final_added"] == 0
        assert len(result["excluded"]["internal_batch_conflicts"]) == 2
        conflict_words = {r["word"] for r in result["excluded"]["internal_batch_conflicts"]}
        assert conflict_words == {"worda", "wordb"}


class TestGateCandidatesHarmlessNoops:
    def test_duplicate_of_existing_alias_excluded_as_noop_not_risk(self):
        result = gate_candidates(
            [("worda", "variant")],
            vocab_set={"worda"},
            existing_alias_map={"variant": "worda"},
        )
        assert result["n_final_added"] == 0
        assert result["excluded_counts"]["vocab_collisions"] == 0
        assert result["excluded_counts"]["existing_alias_collisions"] == 0
        assert result["harmless_noop_counts"]["duplicate_of_existing_alias"] == 1

    def test_redundant_self_resolving_excluded_as_noop(self):
        # normalize("wordaa") == "worda" (aa->a fold) -- this variant
        # already resolves to its own canonical with zero file changes.
        result = gate_candidates(
            [("worda", "wordaa")],
            vocab_set={"worda"},
            existing_alias_map={},
        )
        assert result["n_final_added"] == 0
        assert result["harmless_noop_counts"]["redundant_self_resolving"] == 1

    def test_redundant_duplicate_normalized_form_within_batch(self):
        # Two raw spellings for the SAME canonical that normalize
        # identically ("chhaata" -> chh->ch,aa->a -> "chata"; "chaata" ->
        # aa->a -> "chata") -- only the first (sorted) survives; the second
        # is reported, not silently dropped, and still resolves correctly
        # via its kept sibling.
        result = gate_candidates(
            [("chhata", "chhaata"), ("chhata", "chaata")],
            vocab_set={"chhata"},
            existing_alias_map={},
        )
        assert result["n_final_added"] == 1
        assert (
            result["harmless_noop_counts"]["redundant_duplicate_normalized_form_within_new_batch"]
            == 1
        )


class TestGateCandidatesSurvivor:
    def test_clean_candidate_survives(self):
        # "wordax" has no foldable substring, so it normalizes to itself --
        # a genuine new alias distinct from its own canonical.
        result = gate_candidates(
            [("worda", "wordax")],
            vocab_set={"worda"},
            existing_alias_map={},
        )
        assert result["n_final_added"] == 1
        assert result["final_survivors"][0] == {
            "word": "worda",
            "variant": "wordax",
            "norm_variant": "wordax",
        }

    def test_accounting_totals_match_input_count(self):
        candidates = [
            ("worda", "wordb"),  # vocab collision
            ("worda", "variant"),  # existing alias collision
            ("worda", "shared"),  # internal batch conflict
            ("wordc", "shared"),  # internal batch conflict
            ("worda", "cleanvariant"),  # survives
        ]
        result = gate_candidates(
            candidates,
            vocab_set={"worda", "wordb", "wordc"},
            existing_alias_map={"variant": "wordz"},
        )
        total_excluded = sum(result["excluded_counts"].values()) + sum(
            result["harmless_noop_counts"].values()
        )
        assert result["n_final_added"] + total_excluded == result["n_candidates_generated"]
        assert result["n_final_added"] == 1


class TestRenderNewFileText:
    _FILE = (
        "# header comment\n"
        "# Format: canonical: alias1, alias2, ...\n"
        "\n"
        "# Rain\n"
        "baarish: barish\n"
        "\n"
        "# Moon\n"
        "chaand: chand\n"
    )

    def test_appends_alias_to_existing_canonical_line(self):
        survivors = [{"word": "baarish", "variant": "barrish", "norm_variant": "barish"}]
        new_text = render_new_file_text(self._FILE, survivors)
        assert "baarish: barish, barrish\n" in new_text
        # Untouched line preserved exactly.
        assert "chaand: chand\n" in new_text

    def test_new_canonical_gets_a_new_line_in_new_section(self):
        survivors = [{"word": "naya", "variant": "nayaa", "norm_variant": "naya"}]
        new_text = render_new_file_text(self._FILE, survivors)
        assert "naya: nayaa\n" in new_text
        # Original entries still present, untouched.
        assert "baarish: barish\n" in new_text
        assert "chaand: chand\n" in new_text

    def test_no_survivors_leaves_file_unchanged(self):
        new_text = render_new_file_text(self._FILE, [])
        assert new_text == self._FILE

    def test_multiple_new_canonicals_all_present_and_sorted(self):
        survivors = [
            {"word": "zebra_word", "variant": "zebraa", "norm_variant": "zebra"},
            {"word": "apple_word", "variant": "applee", "norm_variant": "apple"},
        ]
        new_text = render_new_file_text(self._FILE, survivors)
        assert "zebra_word: zebraa\n" in new_text
        assert "apple_word: applee\n" in new_text
        # New canonicals rendered in sorted order.
        assert new_text.index("apple_word:") < new_text.index("zebra_word:")
