from __future__ import annotations

"""
Unit tests for the secret-word schedule module.

Uses in-memory schedule lists and temporary files — no wordfreq, no model.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from config import START_DATE
from schedule import load_schedule, secret_for_date, validate_schedule


class TestSecretForDate:
    """Test schedule cycling and determinism."""

    _SCHEDULE = ["alpha", "bravo", "charlie", "delta"]

    def test_start_date_gives_index_zero(self) -> None:
        result = secret_for_date(START_DATE, "en", self._SCHEDULE)
        assert result == "alpha"

    def test_next_day(self) -> None:
        result = secret_for_date(START_DATE + timedelta(days=1), "en", self._SCHEDULE)
        assert result == "bravo"

    def test_cycles_modularly(self) -> None:
        """After len(schedule) days, the schedule wraps back to the start."""
        n = len(self._SCHEDULE)
        day_n = START_DATE + timedelta(days=n)
        assert secret_for_date(day_n, "en", self._SCHEDULE) == "alpha"

    def test_determinism(self) -> None:
        """Calling twice with same args yields same result."""
        d = START_DATE + timedelta(days=3)
        r1 = secret_for_date(d, "en", self._SCHEDULE)
        r2 = secret_for_date(d, "en", self._SCHEDULE)
        assert r1 == r2

    def test_far_future_date(self) -> None:
        """A date 365 days out produces the expected cyclic index."""
        n = len(self._SCHEDULE)
        days_ahead = 365
        d = START_DATE + timedelta(days=days_ahead)
        expected_idx = days_ahead % n
        assert secret_for_date(d, "en", self._SCHEDULE) == self._SCHEDULE[expected_idx]

    def test_raises_on_empty_schedule(self) -> None:
        with pytest.raises(ValueError, match="Empty schedule"):
            secret_for_date(START_DATE, "en", [])


class TestLoadSchedule:
    """Test schedule file loading with temp files."""

    def test_loads_words(self, tmp_path: Path) -> None:
        fp = tmp_path / "secrets_en.txt"
        fp.write_text("ocean\nmusic\ndoctor\n", encoding="utf-8")
        result = load_schedule("en", path=fp)
        assert result == ["ocean", "music", "doctor"]

    def test_skips_comments(self, tmp_path: Path) -> None:
        fp = tmp_path / "secrets_en.txt"
        fp.write_text("# comment\nocean\n", encoding="utf-8")
        result = load_schedule("en", path=fp)
        assert result == ["ocean"]

    def test_lowercases_words(self, tmp_path: Path) -> None:
        fp = tmp_path / "secrets_en.txt"
        fp.write_text("Ocean\nMUSIC\n", encoding="utf-8")
        result = load_schedule("en", path=fp)
        assert result == ["ocean", "music"]

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        fp = tmp_path / "secrets_en.txt"
        fp.write_text("\nocean\n\nmusic\n\n", encoding="utf-8")
        result = load_schedule("en", path=fp)
        assert result == ["ocean", "music"]


class TestValidateSchedule:
    """Test schedule validation against vocab and profanity."""

    _VOCAB = ["ocean", "music", "doctor", "rain", "family"]

    def test_valid_schedule_passes(self) -> None:
        schedule = ["ocean", "music"]
        result = validate_schedule("en", self._VOCAB, schedule)
        assert result == schedule

    def test_raises_when_secret_not_in_vocab(self) -> None:
        schedule = ["ocean", "unknownword"]
        with pytest.raises(ValueError, match="NOT in en vocab"):
            validate_schedule("en", self._VOCAB, schedule)

    def test_raises_when_secret_is_profane(self) -> None:
        # "ass" is in the actual profanity_en.txt
        vocab_with_profane = [*self._VOCAB, "ass"]
        schedule = ["ocean", "ass"]
        with pytest.raises(ValueError, match="profanity blocklist"):
            validate_schedule("en", vocab_with_profane, schedule)

    def test_pairing_consistency(self) -> None:
        """
        Both English and Hinglish schedules loaded from real files must have
        the same length (translation-paired lines).
        """
        en_schedule = load_schedule("en")
        hien_schedule = load_schedule("hi-en")
        assert len(en_schedule) == len(hien_schedule), (
            f"Schedule length mismatch: en={len(en_schedule)}, hi-en={len(hien_schedule)}"
        )
