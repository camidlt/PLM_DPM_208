"""Défi 1 : réception des trames BMS. python -m pytest -q"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402

from app import app, repo  # noqa: E402
from bp import config, telemetry  # noqa: E402

KEY = {"X-BMS-Key": config.BMS_API_KEY}


@pytest.fixture
def client():
    repo.reset()
    app.config["TESTING"] = True
    return app.test_client()


def frame(bid="BAT-002", **kw):
    f = dict(batteryId=bid, soh=91, soc=60,
             modules=[dict(index=i, internalResistance_mOhm=1.1) for i in range(1, 6)])
    f.update(kw)
    return f


def test_cle_bms_obligatoire(client):
    assert client.post("/api/telemetry", json=frame()).status_code == 401
    assert client.post("/api/telemetry", json=frame(), headers={"X-BMS-Key": "faux"}).status_code == 401


def test_trame_met_a_jour_le_passeport(client):
    r = client.post("/api/telemetry", headers=KEY, json=frame(
        measuredAt="2030-01-01T10:00:00",
        modules=[dict(index=2, internalResistance_mOhm=1.4, temperature_C=31.5)]))
    assert r.status_code == 201 and r.json["results"][0]["current"]
    p = repo.get_passport("BAT-002")
    m2 = p["modules"][1]
    assert m2["internalResistance_mOhm"] == 1.4 and m2["measuredAt"] == "2030-01-01T10:00:00"
    assert m2["temperature_C"] == 31.5
    assert p["dynamic_performance"]["soh"] == 91
    assert repo.get_telemetry("BAT-002")[-1]["at"] == "2030-01-01T10:00:00"


def test_depassement_de_seuil_cree_une_alerte(client):
    mods = [dict(index=i, internalResistance_mOhm=1.1) for i in range(1, 6)]
    mods[3]["internalResistance_mOhm"] = 2.7
    r = client.post("/api/telemetry", headers=KEY, json=frame(modules=mods))
    assert r.json["results"][0]["newAlerts"] == [4]
    hist = repo.get_history("BAT-002")
    assert hist[0]["type"] == "BMS_ALERT" and "Module 4" in hist[0]["details"]
    # une deuxième trame hors seuil ne recrée pas d'alerte pour le même module
    r = client.post("/api/telemetry", headers=KEY, json=frame(modules=mods))
    assert r.json["results"][0]["newAlerts"] == []
    # et l'écran garagiste affiche l'alerte (préremplissage du signalement)
    client.post("/login", data={"username": "garagiste", "password": "garage123"})
    page = client.get("/garage/b/BAT-002").get_data(as_text=True)
    assert "Module 4 : 2.7 mΩ" in page and "Alerte BMS" in page


def test_trame_ancienne_archivee_sans_ecraser(client):
    r = client.post("/api/telemetry", headers=KEY, json=frame(
        measuredAt="2020-01-01T00:00:00",
        modules=[dict(index=1, internalResistance_mOhm=9.9)]))
    assert r.status_code == 201 and not r.json["results"][0]["current"]
    assert repo.get_passport("BAT-002")["modules"][0]["internalResistance_mOhm"] == 1.1
    assert repo.get_telemetry("BAT-002")[0]["at"] == "2020-01-01T00:00:00"


@pytest.mark.parametrize("bad, msg", [
    (dict(batteryId=""), "manquant"),
    (dict(batteryId="INCONNUE"), "introuvable"),
    (dict(modules=[dict(index=9, internalResistance_mOhm=1)]), "inconnu"),
    (dict(modules=[dict(index=1, internalResistance_mOhm="x")]), "nombre"),
    (dict(modules=[dict(index=1, internalResistance_mOhm=1)] * 2), "deux fois"),
    (dict(soh=140), "hors plage"),
    (dict(measuredAt="hier"), "ISO"),
    (dict(modules=[], soh=None, soc=None), "vide"),
])
def test_trames_invalides(client, bad, msg):
    r = client.post("/api/telemetry", headers=KEY, json=frame(**bad))
    assert r.status_code == 400 and msg in r.json["errors"][0]["error"]


def test_lot_de_trames_partiellement_valide(client):
    r = client.post("/api/telemetry", headers=KEY, json=[frame(), frame(bid="NOPE")])
    assert r.status_code == 207 and r.json["accepted"] == 1 and len(r.json["errors"]) == 1


def test_etat_courant_pour_la_passerelle(client):
    assert client.get("/api/telemetry/BAT-DOC-001/latest").status_code == 401
    d = client.get("/api/telemetry/bat-doc-001/latest", headers=KEY).json
    assert d["moduleIndexes"] == [1, 2, 3, 4, 5] and d["resistances"][2] == 6.8


def test_api_historique_et_courbe(client):
    client.post("/login", data={"username": "garagiste", "password": "garage123"})
    readings = client.get("/api/battery/BAT-DOC-001/telemetry").json["readings"]
    assert len(readings) == 6 and readings[0]["at"] < readings[-1]["at"]
    chart = telemetry.resistance_chart(readings, repo.get_passport("BAT-DOC-001")["modules"])
    hot = [line["index"] for line in chart["lines"] if line["hot"]]
    assert hot == [3] and chart["threshold"] == 2.0
    labels = sorted(line["label_y"] for line in chart["lines"])
    assert all(b - a >= 11 for a, b in zip(labels, labels[1:]))


def test_esp32_trame_et_calcul_ohms_law(client):
    h = {"X-Device-Id": "esp32-bms-delorean"}
    payload = {
        "battery_id": "dlr-1985",
        "modules": [
            {"id": 1, "r_mohm": 1.25, "t": 25.0},
            {"id": 2, "v_ocv": 3.7, "v": 3.6832, "i": 12.0},
            {"id": 3, "r_mohm": 1.1},
            {"id": 4, "r_mohm": 1.2},
            {"id": 5, "r_mohm": 1.3},
        ]
    }
    r = client.post("/api/telemetry", json=payload, headers=h)
    assert r.status_code == 201
    p = repo.get_passport("BAT-DOC-001")
    assert p["modules"][0]["internalResistance_mOhm"] == 1.25
    assert p["modules"][1]["internalResistance_mOhm"] == pytest.approx(1.4, abs=0.01)


def test_alias_dlr_1985_scan_et_redirection(client):
    client.post("/login", data={"username": "garagiste", "password": "garage123"})
    r = client.get("/b/DLR-1985")
    assert r.status_code == 302 and "BAT-DOC-001" in r.headers["Location"]
    r2 = client.get("/scan?code=DLR-1985")
    assert r2.status_code == 302 and "BAT-DOC-001" in r2.headers["Location"]
