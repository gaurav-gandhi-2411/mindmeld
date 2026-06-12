from __future__ import annotations

"""
Unit tests for vocab loading and filtering.

Uses a tiny stub vocab list and hardcoded test data — no wordfreq calls,
no model loading, no network required.
"""

from pathlib import Path

import pytest

from config import EN_VOCAB_MAX
from vocab import _is_valid_en_word, load_en_vocab, parse_hinglish_file


class TestEnglishWordFilter:
    """Test _is_valid_en_word against the documented filter criteria."""

    _NO_PROFANITY: frozenset[str] = frozenset()

    def test_accepts_normal_word(self) -> None:
        assert _is_valid_en_word("ocean", self._NO_PROFANITY) is True

    def test_rejects_too_short(self) -> None:
        assert _is_valid_en_word("ab", self._NO_PROFANITY) is False

    def test_accepts_min_length(self) -> None:
        assert _is_valid_en_word("cat", self._NO_PROFANITY) is True

    def test_rejects_too_long(self) -> None:
        # Length 16 should fail (max 15)
        assert _is_valid_en_word("a" * 16, self._NO_PROFANITY) is False

    def test_accepts_max_length(self) -> None:
        assert _is_valid_en_word("a" * 15, self._NO_PROFANITY) is True

    def test_rejects_digit(self) -> None:
        assert _is_valid_en_word("word1", self._NO_PROFANITY) is False

    def test_rejects_hyphen(self) -> None:
        assert _is_valid_en_word("well-known", self._NO_PROFANITY) is False

    def test_rejects_apostrophe(self) -> None:
        assert _is_valid_en_word("don't", self._NO_PROFANITY) is False

    def test_rejects_space(self) -> None:
        assert _is_valid_en_word("hot dog", self._NO_PROFANITY) is False

    def test_rejects_non_ascii(self) -> None:
        assert _is_valid_en_word("café", self._NO_PROFANITY) is False

    def test_rejects_profane(self) -> None:
        profanity = frozenset(["badword"])
        assert _is_valid_en_word("badword", profanity) is False

    def test_profanity_check_case_insensitive(self) -> None:
        profanity = frozenset(["badword"])
        assert _is_valid_en_word("BADWORD", profanity) is False

    def test_accepts_word_not_in_profanity(self) -> None:
        profanity = frozenset(["badword"])
        assert _is_valid_en_word("goodword", profanity) is True


class TestHinglishParsing:
    """Test parse_hinglish_file with in-memory temp files."""

    def test_parses_basic_entry(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("dost\tfriend\n", encoding="utf-8")
        result = parse_hinglish_file(fp)
        assert result == [("dost", "friend")]

    def test_skips_comment_lines(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("# comment\ndost\tfriend\n", encoding="utf-8")
        result = parse_hinglish_file(fp)
        assert result == [("dost", "friend")]

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("\ndost\tfriend\n\nyaar\tbuddy\n", encoding="utf-8")
        result = parse_hinglish_file(fp)
        assert result == [("dost", "friend"), ("yaar", "buddy")]

    def test_lowercases_entries(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("Dost\tFriend\n", encoding="utf-8")
        result = parse_hinglish_file(fp)
        assert result == [("dost", "friend")]

    def test_raises_on_missing_tab(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("dost friend\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing tab separator"):
            parse_hinglish_file(fp)

    def test_multiple_entries(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("# starter\ndost\tfriend\npyaar\tlove\nroti\tbread\n", encoding="utf-8")
        result = parse_hinglish_file(fp)
        assert len(result) == 3
        assert result[0] == ("dost", "friend")
        assert result[2] == ("roti", "bread")


class TestEnVocabSizeCap:
    """Verify the derived English vocab stays within the spec range of ~40–60k words."""

    def test_derived_vocab_size_within_spec(self) -> None:
        """load_en_vocab() must return between 40,000 and 60,000 words (spec range)."""
        vocab = load_en_vocab()
        assert 40_000 <= len(vocab) <= 60_000, (
            f"English vocab size {len(vocab):,} is outside the spec range 40k–60k"
        )

    def test_derived_vocab_size_at_most_en_vocab_max(self) -> None:
        """load_en_vocab() must never exceed EN_VOCAB_MAX regardless of en.txt content."""
        vocab = load_en_vocab()
        assert len(vocab) <= EN_VOCAB_MAX, (
            f"English vocab size {len(vocab):,} exceeds EN_VOCAB_MAX={EN_VOCAB_MAX:,}"
        )

    def test_load_en_vocab_caps_oversized_cache(self, tmp_path: Path) -> None:
        """A stale en.txt with more than EN_VOCAB_MAX entries must be capped on load."""
        import importlib

        import vocab as vocab_mod

        # Write a synthetic en.txt with EN_VOCAB_MAX + 500 entries
        oversized_lines = ["# header"]
        for i in range(EN_VOCAB_MAX + 500):
            # Generate unique 5-char alpha words (safe for filter)
            word = f"{'abcde'[i % 5]}" + f"word{i:05d}"[:14]
            oversized_lines.append(word)
        cache_path = tmp_path / "en.txt"
        cache_path.write_text("\n".join(oversized_lines) + "\n", encoding="utf-8")

        # Patch VOCAB_DIR temporarily
        original_vocab_dir = vocab_mod.VOCAB_DIR  # type: ignore[attr-defined]
        try:
            # Monkeypatch the module-level import reference used in load_en_vocab
            import config

            config.VOCAB_DIR = tmp_path  # type: ignore[attr-defined]
            importlib.reload(vocab_mod)
            result = vocab_mod.load_en_vocab()
            assert len(result) <= EN_VOCAB_MAX, (
                f"load_en_vocab returned {len(result)} words — cap not enforced"
            )
        finally:
            config.VOCAB_DIR = original_vocab_dir  # type: ignore[attr-defined]
            importlib.reload(vocab_mod)


class TestProfanityExclusion:
    """Test that profanity exclusion works correctly in filtering."""

    def test_en_word_excluded_when_profane(self) -> None:
        profanity = frozenset(["badword", "otherbad"])
        assert _is_valid_en_word("badword", profanity) is False
        assert _is_valid_en_word("goodword", profanity) is True

    def test_empty_profanity_list_accepts_all_valid(self) -> None:
        profanity: frozenset[str] = frozenset()
        assert _is_valid_en_word("ocean", profanity) is True
        assert _is_valid_en_word("music", profanity) is True
