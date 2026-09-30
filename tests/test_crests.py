"""Crest downloading and caching, with a fake download instead of the network."""

import io

import pandas as pd
import pytest
import requests
from PIL import Image

from app.components import crests


def fake_png(size=500):
    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), (200, 30, 30, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content=b"", status=200):
        self.content = content
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")


@pytest.fixture(autouse=True)
def temporary_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(crests, "CACHE_DIR", tmp_path)
    crests.crest_uris.clear()
    return tmp_path


def test_crest_is_downloaded_once_then_read_from_disk(monkeypatch, temporary_cache):
    calls = []
    monkeypatch.setattr(crests.requests, "get", lambda url, timeout: calls.append(url) or FakeResponse(fake_png()))

    first = crests.crest_bytes(359)
    second = crests.crest_bytes(359)

    assert first == second
    assert len(calls) == 1
    assert (temporary_cache / "359.png").exists()


def test_crest_is_shrunk_for_tables(monkeypatch):
    monkeypatch.setattr(crests.requests, "get", lambda url, timeout: FakeResponse(fake_png(500)))
    image = Image.open(io.BytesIO(crests.crest_bytes(1)))
    assert max(image.size) == crests.CREST_SIZE


def test_missing_crest_gives_none_and_caches_nothing(monkeypatch, temporary_cache):
    monkeypatch.setattr(crests.requests, "get", lambda url, timeout: FakeResponse(status=404))
    assert crests.crest_bytes(999) is None
    assert not list(temporary_cache.iterdir())


def test_network_error_gives_none(monkeypatch):
    def refuse(url, timeout):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(crests.requests, "get", refuse)
    assert crests.crest_bytes(5) is None


def test_with_crests_adds_one_crest_per_club(monkeypatch):
    monkeypatch.setattr(crests, "crest_bytes", lambda team_id: None if team_id == 30 else b"png")
    frame = pd.DataFrame({"club_id": [1, 2, 3], "name": ["Alpha", "Beta", "Gamma"]})

    result = crests.with_crests(frame, {1: 10, 2: 30})

    assert result.loc[0, "crest"].startswith("data:image/png;base64,")
    assert pd.isna(result.loc[1, "crest"])   # no crest available
    assert pd.isna(result.loc[2, "crest"])   # club not in the lookup
