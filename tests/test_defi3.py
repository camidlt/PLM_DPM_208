"""Tests du Défi 3 : Algorithme de décision et intégration web / repo."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest
from app import app, repo
from bp import decision

TODAY = date(2026, 11, 4)
EXPECTED = {
    "BAT-101": "Reuse",
    "BAT-DOC-001": "Remanufacture",
    "BAT-102": "Repurpose",
    "BAT-103": "Recycle",
    "BAT-004": "Recycle"
}


@pytest.fixture(autouse=True)
def _reset():
    repo.reset()


def test_algorithme_5_cas_direct():
    demands = repo.list_demands()
    for bid, expected in EXPECTED.items():
        p = repo.get_passport(bid)
        assert p is not None, f"{bid} introuvable"
        res = decision.recommend(p, demands, today=TODAY)
        assert res["recommendation"] == expected, f"Attendu {expected} pour {bid}, obtenu {res['recommendation']}"


def test_regle_securite():
    demands = repo.list_demands()
    p = repo.get_passport("BAT-103")
    res = decision.recommend(p, demands, today=TODAY)
    feasible = [o["option"] for o in res["options"] if o["feasible"]]
    assert feasible == ["Recycle"]


def test_bascule_marche():
    p = repo.get_passport("BAT-DOC-001")
    demands = repo.list_demands()
    res1 = decision.recommend(p, demands, today=TODAY)
    assert res1["recommendation"] == "Remanufacture"

    demands_vtt = [dict(d, active=(True if d["uid"] == "DEM-VTT" else d["active"])) for d in demands]
    res2 = decision.recommend(p, demands_vtt, today=TODAY)
    assert res2["recommendation"] == "Repurpose"
    assert res2["market_driven"] is True

    res3 = decision.recommend(p, demands_vtt, weights={"marche": 0.0}, today=TODAY)
    assert res3["recommendation"] == "Remanufacture"


def test_priorites_du_centre():
    p = repo.get_passport("BAT-101")
    demands_vtt = [dict(d, active=(True if d["uid"] == "DEM-VTT" else d["active"])) for d in repo.list_demands()]
    # Avec marché actif et VTT, BAT-101 est Repurpose
    assert decision.recommend(p, demands_vtt, today=TODAY)["recommendation"] == "Repurpose"
    # Si le centre ignore le marché, retour à son optimum (Reuse)
    r_no_mkt = decision.recommend(p, demands_vtt, params={"use_market": False}, today=TODAY)
    assert r_no_mkt["recommendation"] == "Reuse" and not r_no_mkt["market_driven"]
    # Si le centre désactive la hiérarchie circulaire
    r_no_hier = decision.recommend(p, demands_vtt, params={"use_hierarchy": False}, today=TODAY)
    assert all(o["hierarchy"] == 0 for o in r_no_hier["options"])


def test_tri_integration_web_et_onglets():
    client = app.test_client()

    # Login centre de tri
    res = client.post("/login", data={"username": "centretri", "password": "tri123"}, follow_redirects=True)
    assert res.status_code == 200

    # Consultation de BAT-101 (Waste, situé à CT-NANTERRE)
    res_b = client.get("/tri/b/BAT-101")
    assert res_b.status_code == 200
    assert b"Aide" in res_b.data or b"Recommandation" in res_b.data
    assert b"Reuse" in res_b.data

    # Toggle marché VTT depuis la page avec redirection
    res_toggle = client.post("/tri/market/DEM-VTT/toggle", data={"back": "/tri/b/BAT-101?tab=marche#decision"}, follow_redirects=True)
    assert res_toggle.status_code == 200
    demands_dict = {d["uid"]: d for d in repo.list_demands()}
    assert demands_dict["DEM-VTT"]["active"] is True

    # Toggle priorité centre de tri
    res_prio = client.post("/tri/priorities", data={"toggle": "use_market", "back": "/tri/b/BAT-101?tab=priorites#decision"}, follow_redirects=True)
    assert res_prio.status_code == 200
    pol = repo.get_center_policy("CT-NANTERRE")
    assert pol["use_market"] is False

    # Enregistrement de la décision pour BAT-101 (Reuse)
    res_dec = client.post("/tri/b/BAT-101/decision", data={
        "chosen": "Reuse",
        "comment": "Validation test intégration"
    }, follow_redirects=True)
    assert res_dec.status_code == 200

    # Vérification que la décision et l'événement sont dans le graphe
    decs = repo.get_decisions("BAT-101")
    assert len(decs) >= 1
    assert decs[0]["chosen"] == "Reuse"

    events = [e for e in repo.get_history("BAT-101") if e["type"] == "DECISION_RECORDED"]
    assert len(events) >= 1

    # Ajout d'une nouvelle demande sur le marché
    res_add = client.post("/tri/market/add", data={
        "title": "Karts électriques pour circuit de loisir",
        "option": "Repurpose",
        "partner": "Karting Circuit SAS",
        "urgency": "urgente",
        "min_soce": "65",
        "quantity": "15",
        "location": "Paris",
        "chemistries": ["NMC 811"],
        "back": "/tri/b/BAT-101?tab=marche#decision"
    }, follow_redirects=True)
    assert res_add.status_code == 200
    demands_after_add = repo.list_demands()
    added = [d for d in demands_after_add if d["title"] == "Karts électriques pour circuit de loisir"]
    assert len(added) == 1
    new_uid = added[0]["uid"]
    assert added[0]["urgency"] == "urgente"

    # Retrait / suppression de cette demande
    res_del = client.post(f"/tri/market/{new_uid}/delete", data={
        "back": "/tri/b/BAT-101?tab=marche#decision"
    }, follow_redirects=True)
    assert res_del.status_code == 200
    demands_after_del = repo.list_demands()
    assert all(d["uid"] != new_uid for d in demands_after_del)
