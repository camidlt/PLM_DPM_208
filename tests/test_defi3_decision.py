"""Défi 3 : aide à la décision de fin de vie. python -m pytest -q"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402

from app import app, repo  # noqa: E402
from bp import decision  # noqa: E402


@pytest.fixture
def client():
    repo.reset()
    app.config["TESTING"] = True
    return app.test_client()


def login(c, username, password):
    c.get("/logout")
    c.post("/login", data={"username": username, "password": password})


def reco(bid):
    return decision.recommend(repo.get_passport(bid), repo.get_history(bid), repo.get_telemetry(bid))


@pytest.mark.parametrize("bid, expected", [
    ("BAT-002", "Reuse"),            # SOH 93 %, aucun défaut
    ("BAT-DOC-001", "Remanufacture"),  # SOH 71 %, 1 module sur 5 hors seuil
    ("BAT-003", "Repurpose"),        # SOH 64 %, LFP, modules dans les tolérances
    ("BAT-004", "Recycle"),          # SOH 48 %, 2 accidents
])
def test_recommandations_des_batteries_de_demo(client, bid, expected):
    r = reco(bid)
    assert r["recommended"] == expected
    assert r["options"][-1]["key"] == "Recycle" and r["options"][-1]["eligible"]


def test_defaut_de_securite_force_le_recyclage(client):
    login(client, "garagiste", "garage123")
    client.post("/garage/b/BAT-002/report", data={"fault_type": "Dommage physique / gonflement",
                                                   "comment": "pack gonflé", "destination": "CT-NANTERRE"})
    assert reco("BAT-002")["recommended"] == "Recycle"


def test_derive_bms_exclut_le_reemploi(client):
    p = repo.get_passport("BAT-002")
    readings = [dict(at="1", moduleIndexes=[1], resistances=[1.0]),
                dict(at="2", moduleIndexes=[1], resistances=[1.8])]
    r = decision.recommend(p, [], readings)
    assert r["recommended"] != "Reuse"
    assert any("Dérive" in c["label"] and not c["ok"] for c in r["options"][0]["criteria"])


def test_ecran_centre_de_tri_et_api(client):
    login(client, "centretri", "tri123")
    page = client.get("/tri/b/BAT-004").get_data(as_text=True)
    assert "Recommandation" in page and "Recyclage" in page and "Enregistrer l'orientation" in page
    # une batterie non réceptionnée par ce centre : pas de formulaire
    page = client.get("/tri/b/BAT-DOC-001").get_data(as_text=True)
    assert "Remanufacturing" in page and "Enregistrer l'orientation" not in page
    d = client.get("/api/battery/BAT-003/decision").json
    assert d["recommendation"]["recommended"] == "Repurpose" and d["orientation"] is None


def test_enregistrement_de_l_orientation(client):
    login(client, "centretri", "tri123")
    url = "/tri/b/BAT-004/orientation"
    r = client.post(url, data={"choice": "Reuse"}, follow_redirects=True)
    assert "pas possible" in r.get_data(as_text=True)
    r = client.post(url, data={"choice": "Recycle", "comment": "Filière hydrométallurgie"},
                    follow_redirects=True)
    assert "Orientation enregistrée" in r.get_data(as_text=True)
    o = repo.get_orientation("BAT-004")
    assert o["choice"] == "Recycle" and o["recommended"] == "Recycle"
    assert repo.get_history("BAT-004")[0]["type"] == "ORIENTATION_DECIDED"
    r = client.post(url, data={"choice": "Recycle"}, follow_redirects=True)
    assert "déjà été enregistrée" in r.get_data(as_text=True)


def test_orientation_apres_parcours_complet(client):
    """Tronc commun puis défi 3 : Doc → Waste → reçue à Nanterre → remanufacturing."""
    login(client, "garagiste", "garage123")
    client.post("/garage/b/BAT-DOC-001/report",
                data={"fault_type": "Résistance interne anormale d'un module", "comment": "",
                    "destination": "CT-NANTERRE"})
    login(client, "proprietaire", "owner123")
    page = client.get("/owner").get_data(as_text=True)
    notif = re.search(r"/owner/requests/(NOTIF-[0-9A-F]+)/approve", page).group(1)
    client.post(f"/owner/requests/{notif}/approve")

    login(client, "centretri2", "tri123")   # pas le bon centre
    r = client.post("/tri/b/BAT-DOC-001/orientation", data={"choice": "Remanufacture"},
                    follow_redirects=True)
    assert "pas été réceptionnée" in r.get_data(as_text=True)

    login(client, "centretri", "tri123")
    r = client.post("/tri/b/BAT-DOC-001/orientation", data={"choice": "Remanufacture"},
                    follow_redirects=True)
    assert "pas été réceptionnée" in r.get_data(as_text=True)   # pas encore reçue
    # défi 2 : affectation du transporteur, enlèvement sous scellé, puis réception
    order = repo.get_passport("BAT-DOC-001")["transfer"]["uid"]
    login(client, "proprietaire", "owner123")
    client.post(f"/transfers/{order}/schedule", data={"carrier": "TR-TRANSBAT",
                                                      "pickup_date": date.today().isoformat()})
    login(client, "transporteur", "trans123")
    client.post(f"/transfers/{order}/pickup", data={
        "seal": "SC-104522", "weight": "522", "handed_over_by": "M. Brown",
        **{f"check_{k}": "1" for k in ("packaging", "terminals", "labels", "documents")}})
    login(client, "centretri", "tri123")
    client.post("/tri/b/BAT-DOC-001/receive", data={"seal": "SC-104522", "weight": "521",
                                                    "check_seal": "1", "check_packaging": "1"})
    # s'écarter de la recommandation exige une justification
    r = client.post("/tri/b/BAT-DOC-001/orientation", data={"choice": "Recycle"}, follow_redirects=True)
    assert "justification est obligatoire" in r.get_data(as_text=True)
    r = client.post("/tri/b/BAT-DOC-001/orientation", data={"choice": "Remanufacture"},
                    follow_redirects=True)
    assert "Orientation enregistrée" in r.get_data(as_text=True)
    assert repo.get_orientation("BAT-DOC-001")["choice"] == "Remanufacture"
