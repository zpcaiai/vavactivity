from __future__ import annotations

import importlib.util
import json
from pathlib import Path

script_path = (
    Path(__file__).resolve().parents[4] / "scripts" / "observability" / "observe_release.py"
)
spec = importlib.util.spec_from_file_location("observe_release", script_path)
assert spec is not None and spec.loader is not None
observe_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observe_release)


def write_samples(state, samples):
    state.write_text(
        "".join(json.dumps(sample) + "\n" for sample in samples),
        encoding="utf-8",
    )


def sample(at, *, status="PASS", commit="commit-a", clean=True):
    return {
        "epoch_seconds": at,
        "status": status,
        "git_commit": commit,
        "worktree_clean": clean,
    }


def test_empty_history_stays_in_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(observe_release.time, "time", lambda: 1_000_000.0)

    report = observe_release.evaluate(tmp_path / "missing.jsonl", 3600)

    assert report["windows"]["24h"]["status"] == "IN_PROGRESS"
    assert report["windows"]["24h"]["sample_count"] == 0


def test_complete_clean_history_passes_only_elapsed_window(tmp_path, monkeypatch):
    now = 2_000_000.0
    interval = 3600
    monkeypatch.setattr(observe_release.time, "time", lambda: now)
    state = tmp_path / "samples.jsonl"
    write_samples(
        state,
        [
            sample(at)
            for at in range(
                int(now - observe_release.WINDOWS["24h"] - interval),
                int(now) + 1,
                interval,
            )
        ],
    )

    report = observe_release.evaluate(state, interval)

    assert report["windows"]["24h"]["status"] == "PASS"
    assert report["windows"]["24h"]["cadence_complete"] is True
    assert report["windows"]["24h"]["immutable_identity"] is True
    assert report["windows"]["7d"]["status"] == "IN_PROGRESS"
    assert report["windows"]["30d"]["status"] == "IN_PROGRESS"


def test_large_gap_keeps_window_in_progress(tmp_path, monkeypatch):
    now = 3_000_000.0
    interval = 3600
    window = observe_release.WINDOWS["24h"]
    monkeypatch.setattr(observe_release.time, "time", lambda: now)
    state = tmp_path / "samples.jsonl"
    write_samples(
        state,
        [
            sample(now - window - interval),
            sample(now - window + interval),
            sample(now),
        ],
    )

    report = observe_release.evaluate(state, interval)

    assert report["windows"]["24h"]["status"] == "IN_PROGRESS"
    assert report["windows"]["24h"]["cadence_complete"] is False


def test_dirty_or_mixed_commit_history_is_not_immutable(tmp_path, monkeypatch):
    now = 4_000_000.0
    interval = 3600
    window = observe_release.WINDOWS["24h"]
    monkeypatch.setattr(observe_release.time, "time", lambda: now)
    state = tmp_path / "samples.jsonl"
    samples = [sample(at) for at in range(int(now - window - interval), int(now) + 1, interval)]
    samples[-2] = sample(samples[-2]["epoch_seconds"], commit="commit-b")
    samples[-1] = sample(samples[-1]["epoch_seconds"], clean=False)
    write_samples(state, samples)

    report = observe_release.evaluate(state, interval)

    assert report["windows"]["24h"]["status"] == "IN_PROGRESS"
    assert report["windows"]["24h"]["immutable_identity"] is False


def test_failed_sample_fails_active_windows(tmp_path, monkeypatch):
    now = 5_000_000.0
    monkeypatch.setattr(observe_release.time, "time", lambda: now)
    state = tmp_path / "samples.jsonl"
    write_samples(state, [sample(now - 60, status="FAIL")])

    report = observe_release.evaluate(state, 3600)

    assert report["windows"]["24h"]["status"] == "FAIL"
