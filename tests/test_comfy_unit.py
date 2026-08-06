import json
import time
from unittest.mock import MagicMock

from bench.comfy import ComfyClient, ProgressCollector


def test_queue_prompt(monkeypatch):
    client = ComfyClient("http://example:8188")

    def fake_urlopen(req, timeout=None):
        m = MagicMock()
        m.read.return_value = json.dumps({"prompt_id": "abc"}).encode()
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert client.queue_prompt({"1": {}}) == "abc"


def test_was_node_cached():
    hist = {
        "status": {
            "messages": [
                ["execution_start", {}],
                ["execution_cached", {"nodes": ["1", "10", "91"]}],
                ["execution_success", {}],
            ]
        }
    }
    assert ComfyClient.was_node_cached(hist, 10) is True
    assert ComfyClient.was_node_cached(hist, "15") is False


def test_cancel_all_posts_interrupt_and_clear(monkeypatch):
    client = ComfyClient("http://example:8188")
    calls = []

    def fake_request(method, path, data=None, timeout=None):
        calls.append((method, path, data))
        return None

    monkeypatch.setattr(client, "_request", fake_request)
    client.cancel_all()
    paths = [c[1] for c in calls]
    assert "/interrupt" in paths
    assert "/queue" in paths


def test_progress_collector_sec_per_it_uses_node_wall_clock(monkeypatch):
    """s/it = sampler wall time / steps, not WS message inter-arrival."""
    c = ProgressCollector()
    t = [1000.0]

    def fake_perf():
        return t[0]

    monkeypatch.setattr(time, "perf_counter", fake_perf)

    # Enter sampler
    c.on_executing({"node": "10", "prompt_id": "p1"})
    # 20 steps over 100s wall clock → 5.0 s/it
    for step in range(1, 21):
        t[0] = 1000.0 + step * 5.0
        c.on_progress({"value": step, "max": 20, "node": "10", "prompt_id": "p1"})
    # Leave sampler for VAE
    t[0] = 1000.0 + 100.0
    c.on_executing({"node": "125", "prompt_id": "p1"})

    spi = c.sec_per_it("p1")
    assert spi is not None
    assert abs(spi - 5.0) < 0.05


def test_progress_collector_ignores_burst_message_deltas(monkeypatch):
    """Burst-received progress messages must not yield ~0.01 s/it."""
    c = ProgressCollector()
    t = [1000.0]
    monkeypatch.setattr(time, "perf_counter", lambda: t[0])

    c.on_executing({"node": "10"})
    # Simulate wall clock advancing correctly even if we only "process" at end
    for step in range(1, 21):
        t[0] = 1000.0 + step * 5.0
        c.on_progress({"value": step, "max": 20, "node": "10"})
    t[0] = 1100.0
    c.on_executing({"node": None})

    spi = c.sec_per_it()
    assert spi is not None
    assert spi > 1.0  # not 0.01
