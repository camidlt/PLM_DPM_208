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


def packet(r3, bid="BAT-DOC-001"):
    return {"batteryId": bid, "modules": [{"id": 1, "r_mohm": 1.2}, {"id": 2, "r_mohm": 1.3},
                                          {"id": 3, "r_mohm": r3}, {"id": 4, "r_mohm": 1.1},
                                          {"id": 5, "r_mohm": 1.4}]}


def module(bid, index):
    return next(m for m in repo.get_passport(bid)["modules"] if m["index"] == index)


def test_esp32_payload_drives_health_and_alert(client):
    h = {"X-Device-Id": "esp32-bms-delorean"}
    assert client.post("/api/telemetry", json=packet(1.2), headers=h).json()["ok"]
    assert module("BAT-DOC-001", 3)["health"] == "OK"
    client.post("/api/telemetry", json=packet(1.7), headers=h)
    assert module("BAT-DOC-001", 3)["health"] == "WARNING"
    for _ in range(2):
        client.post("/api/telemetry", json=packet(6.9), headers=h)
    assert module("BAT-DOC-001", 3)["health"] == "WARNING"   # pas encore 3 dépassements
    r = client.post("/api/telemetry", json=packet(7.0), headers=h).json()
    assert r["alerts"] and "Module 3" in r["alerts"][0]
    assert module("BAT-DOC-001", 3)["health"] == "CRITICAL"
    assert any(e["type"] == "BMS_ALERT" for e in repo.get_history("BAT-DOC-001"))
    # pas de nouvelle alerte tant que le module reste critique
    assert client.post("/api/telemetry", json=packet(7.1), headers=h).json()["alerts"] == []
    live = client.get("/api/live").json()
    assert live["online"] and live["device"]["source"] == "ESP32" and live["device"]["packets"] == 6
    pts = next(m for m in live["modules"] if m["index"] == 3)["points"]
    assert [p["r"] for p in pts[-6:]] == [1.2, 1.7, 6.9, 6.9, 7.0, 7.1]


KEY = {"X-BMS-Key": "bms-demo-key"}


def test_legacy_esp32_field_names_and_ohms_law(client):
    # ancien identifiant DLR-1985 du firmware déjà flashé, anciens noms de champs
    r = client.post("/api/telemetry", headers=KEY, json={"battery_id": "dlr-1985", "modules": [
        {"id": 1, "resistance_mohm": 1.25},
        {"id": 2, "v_ocv": 3.7, "v": 3.6832, "i": 12.0}]})
    assert r.status_code == 200
    assert module("BAT-DOC-001", 1)["internalResistance_mOhm"] == 1.25
    assert module("BAT-DOC-001", 2)["internalResistance_mOhm"] == pytest.approx(1.4, abs=0.01)


def test_telemetry_rejects_bad_input(client):
    seeded = repo.count_readings("BAT-DOC-001")
    assert client.post("/api/telemetry", content="pas du json", headers=KEY).status_code == 400
    assert client.post("/api/telemetry", json={"modules": []}, headers=KEY).status_code == 400
    assert client.post("/api/telemetry", json=packet(1.0, bid="INCONNUE"), headers=KEY).status_code == 400
    bad_module = {"batteryId": "BAT-DOC-001", "modules": [{"id": 9, "r_mohm": 1.0}]}
    r = client.post("/api/telemetry", json=bad_module, headers=KEY)
    assert r.status_code == 400 and "inconnu" in r.json()["error"]
    assert client.post("/api/telemetry", json={"batteryId": "BAT-DOC-001", "soh": 140},
                       headers=KEY).status_code == 400
    assert repo.count_readings("BAT-DOC-001") == seeded   # rien n'est écrit pour une trame rejetée


def test_machine_key(client):
    # sans clé ni identifiant d'appareil : refusé ; mauvaise clé : refusée
    assert client.post("/api/telemetry", json=packet(1.2)).status_code == 401
    assert client.post("/api/telemetry", json=packet(1.2), headers={"X-BMS-Key": "faux"}).status_code == 401
    assert client.post("/api/telemetry", json=packet(1.2), headers=KEY).status_code == 200
    # ancien en-tête accepté
    assert client.post("/api/telemetry", json=packet(1.2),
                       headers={"X-Device-Token": "bms-demo-key"}).status_code == 200


