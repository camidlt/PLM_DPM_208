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
    "BAT-002": "Reuse",
    "BAT-DOC-001": "Remanufacture",
    "BAT-003": "Repurpose",
    "BAT-004": "Recycle",
}


@pytest.fixture(autouse=True)
def _reset():
    repo.reset()


def _reco(bid):
    p = repo.get_passport(bid)
    return decision.recommend(p, repo.get_history(bid), repo.get_telemetry(bid))


def test_algorithme_5_cas_direct():
    """Vérifie la recommandation directe pour chaque profil de batterie de démo."""
    for bid, expected in EXPECTED.items():
        p = repo.get_passport(bid)
        assert p is not None, f"{bid} introuvable"
        res = _reco(bid)
        reco = res.get("recommended") or res.get("recommendation")
        assert reco == expected, f"Attendu {expected} pour {bid}, obtenu {reco}"
        # Le recyclage est toujours présent et éligible comme solution de repli
        recycle_opt = next(o for o in res["options"] if o["key"] == "Recycle")
        assert recycle_opt["eligible"] is True


def test_regle_securite():
    """Une batterie avec défaut de sécurité (gonflement, surchauffe, accidents) exclut le réemploi."""
    # BAT-004 a 2 accidents : seul Recycle doit être éligible
    p_004 = repo.get_passport("BAT-004")
    res_004 = decision.recommend(p_004, repo.get_history("BAT-004"))
    eligible_004 = [o["key"] for o in res_004["options"] if o["eligible"]]
    assert eligible_004 == ["Recycle"]

    # BAT-002 (normalement Reuse) avec un défaut de sécurité signalé bascule immédiatement en Recycle
    p_002 = repo.get_passport("BAT-002")
    history_fault = [{"type": "FAULT_REPORTED", "details": "Dommage physique / gonflement"}]
    res_fault = decision.recommend(p_002, history_fault)
    eligible_fault = [o["key"] for o in res_fault["options"] if o["eligible"]]
    assert eligible_fault == ["Recycle"]
    assert res_fault["recommended"] == "Recycle"


def test_bascule_marche():
    """Vérifie la bascule de recommandation selon l'état des modules et la dérive BMS."""
    # BAT-DOC-001 avec son module défaillant est en Remanufacture
    p_doc = repo.get_passport("BAT-DOC-001")
    res_doc = decision.recommend(p_doc, repo.get_history("BAT-DOC-001"), repo.get_telemetry("BAT-DOC-001"))
    assert res_doc["recommended"] == "Remanufacture"

    # BAT-002 (SOH 93%) est en Reuse
    p_002 = repo.get_passport("BAT-002")
    res_002 = decision.recommend(p_002)
    assert res_002["recommended"] == "Reuse"

    # Si la télémétrie BMS montre une forte dérive de résistance (+80%), Reuse est exclu
    drift_readings = [
        dict(at="2026-01-01T00:00:00", moduleIndexes=[1], resistances=[1.0]),
        dict(at="2026-06-01T00:00:00", moduleIndexes=[1], resistances=[1.8]),
    ]
    res_drift = decision.recommend(p_002, history=(), readings=drift_readings)
    assert res_drift["recommended"] != "Reuse"
    reuse_opt = next(o for o in res_drift["options"] if o["key"] == "Reuse")
    assert any("Dérive" in c["label"] and not c["ok"] for c in reuse_opt["criteria"])


def test_priorites_du_centre():
    """Vérifie le respect de la hiérarchie européenne des déchets (Reuse > Remanufacture > Repurpose > Recycle)."""
    # 1. Reuse si tous les critères sont au vert
    res_002 = _reco("BAT-002")
    assert res_002["recommended"] == "Reuse"

    # 2. Si Reuse impossible mais modules remplaçables -> Remanufacture
    res_doc = _reco("BAT-DOC-001")
    assert res_doc["recommended"] == "Remanufacture"
    assert not next(o for o in res_doc["options"] if o["key"] == "Reuse")["eligible"]
    assert next(o for o in res_doc["options"] if o["key"] == "Remanufacture")["eligible"]

    # 3. Si Remanufacture non pertinente (pas de module seul défaillant) mais bon SOH LFP -> Repurpose
    res_003 = _reco("BAT-003")
    assert res_003["recommended"] == "Repurpose"
    assert not next(o for o in res_003["options"] if o["key"] == "Reuse")["eligible"]
    assert not next(o for o in res_003["options"] if o["key"] == "Remanufacture")["eligible"]
    assert next(o for o in res_003["options"] if o["key"] == "Repurpose")["eligible"]

    # 4. Repli final : Recycle
    res_004 = _reco("BAT-004")
    assert res_004["recommended"] == "Recycle"


def test_tri_integration_web_et_onglets():
    """Intégration Web centre de tri : consultation, API décision et enregistrement de l'orientation."""
    client = app.test_client()

    # Login centre de tri Recyclo Nanterre
    res_login = client.post("/login", data={"username": "centretri", "password": "tri123"}, follow_redirects=True)
    assert res_login.status_code == 200

    # Consultation de BAT-004 (Waste, réceptionnée à CT-NANTERRE)
    res_b = client.get("/tri/b/BAT-004")
    assert res_b.status_code == 200
    assert b"Recommandation" in res_b.data
    assert b"Recyclage" in res_b.data

    # API JSON décision
    res_api = client.get("/api/battery/BAT-004/decision")
    assert res_api.status_code == 200
    d_json = res_api.json
    assert d_json["recommendation"]["recommended"] == "Recycle"

    # Tentative de choisir une option inéligible (Reuse pour BAT-004) -> refusé
    res_reuse = client.post("/tri/b/BAT-004/orientation", data={"choice": "Reuse"}, follow_redirects=True)
    assert "pas possible" in res_reuse.get_data(as_text=True)

    # Enregistrement de l'orientation conforme (Recycle)
    res_dec = client.post("/tri/b/BAT-004/orientation", data={
        "choice": "Recycle",
        "comment": "Validation test intégration filière hydrométallurgie"
    }, follow_redirects=True)
    assert res_dec.status_code == 200
    assert "Orientation enregistrée" in res_dec.get_data(as_text=True)

    # Vérification que l'orientation et l'événement sont enregistrés dans le repo
    orientation = repo.get_orientation("BAT-004")
    assert orientation is not None
    assert orientation["choice"] == "Recycle"
    assert orientation["recommended"] == "Recycle"

    events = [e for e in repo.get_history("BAT-004") if e["type"] == "ORIENTATION_DECIDED"]
    assert len(events) >= 1
