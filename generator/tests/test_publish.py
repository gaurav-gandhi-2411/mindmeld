from __future__ import annotations

"""
Unit tests for publish.py.

Covers:
  - _commit_message formatting
  - _collect_sync_plan logic
  - _count_changed_files diff detection
  - _apply_sync copy behaviour
  - end-to-end dry-run (no git mutations)
  - end-to-end commit+push path against a local bare remote + clone (no network)

All tests use tmp_path fixtures; no network calls, no real payloads repo touched.
"""

import gzip
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from publish import (  # noqa: I001 — conftest adds generator/ to sys.path
    _apply_sync,
    _collect_sync_plan,
    _commit_message,
    _count_changed_files,
    _git_has_changes,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_gz(path: Path, data: dict) -> None:
    """Write a dict as gzipped JSON to path, creating parent dirs.

    Uses mtime=0 so repeated calls produce byte-for-byte identical output,
    mirroring the determinism guarantee in the real payload writer.
    """
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(json.dumps(data).encode())
    path.write_bytes(buf.getvalue())


def _make_fake_build_output(out_dir: Path, langs: list[str], puzzle_dates: list[date]) -> None:
    """Create a realistic-looking build output directory tree."""
    for lang in langs:
        for d in puzzle_dates:
            _write_gz(out_dir / lang / f"{d.isoformat()}.json.gz", {"date": d.isoformat()})
    manifest = {
        "v": 1,
        "langs": {
            lang: {"days": [{"date": d.isoformat()} for d in puzzle_dates]} for lang in langs
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _init_local_git_remote(tmp_path: Path) -> tuple[Path, Path]:
    """
    Create a bare 'remote' repo and a clone of it.

    Returns (bare_path, clone_path).
    The clone has origin pointing to the bare repo — no network needed.
    """
    bare = tmp_path / "remote.git"
    clone = tmp_path / "payloads-clone"

    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(bare)],
        check=True,
        capture_output=True,
    )

    clone.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(clone)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=str(clone),
        check=True,
        capture_output=True,
    )

    # git needs at least one commit before it can push to a bare repo.
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(clone),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(clone),
        check=True,
        capture_output=True,
    )

    # Write the static files that the payloads repo always has.
    (clone / ".nojekyll").write_text("", encoding="utf-8")
    (clone / "README.md").write_text("# payloads\n", encoding="utf-8")
    (clone / "manifest.json").write_text("{}", encoding="utf-8")
    (clone / "en").mkdir()
    (clone / "hi-en").mkdir()

    subprocess.run(["git", "add", "-A"], cwd=str(clone), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: init"],
        cwd=str(clone),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=str(clone),
        check=True,
        capture_output=True,
    )
    return bare, clone


# ---------------------------------------------------------------------------
# Tests: _commit_message
# ---------------------------------------------------------------------------


class TestCommitMessage:
    """Verify commit message format and [skip ci] tag."""

    def test_single_day(self) -> None:
        msg = _commit_message([date(2026, 6, 12)], ["en"])
        assert msg == "chore: payload drop 2026-06-12..2026-06-12 (en) [skip ci]"

    def test_range(self) -> None:
        dates = [date(2026, 6, 12), date(2026, 6, 13), date(2026, 6, 14)]
        msg = _commit_message(dates, ["en", "hi-en"])
        assert msg == "chore: payload drop 2026-06-12..2026-06-14 (en,hi-en) [skip ci]"

    def test_skip_ci_always_present(self) -> None:
        msg = _commit_message([date(2026, 7, 1), date(2026, 7, 30)], ["en"])
        assert "[skip ci]" in msg

    def test_raises_on_empty_dates(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            _commit_message([], ["en"])

    def test_first_and_last_dates_in_message(self) -> None:
        dates = [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 31)]
        msg = _commit_message(dates, ["en"])
        assert "2026-01-01" in msg
        assert "2026-01-31" in msg

    def test_langs_joined_with_comma(self) -> None:
        msg = _commit_message([date(2026, 6, 12)], ["en", "hi-en"])
        assert "(en,hi-en)" in msg


# ---------------------------------------------------------------------------
# Tests: _collect_sync_plan
# ---------------------------------------------------------------------------