def test_batch_soh_soc_and_reading_nodes(client):
    seeded = repo.count_readings("BAT-DOC-001")
    frames = [dict(packet(1.2 + k / 10), soh=70 - k, soc=40 + k, ts=f"2026-11-06T10:00:0{k}")
              for k in range(4)]
    r = client.post("/api/telemetry", json=frames, headers=KEY)
    assert r.status_code == 200 and r.json()["accepted"] == 4
    p = repo.get_passport("BAT-DOC-001")
    assert p["dynamic_performance"]["soh"] == 67 and p["dynamic_performance"]["soc"] == 43
    assert repo.count_readings("BAT-DOC-001") == seeded + 4
    readings = [n for n in repo.nodes.values()
                if n["_label"] == "TelemetryReading" and n["source"] != "BMS (historique)"]
    assert readings[0]["resistances"] == [1.2, 1.3, 1.2, 1.1, 1.4] and readings[0]["soh"] == 70
    # lot partiellement invalide : les trames valides passent, les autres sont listées (207)
    r = client.post("/api/telemetry", json=[packet(1.2), packet(1.2, bid="INCONNUE")], headers=KEY)
    assert r.status_code == 207 and r.json()["accepted"] == 1 and r.json()["errors"][0]["frame"] == 1
    # un lot trop grand est refusé en entier
    assert client.post("/api/telemetry", json=[packet(1.2)] * 201, headers=KEY).status_code == 400


def test_live_payload_feeds_trend_chart(client):
    for r3 in (1.5, 2.5, 3.5):
        client.post("/api/telemetry", json=packet(r3), headers=KEY)
    client.post("/login", data={"username": "garagiste", "password": "garage123"})
    live = client.get("/api/battery/BAT-DOC-001/live").json()
    m3 = next(m for m in live["modules"] if m["index"] == 3)
    assert [p["r"] for p in m3["points"]][-3:] == [1.5, 2.5, 3.5] and m3["rmax"] == 2.0
    assert live["readings"] == len(seed_data.HISTORY_DATES_ACTIVE) + 3
    page = client.get("/garage/b/BAT-DOC-001").text
    assert "data-trend" in page and 'data-alerts="3"' in page


def test_public_pages_and_lookup(client):
    assert client.get("/").status_code == 200
    assert client.get("/lookup?code=dlr-1985").headers["location"].endswith("/b/BAT-DOC-001")
    assert client.get("/b/BAT-DOC-001").headers["location"].endswith("/public/b/BAT-DOC-001")
    page = client.get("/public/b/BAT-DOC-001").text
    assert "Annexe XIII" in page and "6.8" not in page   # pas de données de santé en public
    assert client.get("/qr/BAT-DOC-001.png").headers["content-type"] == "image/png"
    assert client.get("/api/battery/BAT-DOC-001/live").status_code in (302, 303)


BANNED = re.compile("[–—\U0001F300-\U0001FAFF☀-➿⭐⭕]")


def test_no_emoji_or_long_dash_in_pages(client):
    pages = ["/", "/login", "/public/b/BAT-DOC-001"]
    seen = {}
    for user, pwd, urls in [
        ("garagiste", "garage123", ["/garage"] + [f"/garage/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("proprietaire", "owner123", ["/owner"] + [f"/owner/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("centretri", "tri123", ["/tri", "/tri/market"] + [f"/tri/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("transporteur", "trans123", ["/transport", "/messages"]),
    ]:
        client.post("/login", data={"username": user, "password": pwd})
        for u in urls:
            seen[u] = client.get(u).text
    for u in pages:
        seen[u] = client.get(u).text
    for u, html in seen.items():
        bad = BANNED.findall(html)
        assert not bad, f"{u} contient {bad[:5]}"


def test_demo_batteries_have_fake_history(client):
    """Chaque batterie de démo a une courbe ; la dérive du module 3 de Doc va de 1,5 à 6,8 mΩ."""
    client.post("/login", data={"username": "garagiste", "password": "garage123"})
    for b in seed_data.BATTERIES:
        live = client.get(f"/api/battery/{b['id']}/live").json()
        assert all(len(m["points"]) >= 7 for m in live["modules"]), b["id"]
        assert [m["points"][-1]["r"] for m in live["modules"]] == b["modules"], b["id"]
    m3 = next(m for m in client.get("/api/battery/BAT-DOC-001/live").json()["modules"] if m["index"] == 3)
    rs = [p["r"] for p in m3["points"]]
    assert rs[0] == 1.5 and rs[-1] == 6.8 and rs == sorted(rs)
    assert m3["points"][0]["ts"].startswith("2026-06-03")
    # reproductible : mêmes valeurs après réinitialisation
    repo.reset()
    assert [p["r"] for p in next(m for m in repo.get_telemetry("BAT-DOC-001")["modules"]
                                  if m["index"] == 1)["points"]] == \
           [p["r"] for p in next(m for m in client.get("/api/battery/BAT-DOC-001/live").json()["modules"]
                                  if m["index"] == 1)["points"]]
