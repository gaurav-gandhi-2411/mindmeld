from __future__ import annotations

"""
Unit tests for payload quantization round-trip error bound.

The spec requires: dequantize(quantize(x)) ≈ x  with max error < 1e-4.
Step size = 1 / QSIM_SCALE ≈ 3.05e-5, so max error ≈ step/2 ≈ 1.5e-5.
"""

import numpy as np
import pytest

from payload import dequantize, quantize


class TestQuantizeRoundTrip:
    """Verify quantize → dequantize round-trip error stays under 1e-4."""

    def test_exact_zero(self) -> None:
        q = quantize(0.0)
        recovered = dequantize(q)
        assert abs(recovered - 0.0) < 1e-4

    def test_exact_one(self) -> None:
        q = quantize(1.0)
        recovered = dequantize(q)
        assert abs(recovered - 1.0) < 1e-4

    def test_exact_minus_one(self) -> None:
        q = quantize(-1.0)
        recovered = dequantize(q)
        assert abs(recovered - (-1.0)) < 1e-4

    def test_half(self) -> None:
        q = quantize(0.5)
        recovered = dequantize(q)
        assert abs(recovered - 0.5) < 1e-4

    def test_minus_half(self) -> None:
        q = quantize(-0.5)
        recovered = dequantize(q)
        assert abs(recovered - (-0.5)) < 1e-4

    def test_quantize_output_in_uint16_range(self) -> None:
        for v in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            q = quantize(v)
            assert 0 <= q <= 65535, f"quantize({v})={q} out of uint16 range"

    def test_dense_sweep_max_error(self) -> None:
        """
        Sweep 10_000 uniformly-spaced similarity values and confirm
        every round-trip error is strictly below the 1e-4 budget.
        """
        values = np.linspace(-1.0, 1.0, 10_000)
        max_err = 0.0
        for v in values:
            q = quantize(float(v))
            recovered = dequantize(q)
            err = abs(recovered - float(v))
            max_err = max(max_err, err)
        assert max_err < 1e-4, f"Max round-trip error {max_err:.2e} exceeds 1e-4 budget"

    def test_typical_cosine_similarity(self) -> None:
        """A realistic cos similarity near 0.7 (close-to-secret word) round-trips cleanly."""
        original = 0.7423
        q = quantize(original)
        recovered = dequantize(q)
        assert abs(recovered - original) < 1e-4

    @pytest.mark.parametrize(
        "sim",
        [-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0],
    )
    def test_parametrized_values(self, sim: float) -> None:
        q = quantize(sim)
        recovered = dequantize(q)
        assert abs(recovered - sim) < 1e-4
