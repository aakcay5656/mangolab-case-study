"""The review runs ./test.sh with FX_UPSTREAM_BASE pointing at a closed port.

This is the one test that opens a real socket — to a port on this machine that
nothing is listening on. It is the end-to-end proof that when the upstream is
simply not there, the customer gets a named error and never a number.
"""

import socket

import pytest
from fastapi.testclient import TestClient

from fxtool.main import app

QUERY = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


def closed_port() -> int:
    """A port that was free a microsecond ago and has nothing listening on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def unreachable_upstream(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", f"http://127.0.0.1:{closed_port()}")


def test_a_closed_port_produces_an_error_not_a_zero(unreachable_upstream):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/tools/convert", params=QUERY)

    body = response.json()
    assert response.status_code == 502
    assert body == {
        "error": "upstream_unavailable",
        "message": "The exchange-rate service could not be reached.",
    }
    # The failure mode that matters: no rate, no result, no 200.
    assert "rate" not in body and "result" not in body


def test_health_still_answers_when_the_upstream_is_gone(unreachable_upstream):
    with TestClient(app) as client:
        assert client.get("/health").json() == {"ok": True}


def test_a_bad_request_is_still_refused_locally_when_the_upstream_is_gone(unreachable_upstream):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/tools/convert", params={**QUERY, "amount": "-1"})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_amount"
