"""Défi 1 : télémétrie ESP32, page d'accueil et contraintes de rédaction."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import DEVICES, app, repo  # noqa: E402
from bp import seed_data  # noqa: E402


@pytest.fixture
def client():
    repo.reset()
    DEVICES.clear()
    return TestClient(app, follow_redirects=False)


def packet(r3, bid="DLR-1985"):
    return {"batteryId": bid, "modules": [{"id": 1, "r_mohm": 1.2}, {"id": 2, "r_mohm": 1.3},
                                          {"id": 3, "r_mohm": r3}, {"id": 4, "r_mohm": 1.1},
                                          {"id": 5, "r_mohm": 1.4}]}


def module(bid, index):
    return next(m for m in repo.get_passport(bid)["modules"] if m["index"] == index)


def test_esp32_payload_drives_health_and_alert(client):
    h = {"X-Device-Id": "esp32-bms-delorean"}
    assert client.post("/api/telemetry", json=packet(1.2), headers=h).json()["ok"]
    assert module("DLR-1985", 3)["health"] == "OK"
    client.post("/api/telemetry", json=packet(1.7), headers=h)
    assert module("DLR-1985", 3)["health"] == "WARNING"
    for _ in range(2):
        client.post("/api/telemetry", json=packet(6.9), headers=h)
    assert module("DLR-1985", 3)["health"] == "WARNING"   # pas encore 3 dépassements
    r = client.post("/api/telemetry", json=packet(7.0), headers=h).json()
    assert r["alerts"] and "Module 3" in r["alerts"][0]
    assert module("DLR-1985", 3)["health"] == "CRITICAL"
    assert any(e["type"] == "BMS_ALERT" for e in repo.get_history("DLR-1985"))
    # pas de nouvelle alerte tant que le module reste critique
    assert client.post("/api/telemetry", json=packet(7.1), headers=h).json()["alerts"] == []
    live = client.get("/api/live").json()
    assert live["online"] and live["device"]["source"] == "ESP32" and live["device"]["packets"] == 6
    assert len(next(m for m in live["modules"] if m["index"] == 3)["points"]) == 6


def test_legacy_esp32_field_names_and_ohms_law(client):
    r = client.post("/api/telemetry", json={"battery_id": "dlr-1985", "modules": [
        {"id": 1, "resistance_mohm": 1.25},
        {"id": 2, "v_ocv": 3.7, "v": 3.6832, "i": 12.0}]})
    assert r.status_code == 200
    assert module("DLR-1985", 1)["internalResistance_mOhm"] == 1.25
    assert module("DLR-1985", 2)["internalResistance_mOhm"] == pytest.approx(1.4, abs=0.01)


def test_telemetry_rejects_bad_input(client):
    assert client.post("/api/telemetry", content="pas du json").status_code == 400
    assert client.post("/api/telemetry", json={"modules": []}).status_code == 400
    assert client.post("/api/telemetry", json=packet(1.0, bid="INCONNUE")).status_code == 400


def test_public_pages_and_lookup(client):
    assert client.get("/").status_code == 200
    assert client.get("/lookup?code=dlr-1985").headers["location"].endswith("/b/DLR-1985")
    assert client.get("/b/DLR-1985").headers["location"].endswith("/public/b/DLR-1985")
    page = client.get("/public/b/DLR-1985").text
    assert "Annexe XIII" in page and "6.8" not in page   # pas de données de santé en public
    assert client.get("/qr/DLR-1985.png").headers["content-type"] == "image/png"
    assert client.get("/api/battery/DLR-1985/live").status_code in (302, 303)


BANNED = re.compile("[–—\U0001F300-\U0001FAFF☀-➿⭐⭕]")


def test_no_emoji_or_long_dash_in_pages(client):
    pages = ["/", "/login", "/public/b/DLR-1985"]
    seen = {}
    for user, pwd, urls in [
        ("garagiste", "garage123", ["/garage"] + [f"/garage/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("proprietaire", "owner123", ["/owner"] + [f"/owner/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("centretri", "tri123", ["/tri", "/tri/market"] + [f"/tri/b/{b['id']}" for b in seed_data.BATTERIES]),
    ]:
        client.post("/login", data={"username": user, "password": pwd})
        for u in urls:
            seen[u] = client.get(u).text
    for u in pages:
        seen[u] = client.get(u).text
    for u, html in seen.items():
        bad = BANNED.findall(html)
        assert not bad, f"{u} contient {bad[:5]}"
