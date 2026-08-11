"""The seconds-per-step reading, including the burst-delivery cases that used to lie."""

from __future__ import annotations

import time

import pytest

from h3lab.comfy.progress import ProgressTracker, labels_for, node_label

# The ids are deliberately not the ones the lab was written against: a subgraph renumbers
# every node, so a tracker that knows names only by id knows nothing after one edit.
PROMPT = {
    "169:1": {"class_type": "UNETLoader", "inputs": {}},
    "169:10": {"class_type": "SamplerCustomAdvanced", "inputs": {}},
    "169:125": {"class_type": "VAEDecode", "inputs": {}},
    "169:122": {"class_type": "SpectrumApplyMiniMaxH3", "inputs": {}},
    "h3:ref_0": {"class_type": "LoadImage", "inputs": {}},
}


def feed(tracker: ProgressTracker, node: str, steps: int, *, gap_s: float = 0.0) -> None:
    for value in range(1, steps + 1):
        tracker.on_progress({"node": node, "value": value, "max": steps})
        if gap_s:
            time.sleep(gap_s)


def test_a_normal_sampler_run_reports_a_believable_rate(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker()

    tracker.on_executing({"node": "10"})
    for value in range(1, 21):
        tracker.on_progress({"node": "10", "value": value, "max": 20})
        clock["t"] += 8.0
    tracker.on_executing({"node": "125"})

    assert tracker.sec_per_it() == pytest.approx(8.0, rel=0.02)
    assert tracker.steps_seen() == 20


def test_a_burst_of_progress_events_is_discarded(monkeypatch):
    """Twenty events in four milliseconds is delivery, not sampling."""
    clock = {"t": 50.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker()

    tracker.on_executing({"node": "10"})
    for value in range(1, 21):
        tracker.on_progress({"node": "10", "value": value, "max": 20})
        clock["t"] += 0.0002
    tracker.on_executing({"node": None})

    # The old collector reported ~0.008 s/it here. Nothing is better than a lie.
    assert tracker.sec_per_it() is None


def test_a_late_first_event_does_not_start_the_clock(monkeypatch):
    """If the first event seen is step 14, the elapsed window is not 14 steps long."""
    clock = {"t": 10.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker()

    tracker.on_progress({"node": "10", "value": 14, "max": 20})
    clock["t"] += 0.01
    tracker.on_progress({"node": "10", "value": 20, "max": 20})
    tracker.on_executing({"node": None})

    assert tracker.sec_per_it() is None


def test_the_slower_reading_wins_on_an_equal_step_count(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker()

    tracker.on_executing({"node": "10"})
    tracker.on_progress({"node": "10", "value": 1, "max": 20})
    clock["t"] += 200.0
    tracker.on_progress({"node": "10", "value": 20, "max": 20})
    tracker.on_executing({"node": "12"})

    first = tracker.sec_per_it()
    assert first == pytest.approx(10.0, rel=0.05)

    # A second, faster window for the same node must not lower the recorded rate.
    tracker.on_executing({"node": "10"})
    clock["t"] += 1.0
    tracker.on_progress({"node": "10", "value": 20, "max": 20})
    tracker.on_executing({"node": None})
    assert tracker.sec_per_it() == pytest.approx(first, rel=0.05)


def test_the_node_with_more_steps_is_preferred(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker()

    tracker.on_executing({"node": "2"})
    tracker.on_progress({"node": "2", "value": 1, "max": 2})
    clock["t"] += 30.0
    tracker.on_progress({"node": "2", "value": 2, "max": 2})

    tracker.on_executing({"node": "10"})
    tracker.on_progress({"node": "10", "value": 1, "max": 20})
    clock["t"] += 100.0
    tracker.on_progress({"node": "10", "value": 20, "max": 20})
    tracker.on_executing({"node": None})

    assert tracker.steps_seen() == 20
    assert tracker.sec_per_it() == pytest.approx(5.0, rel=0.05)


def test_reaching_the_final_step_does_not_end_the_measurement(monkeypatch):
    """A burst reaches max instantly; only leaving the node ends the window."""
    clock = {"t": 0.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker()

    tracker.on_executing({"node": "10"})
    tracker.on_progress({"node": "10", "value": 1, "max": 20})
    clock["t"] += 160.0
    tracker.on_progress({"node": "10", "value": 20, "max": 20})
    clock["t"] += 40.0  # decode still running inside the same node
    tracker.on_executing({"node": None})

    assert tracker.sec_per_it() == pytest.approx(10.0, rel=0.05)


def test_a_snapshot_describes_the_live_state(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker.of(PROMPT)

    tracker.on_executing({"node": "169:10"})
    tracker.on_progress({"node": "169:10", "value": 1, "max": 20})
    clock["t"] += 9.0
    tracker.on_progress({"node": "169:10", "value": 2, "max": 20})

    snapshot = tracker.snapshot()
    assert snapshot["node"] == "169:10"
    assert snapshot["node_label"] == "Sampler"
    assert snapshot["step"] == 2
    assert snapshot["step_total"] == 20
    assert snapshot["sec_per_it"] == pytest.approx(4.5, rel=0.05)


def test_malformed_events_are_ignored():
    tracker = ProgressTracker()
    tracker.on_progress({"node": "10", "value": None, "max": 20})
    tracker.on_progress({"node": "10", "value": 3})
    tracker.on_progress({"node": "10", "value": 1, "max": 0})
    tracker.on_progress({})
    assert tracker.sec_per_it() is None
    assert tracker.snapshot()["node"] is None


def test_plausibility_rules_are_explicit():
    assert ProgressTracker.is_plausible(160.0, 20) is True
    assert ProgressTracker.is_plausible(0.004, 20) is False
    assert ProgressTracker.is_plausible(0.5, 20) is False
    # A short node with few steps is allowed to be fast.
    assert ProgressTracker.is_plausible(0.02, 2) is True
    assert ProgressTracker.is_plausible(1.0, 0) is False


def test_a_progress_label_says_what_the_node_is_not_where_it_sits():
    labels = labels_for(PROMPT)
    assert labels["169:10"] == "Sampler"
    assert labels["169:125"] == "VAE decode"
    assert labels["169:1"] == "Diffusion model"
    # A class nobody wrote a word for still reads better than a number.
    assert labels["169:122"] == "SpectrumApplyMiniMaxH3"
    assert labels["h3:ref_0"] == "Load image"


def test_a_node_the_prompt_never_mentioned_is_named_by_its_id():
    tracker = ProgressTracker.of(PROMPT)
    tracker.on_executing({"node": "4242"})
    assert tracker.snapshot()["node_label"] == "node 4242"
    assert node_label("4242") == "node 4242"
    assert node_label(None) is None


def test_the_sampler_is_preferred_by_what_it_is(monkeypatch):
    """The rate to report is the sampler's, and the sampler is no longer node 10."""
    clock = {"t": 0.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    tracker = ProgressTracker.of(PROMPT)

    # A decode that also reports twenty steps, then the sampler with the same count.
    tracker.on_executing({"node": "169:125"})
    tracker.on_progress({"node": "169:125", "value": 1, "max": 20})
    clock["t"] += 100.0
    tracker.on_progress({"node": "169:125", "value": 20, "max": 20})

    tracker.on_executing({"node": "169:10"})
    tracker.on_progress({"node": "169:10", "value": 1, "max": 20})
    clock["t"] += 160.0
    tracker.on_progress({"node": "169:10", "value": 20, "max": 20})
    tracker.on_executing({"node": None})

    assert tracker.sec_per_it() == pytest.approx(8.0, rel=0.05)


def test_progress_from_a_real_clock_is_measured_not_guessed():
    tracker = ProgressTracker()
    tracker.on_executing({"node": "10"})
    feed(tracker, "10", 3, gap_s=0.06)
    tracker.on_executing({"node": None})
    rate = tracker.sec_per_it()
    assert rate is not None
    assert 0.02 <= rate <= 0.5
