from __future__ import annotations

"""
Unit tests for evals.finetune.probe_workstream_e_efficiency's pure helpers
(spec-model-excellence.md WORKSTREAM E, item 15: efficiency assessment).

No model loading, no network calls -- these are the size/hash/ranking-
resolution helpers that don't require a SentenceTransformer or torch model
object. The heavier integration paths (evaluate_embedding_vector_
quantization, evaluate_weight_quantization, train_distillation_candidate)
are exercised by this workstream's own probe run, not re-run here (mirrors
this repo's convention for probe_lever_*.py / probe_l2_collision_scan_
extension.py -- test the pure logic, not the multi-minute model pipeline).
"""

import hashlib

import numpy as np
import pytest

from evals.finetune.probe_workstream_e_efficiency import (
    _make_hamming_sim_fn,
    _make_int8_dot_sim_fn,
    _sha256,
    gate_vs_shipped,
    model_dir_size_bytes,
    resolve_dim1_custom,
    resolve_dim2_custom,
    verify_protected_files_untouched,
)


class TestSha256:
    def test_matches_hashlib_reference(self, tmp_path) -> None:
        f = tmp_path / "sample.bin"
        f.write_bytes(b"hello world" * 1000)
        expected = hashlib.sha256(b"hello world" * 1000).hexdigest()
        assert _sha256(f) == expected

    def test_different_content_gives_different_hash(self, tmp_path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"aaaa")
        f2.write_bytes(b"bbbb")
        assert _sha256(f1) != _sha256(f2)


class TestModelDirSizeBytes:
    def test_sums_all_files_and_finds_largest(self, tmp_path) -> None:
        (tmp_path / "small.json").write_bytes(b"x" * 10)
        (tmp_path / "big.safetensors").write_bytes(b"y" * 1000)
        sub = tmp_path / "1_Pooling"
        sub.mkdir()
        (sub / "config.json").write_bytes(b"z" * 5)

        result = model_dir_size_bytes(tmp_path)
        assert result["total_bytes"] == 10 + 1000 + 5
        assert result["n_files"] == 3
        assert result["largest_file"] == "big.safetensors"
        assert result["largest_file_bytes"] == 1000


