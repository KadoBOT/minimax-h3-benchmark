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
