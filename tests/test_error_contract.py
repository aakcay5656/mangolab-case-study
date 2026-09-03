"""The envelope is the contract, so it is tested on its own.

These build a throwaway app rather than the real one: the point is that every
route out of the service — ours, the framework's, and an unforeseen crash —
produces the same two keys.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fxtool.errors import STATUS, install_error_handlers, tool_error


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/raises")
    async def raises(code: str = "no_rate_for_date"):
        raise tool_error(code, "A sentence a person could read.")

    @app.get("/crashes")
    async def crashes():
        raise RuntimeError("upstream password is hunter2")

    @app.get("/typed")
    async def typed(amount: float):
        return {"amount": amount}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("code, status", sorted(STATUS.items()))
def test_every_code_answers_with_its_status_and_nothing_else(client, code, status):
    response = client.get("/raises", params={"code": code})

    assert response.status_code == status
    assert response.json() == {"error": code, "message": "A sentence a person could read."}


def test_an_unlisted_code_cannot_be_raised_by_accident():
    with pytest.raises(KeyError):
        tool_error("oops_typo", "...")


def test_a_crash_becomes_500_and_leaks_nothing(client):
    response = client.get("/crashes")

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text


def test_framework_validation_uses_the_same_envelope(client):
    response = client.get("/typed", params={"amount": "abc"})

    body = response.json()
    assert response.status_code == 422
    assert body["error"] == "invalid_amount"
    assert "'amount'" in body["message"]
    assert set(body) == {"error", "message"}


def test_an_unknown_route_uses_the_same_envelope(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert set(response.json()) == {"error", "message"}
    assert response.json()["error"] == "not_found"
