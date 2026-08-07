import json
from urllib.error import URLError

from bench.constants import FALLBACK_SAMPLERS, FALLBACK_SCHEDULERS
from bench.options import clear_options_cache, fetch_comfy_options


def _object_info_body(node_name: str, field: str, values: list[str]) -> bytes:
    payload = {
        node_name: {
            "input": {
                "required": {
                    field: [values, {}],
                }
            }
        }
    }
    return json.dumps(payload).encode()


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_fallback_on_bad_url(monkeypatch):
    clear_options_cache()

    def boom(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr("bench.options.urllib.request.urlopen", boom)
    data = fetch_comfy_options("http://127.0.0.1:1", timeout=0.1)
    assert data["source"] == "fallback"
    assert data["schedulers"] == list(FALLBACK_SCHEDULERS)
    assert data["samplers"] == list(FALLBACK_SAMPLERS)
    assert data["defaults"]["scheduler"] == "beta57"
    assert data["defaults"]["sampler"] == "euler"
    assert data["defaults"]["seed"] == 42
    assert data["defaults"]["steps"] == 20
    assert data["defaults"]["mp"] == 0.5
    assert data["defaults"]["duration_s"] == 5


def test_fetch_from_object_info(monkeypatch):
    clear_options_cache()
    sched_vals = ["simple", "beta", "karras"]
    samp_vals = ["euler", "dpmpp_2m"]

    def fake_urlopen(url, timeout=None):
        url = str(url)
        if "BasicScheduler" in url:
            return _FakeResp(
                _object_info_body("BasicScheduler", "scheduler", sched_vals)
            )
        if "KSamplerSelect" in url:
            return _FakeResp(
                _object_info_body("KSamplerSelect", "sampler_name", samp_vals)
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("bench.options.urllib.request.urlopen", fake_urlopen)
    data = fetch_comfy_options("http://127.0.0.1:8188")
    assert data["source"] == "comfy"
    assert data["schedulers"] == sched_vals
    assert data["samplers"] == samp_vals
    assert data["defaults"]["seed"] == 42


def test_fetch_caches_for_ttl(monkeypatch):
    clear_options_cache()
    calls = {"n": 0}

    def fake_urlopen(url, timeout=None):
        calls["n"] += 1
        url = str(url)
        if "BasicScheduler" in url:
            return _FakeResp(
                _object_info_body("BasicScheduler", "scheduler", ["a"])
            )
        return _FakeResp(
            _object_info_body("KSamplerSelect", "sampler_name", ["b"])
        )

    monkeypatch.setattr("bench.options.urllib.request.urlopen", fake_urlopen)
    d1 = fetch_comfy_options("http://x")
    d2 = fetch_comfy_options("http://x")
    assert d1 is d2
    assert calls["n"] == 2  # one pair of GETs only


def test_fetch_fallback_on_empty_combo(monkeypatch):
    clear_options_cache()

    def fake_urlopen(url, timeout=None):
        return _FakeResp(
            _object_info_body("BasicScheduler", "scheduler", [])
        )

    monkeypatch.setattr("bench.options.urllib.request.urlopen", fake_urlopen)
    data = fetch_comfy_options("http://x")
    assert data["source"] == "fallback"
