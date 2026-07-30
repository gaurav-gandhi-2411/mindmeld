from __future__ import annotations

"""
Unit tests for evals.finetune.collision_scan's pure primitives (WORKSTREAM
B, item 8): nearest-neighbor extraction, orthographic-similarity, origin
tagging, and the collision_score aggregation. Tests use small synthetic
matrices/vocabs -- no model loading, no network calls.
"""

import numpy as np

from evals.finetune.collision_scan import (
    analyze_word,
    hien_word_origin,
    hinglish_sourced_words,
    orthographically_similar,
    top_k_neighbors,
)


class TestTopKNeighbors:
    def test_excludes_self_and_orders_by_similarity(self) -> None:
        # 4 unit vectors on a circle in the xy-plane; row 0 is closest to
        # row 1, then row 3 (opposite-ish), then row 2 (near-orthogonal).
        matrix = np.array(
            [
                [1.0, 0.0],
                [0.9, 0.436],  # ~25.8 degrees from row 0 -- closest
                [0.0, 1.0],  # 90 degrees -- farthest
                [0.6, 0.8],  # ~53.1 degrees -- middle
            ],
            dtype=np.float32,
        )
        neighbors = top_k_neighbors(matrix, 0, k=3)
        assert neighbors == [1, 3, 2]
        assert 0 not in neighbors

    def test_k_caps_result_length(self) -> None:
        matrix = np.eye(5, dtype=np.float32)
        neighbors = top_k_neighbors(matrix, 0, k=2)
        assert len(neighbors) == 2


class TestOrthographicallySimilar:
    def test_low_edit_distance_pair_is_similar(self) -> None:
        assert orthographically_similar("seedha", "seed") is True

    def test_shared_prefix_short_words_is_similar(self) -> None:
        assert orthographically_similar("accha", "ac") is True

    def test_shared_interior_run_is_similar(self) -> None:
        assert orthographically_similar("chashma", "champagne") is True

    def test_unrelated_words_not_similar(self) -> None:
        assert orthographically_similar("dost", "elephant") is False

    def test_no_surface_overlap_known_limitation(self) -> None:
        # naukri/norfolk is a real historical collision candidate
        # (probe_subword_collision.py) with zero character-level overlap --
        # documented as an explicit blind spot of this heuristic, not a bug.
        assert orthographically_similar("naukri", "norfolk") is False


class TestHienWordOrigin:
    def test_known_hinglish_word_tagged_hinglish(self) -> None:
        origin = hien_word_origin(["dost", "junoon"])
        assert origin["dost"] == "hinglish"
        assert origin["junoon"] == "hinglish"

    def test_english_only_word_tagged_english(self) -> None:
        hi_words = hinglish_sourced_words()
        assert "elephant" not in hi_words  # sanity: not a curated hinglish word
        origin = hien_word_origin(["elephant"])
        assert origin["elephant"] == "english"


class TestAnalyzeWord:
    def test_collision_score_counts_only_english_and_similar_neighbors(self) -> None:
        # word "seedha" at idx 0; neighbors (in similarity order) are:
        #   idx1 "seed" (english, similar)      -> counts
        #   idx2 "seedi" (hinglish, similar)     -> origin excludes it
        #   idx3 "root" (english, not similar)   -> orthography excludes it
        #   idx4 "seeds" (english, similar)      -> counts
        vocab = ["seedha", "seed", "seedi", "root", "seeds"]
        origin = {"seedha": "hinglish", "seed": "english", "seedi": "hinglish", "root": "english",
                  "seeds": "english"}
        glosses = {"seedha": "straight"}
        # Build a matrix whose row order after argsort(-sims) from row 0 is
        # exactly [1, 2, 3, 4] -- achieved via decreasing similarity to a
        # fixed direction.
        matrix = np.array(
            [
                [1.0, 0.0],
                [0.99, 0.14107],
                [0.95, 0.31225],
                [0.8, 0.6],
                [0.6, 0.8],
            ],
            dtype=np.float32,
        )
        result = analyze_word("seedha", 0, matrix, vocab, origin, glosses, k=4)
        assert result["n_colliding_neighbors"] == 2
        assert result["collision_score"] == 0.5
        assert result["gloss"] == "straight"
        assert [n["word"] for n in result["neighbors"]] == ["seed", "seedi", "root", "seeds"]
