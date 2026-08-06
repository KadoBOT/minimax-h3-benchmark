import json
from unittest.mock import MagicMock

from bench.comfy import ComfyClient


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