class TestCollectSyncPlan:
    """Verify the file-copy plan is correct without touching the payloads repo."""

    def test_includes_lang_files(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        payloads = tmp_path / "payloads"
        dates = [date(2026, 6, 12), date(2026, 6, 13)]
        _make_fake_build_output(src, ["en"], dates)
        plan = _collect_sync_plan(src, payloads, ["en"])
        dst_names = {dst.name for _, dst in plan}
        assert "2026-06-12.json.gz" in dst_names
        assert "2026-06-13.json.gz" in dst_names

    def test_includes_manifest(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        payloads = tmp_path / "payloads"
        dates = [date(2026, 6, 12)]
        _make_fake_build_output(src, ["en"], dates)
        plan = _collect_sync_plan(src, payloads, ["en"])
        dst_names = {dst.name for _, dst in plan}
        assert "manifest.json" in dst_names

    def test_excludes_readme_and_nojekyll(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        payloads = tmp_path / "payloads"
        dates = [date(2026, 6, 12)]
        _make_fake_build_output(src, ["en"], dates)
        # Simulate these files in src (shouldn't happen but be safe).
        (src / "README.md").write_text("readme", encoding="utf-8")
        (src / ".nojekyll").write_text("", encoding="utf-8")
        plan = _collect_sync_plan(src, payloads, ["en"])
        dst_names = {dst.name for _, dst in plan}
        assert "README.md" not in dst_names
        assert ".nojekyll" not in dst_names

    def test_both_langs(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        payloads = tmp_path / "payloads"
        dates = [date(2026, 6, 12)]
        _make_fake_build_output(src, ["en", "hi-en"], dates)
        plan = _collect_sync_plan(src, payloads, ["en", "hi-en"])
        parents = {dst.parent.name for _, dst in plan if dst.name.endswith(".json.gz")}
        assert "en" in parents
        assert "hi-en" in parents

    def test_missing_lang_dir_skipped_gracefully(self, tmp_path: Path) -> None:
        src = tmp_path / "build"
        payloads = tmp_path / "payloads"
        # Only en dir exists, hi-en does not.
        dates = [date(2026, 6, 12)]
        _make_fake_build_output(src, ["en"], dates)
        plan = _collect_sync_plan(src, payloads, ["en", "hi-en"])
        # Should not raise; hi-en simply not included.
        parents = {dst.parent.name for _, dst in plan if dst.name.endswith(".json.gz")}
        assert "hi-en" not in parents


# ---------------------------------------------------------------------------
# Tests: _count_changed_files
# ---------------------------------------------------------------------------


class TestCountChangedFiles:
    """Verify changed-file detection for dry-run reporting."""

    def test_all_new_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src.mkdir()
        dst_dir.mkdir()
        (src / "a.json.gz").write_bytes(b"data1")
        (src / "b.json.gz").write_bytes(b"data2")
        plan = [
            (src / "a.json.gz", dst_dir / "a.json.gz"),
            (src / "b.json.gz", dst_dir / "b.json.gz"),
        ]
        assert _count_changed_files(plan) == 2

    def test_no_changes(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src.mkdir()
        dst_dir.mkdir()
        (src / "a.json.gz").write_bytes(b"same-content")
        (dst_dir / "a.json.gz").write_bytes(b"same-content")
        plan = [(src / "a.json.gz", dst_dir / "a.json.gz")]
        assert _count_changed_files(plan) == 0

    def test_partial_changes(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src.mkdir()
        dst_dir.mkdir()
        (src / "a.json.gz").write_bytes(b"new-data")
        (dst_dir / "a.json.gz").write_bytes(b"old-data")
        (src / "b.json.gz").write_bytes(b"same")
        (dst_dir / "b.json.gz").write_bytes(b"same")
        plan = [
            (src / "a.json.gz", dst_dir / "a.json.gz"),
            (src / "b.json.gz", dst_dir / "b.json.gz"),
        ]
        assert _count_changed_files(plan) == 1


# ---------------------------------------------------------------------------
# Tests: _apply_sync
# ---------------------------------------------------------------------------


class TestApplySync:
    """Verify file copy behaviour."""

    def test_copies_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst_dir = tmp_path / "dst" / "en"
        src.mkdir()
        (src / "a.json.gz").write_bytes(b"payload-bytes")
        plan = [(src / "a.json.gz", dst_dir / "a.json.gz")]
        _apply_sync(plan)
        assert (dst_dir / "a.json.gz").read_bytes() == b"payload-bytes"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "manifest.json").write_text("{}", encoding="utf-8")
        dst = tmp_path / "dst" / "deeply" / "nested" / "manifest.json"
        _apply_sync([(src / "manifest.json", dst)])
        assert dst.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src.mkdir()
        dst_dir.mkdir()
        (src / "a.json.gz").write_bytes(b"new")
        (dst_dir / "a.json.gz").write_bytes(b"old")
        _apply_sync([(src / "a.json.gz", dst_dir / "a.json.gz")])
        assert (dst_dir / "a.json.gz").read_bytes() == b"new"


# ---------------------------------------------------------------------------
# Tests: dry-run mode (no git mutations)
# ---------------------------------------------------------------------------


class TestDryRunNoSideEffects:
    """
    Verify that --dry-run does not write any files into the payloads repo
    and does not create any git commits.
    """

    def test_dry_run_leaves_payloads_repo_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        --dry-run must not write any files and must leave git status clean.
        We stub out _run_build to avoid a real model load.
        """
        bare, clone = _init_local_git_remote(tmp_path)

        # Record files present before dry-run.
        before = set(clone.rglob("*"))

        # Stub _run_build so it creates fake output without loading models.
        import publish as pub

        def fake_build(days: int, langs: list[str], out_dir: Path, start: date) -> None:
            dates = [start] * days
            from datetime import timedelta

            dates = [start + timedelta(days=i) for i in range(days)]
            _make_fake_build_output(out_dir, langs, dates[:2])  # 2 days is enough

        monkeypatch.setattr(pub, "_run_build", fake_build)

        main(
            argv=[
                "--days",
                "2",
                "--langs",
                "en",
                "--payloads-repo",
                str(clone),
                "--dry-run",
            ]
        )

        # Nothing new should have been written.
        after = set(clone.rglob("*"))
        assert before == after, f"dry-run wrote files: {after - before}"

        # Git tree must still be clean.
        assert not _git_has_changes(clone), "dry-run left git changes in payloads repo"

    def test_dry_run_prints_would_copy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        bare, clone = _init_local_git_remote(tmp_path)

        import publish as pub

        def fake_build(days: int, langs: list[str], out_dir: Path, start: date) -> None:
            from datetime import timedelta

            dates = [start + timedelta(days=i) for i in range(days)]
            _make_fake_build_output(out_dir, langs, dates)

        monkeypatch.setattr(pub, "_run_build", fake_build)

        main(
            argv=[
                "--days",
                "2",
                "--langs",
                "en",
                "--payloads-repo",
                str(clone),
                "--dry-run",
            ]
        )

        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "would copy" in out


# ---------------------------------------------------------------------------
# Tests: commit+push against a local bare remote (no network)
# ---------------------------------------------------------------------------


class TestCommitAndPushLocal:
    """
    End-to-end test using a local bare repo as the 'remote'.
    No network calls; no real payloads repo is touched.
    """

    def test_new_payloads_committed_and_pushed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bare, clone = _init_local_git_remote(tmp_path)

        import publish as pub

        def fake_build(days: int, langs: list[str], out_dir: Path, start: date) -> None:
            from datetime import timedelta

            dates = [start + timedelta(days=i) for i in range(days)]
            _make_fake_build_output(out_dir, langs, dates)

        monkeypatch.setattr(pub, "_run_build", fake_build)

        main(
            argv=[
                "--days",
                "2",
                "--langs",
                "en",
                "--payloads-repo",
                str(clone),
            ]
        )

        # Verify the file was committed to the local clone.
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(clone),
            capture_output=True,
            text=True,
            check=True,
        )
        assert "payload drop" in log.stdout
        assert "[skip ci]" in log.stdout

    def test_no_commit_when_nothing_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the build output is identical to what's already in the repo, skip commit."""
        bare, clone = _init_local_git_remote(tmp_path)

        import publish as pub

        def fake_build(days: int, langs: list[str], out_dir: Path, start: date) -> None:
            from datetime import timedelta

            dates = [start + timedelta(days=i) for i in range(days)]
            _make_fake_build_output(out_dir, langs, dates)

        monkeypatch.setattr(pub, "_run_build", fake_build)

        # First publish — creates the files.
        main(
            argv=[
                "--days",
                "2",
                "--langs",
                "en",
                "--payloads-repo",
                str(clone),
            ]
        )

        log_before = (
            subprocess.run(
                ["git", "log", "--oneline"],
                cwd=str(clone),
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )

        # Second publish with identical content — should NOT add another commit.
        main(
            argv=[
                "--days",
                "2",
                "--langs",
                "en",
                "--payloads-repo",
                str(clone),
            ]
        )

        log_after = (
            subprocess.run(
                ["git", "log", "--oneline"],
                cwd=str(clone),
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )

        assert len(log_before) == len(log_after), (
            "A second commit was created despite no content change"
        )

    def test_readme_and_nojekyll_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """README.md and .nojekyll in the payloads repo must not be deleted."""
        bare, clone = _init_local_git_remote(tmp_path)
        readme_content = (clone / "README.md").read_text(encoding="utf-8")

        import publish as pub

        def fake_build(days: int, langs: list[str], out_dir: Path, start: date) -> None:
            from datetime import timedelta

            dates = [start + timedelta(days=i) for i in range(days)]
            _make_fake_build_output(out_dir, langs, dates)

        monkeypatch.setattr(pub, "_run_build", fake_build)

        main(
            argv=[
                "--days",
                "2",
                "--langs",
                "en",
                "--payloads-repo",
                str(clone),
            ]
        )

        assert (clone / "README.md").exists(), "README.md was deleted by publish"
        assert (clone / "README.md").read_text(encoding="utf-8") == readme_content
        assert (clone / ".nojekyll").exists(), ".nojekyll was deleted by publish"
