"""Tests de los endpoints de la API (Parte 3), con TestClient en memoria."""

from fastapi.testclient import TestClient

from risk_profiling.api import app

client = TestClient(app)


def test_get_user_risk_ok():
    r = client.get("/users/USR0040/risk")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "USR0040"
    assert body["category"] == "VERY_HIGH"
    assert isinstance(body["top_signals"], list) and body["top_signals"]


def test_get_user_risk_404():
    assert client.get("/users/NOEXISTE/risk").status_code == 404


def test_list_users_por_categoria_ordenado():
    r = client.get("/users", params={"category": "very_high", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert all(u["category"] == "VERY_HIGH" for u in data)
    scores = [u["score"] for u in data]
    assert scores == sorted(scores, reverse=True)  # score descendente


def test_list_users_categoria_invalida():
    assert client.get("/users", params={"category": "BOGUS"}).status_code == 422