class TestVerifyProtectedFilesUntouched:
    def test_all_match_when_hashes_agree(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "protected.bin"
        f.write_bytes(b"shipped model weights")
        expected_hash = hashlib.sha256(b"shipped model weights").hexdigest()
        monkeypatch.setattr(
            "evals.finetune.probe_workstream_e_efficiency._BASELINE_HASHES",
            {str(f): expected_hash},
        )
        result = verify_protected_files_untouched()
        assert result["all_untouched"] is True
        assert result["files"][str(f)]["match"] is True

    def test_mismatch_detected_if_file_mutated(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "protected.bin"
        f.write_bytes(b"shipped model weights")
        stale_hash = hashlib.sha256(b"a DIFFERENT payload").hexdigest()
        monkeypatch.setattr(
            "evals.finetune.probe_workstream_e_efficiency._BASELINE_HASHES",
            {str(f): stale_hash},
        )
        result = verify_protected_files_untouched()
        assert result["all_untouched"] is False
        assert result["files"][str(f)]["match"] is False

    def test_missing_file_reported_not_raised(self, tmp_path, monkeypatch) -> None:
        missing = tmp_path / "does_not_exist.bin"
        monkeypatch.setattr(
            "evals.finetune.probe_workstream_e_efficiency._BASELINE_HASHES",
            {str(missing): "deadbeef"},
        )
        result = verify_protected_files_untouched()
        assert result["all_untouched"] is False
        assert result["files"][str(missing)]["actual"] is None


# A 4-word toy vocab, arranged so "a" and "b" are close, "c" and "d" are far,
# for exercising resolve_dim1_custom/resolve_dim2_custom with a hand-built
# similarity function (no model, no embedding call).
_TOY_VOCAB = ["a", "b", "c", "d"]
_TOY_IDX = {w: i for i, w in enumerate(_TOY_VOCAB)}


def _toy_sim_fn(idx: int) -> np.ndarray:
    """Fixed similarity table: word 0 ("a") ranks itself first, "b" second,
    "c" third, "d" last -- independent of which word is queried, just to
    give resolve_dim1_custom/resolve_dim2_custom a fully deterministic
    ranking to check against."""
    table = {
        0: np.array([4.0, 3.0, 2.0, 1.0]),
        1: np.array([3.0, 4.0, 2.0, 1.0]),
    }
    return table[idx]


class TestResolveDim1Custom:
    def test_rank_and_band_computed_from_custom_similarity(self) -> None:
        raw_scenarios = [
            {"secret": "a", "word": "b", "tier": "near", "expected_bands": [0, 1, 2]},
            {"secret": "a", "word": "d", "tier": "far", "expected_bands": [4, 5]},
        ]
        resolved = resolve_dim1_custom(raw_scenarios, _TOY_VOCAB, _TOY_IDX, _toy_sim_fn)
        by_word = {r["word"]: r for r in resolved}
        # "b" has the 2nd-highest similarity to "a" (table[0] = [4,3,2,1]) -> rank 2.
        assert by_word["b"]["actual_rank"] == 2
        assert by_word["b"]["resolution_error"] is None
        # "d" has the lowest similarity -> rank 4 (last of 4 words).
        assert by_word["d"]["actual_rank"] == 4

    def test_missing_secret_or_word_reports_resolution_error(self) -> None:
        raw_scenarios = [
            {"secret": "not-in-vocab", "word": "b", "tier": "near", "expected_bands": [0, 1]},
        ]
        resolved = resolve_dim1_custom(raw_scenarios, _TOY_VOCAB, _TOY_IDX, _toy_sim_fn)
        assert resolved[0]["actual_rank"] is None
        assert resolved[0]["resolution_error"] is not None


class TestResolveDim2Custom:
    def test_pass_rate_and_ranks(self) -> None:
        result = resolve_dim2_custom([("b", "a")], _TOY_VOCAB, _TOY_IDX, _toy_sim_fn)
        assert result["n_pairs"] == 1
        assert result["n_resolved"] == 1
        rec = result["records"][0]
        assert rec["rank"] == 2  # "b" is 2nd-most-similar to "a"
        assert rec["resolution_error"] is None

    def test_missing_word_recorded_as_resolution_error_not_dropped(self) -> None:
        result = resolve_dim2_custom(
            [("ghost", "a")], _TOY_VOCAB, _TOY_IDX, _toy_sim_fn
        )
        assert result["n_resolved"] == 0
        assert result["records"][0]["resolution_error"] is not None
        assert result["pass_rate_scorching_or_hot"] is None


class TestSimFactories:
    def test_int8_dot_sim_ranks_identical_vector_highest(self) -> None:
        matrix = np.array(
            [[100, 100], [100, 90], [-100, -100]],
            dtype=np.int8,
        )
        sim_fn = _make_int8_dot_sim_fn(matrix)
        sims = sim_fn(0)
        # Row 0 dotted with itself must be the largest value (self-similarity
        # is maximal), and the antipodal row 2 must be the smallest/most negative.
        assert sims[0] == sims.max()
        assert sims[2] == sims.min()

    def test_hamming_sim_ranks_identical_bits_highest(self) -> None:
        # 3 rows of 1 packed byte each: row0 and row1 differ in 1 bit, row2
        # is the bitwise complement of row0 (maximal Hamming distance).
        matrix = np.array([[0b00000000], [0b00000001], [0b11111111]], dtype=np.uint8)
        sim_fn = _make_hamming_sim_fn(matrix)
        sims = sim_fn(0)
        assert sims[0] == 0  # zero distance to itself -> similarity 0 (the max)
        assert sims[1] == -1  # 1 bit different -> distance 1 -> similarity -1
        assert sims[2] == -8  # fully complementary -> distance 8 -> similarity -8
        assert sims[0] > sims[1] > sims[2]


class TestGateVsShipped:
    """gate_vs_shipped composes bootstrap_ci.py + regression.py (already unit-
    tested elsewhere) -- this exercises the composition/verdict logic only,
    with a tiny synthetic record set (n_boot defaults are large but fast at
    this size)."""

    def _dim1_records(self, in_expected_band: bool) -> list[dict]:
        return [
            {
                "secret": "s1",
                "word": "w1",
                "tier": "near",
                "actual_rank": 1,
                "in_expected_band": in_expected_band,
            },
            {
                "secret": "s2",
                "word": "w2",
                "tier": "far",
                "actual_rank": 5000,
                "in_expected_band": in_expected_band,
            },
        ]

    def _dim2_records(self, consistent: bool) -> list[dict]:
        return [
            {
                "en_secret": "e1",
                "hien_secret": "h1",
                "consistent": consistent,
                "resolution_error": None,
            }
        ]

    def test_identical_records_pass_gate(self) -> None:
        dim1 = self._dim1_records(True)
        dim2 = self._dim2_records(True)
        result = gate_vs_shipped(dim1, dim2, dim1, dim2)
        assert result["gate_verdict"] == "PASS"
        assert result["dim1_regression_floor"]["n_broken"] == 0
        assert result["dim2_regression_floor"]["n_broken"] == 0

    def test_candidate_breaking_a_working_pair_fails_gate(self) -> None:
        shipped_dim1 = self._dim1_records(True)
        cand_dim1 = self._dim1_records(False)
        shipped_dim2 = self._dim2_records(True)
        cand_dim2 = self._dim2_records(True)
        result = gate_vs_shipped(shipped_dim1, shipped_dim2, cand_dim1, cand_dim2)
        assert result["dim1_regression_floor"]["n_broken"] == 2
        assert result["gate_verdict"] == "FAIL"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
