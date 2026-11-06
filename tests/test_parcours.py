"""Parcours complet du tronc commun, en mode mémoire : python -m pytest -q"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402
from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import app, repo  # noqa: E402
from bp import seed_data  # noqa: E402


TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def client():
    repo.reset()
    return TestClient(app, follow_redirects=False)


def login(c, username, password):
    c.get("/logout")
    return c.post("/login", data={"username": username, "password": password}, follow_redirects=True)


def test_login_required(client):
    r = client.get("/garage")
    assert r.status_code in (302, 303) and "/login" in r.headers["location"]


def test_bad_password(client):
    r = login(client, "garagiste", "faux")
    assert "incorrect" in r.text


def test_qr_entry_routes_each_role(client):
    login(client, "garagiste", "garage123")
    r = client.get("/b/BAT-DOC-001")
    assert r.headers["location"].endswith("/garage/b/BAT-DOC-001")
    r = client.get("/scan?code=http://192.168.1.20:5000/b/BAT-DOC-001")
    assert r.headers["location"].endswith("/garage/b/BAT-DOC-001")
    login(client, "centretri", "tri123")
    assert client.get("/b/BAT-DOC-001").headers["location"].endswith("/tri/b/BAT-DOC-001")


def test_role_isolation(client):
    login(client, "garagiste", "garage123")
    r = client.get("/owner")
    assert r.status_code in (302, 303) and r.headers["location"].endswith("/garage")


def test_parcours_complet(client):
    # 1. Garagiste : voit l'alerte module 3 et signale hors d'usage
    login(client, "garagiste", "garage123")
    page = client.get("/garage/b/BAT-DOC-001").text
    assert "Module 3 : 6.8 mΩ" in page and "Original" in page
    assert "Centre de tri de destination" in page and "Planifier automatiquement la collecte" in page
    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Résistance interne anormale d'un module", "comment": "HS",
                          "destination": "CT-NANTERRE"})
    assert "Demande envoyée" in r.text
    # pas de double demande
    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Autre", "comment": "", "destination": "CT-NANTERRE"})
    assert "déjà en attente" in r.text

    # 2. Centre de tri AVANT mise à jour : statut non à jour, réception refusée
    login(client, "centretri", "tri123")
    page = client.get("/tri/b/BAT-DOC-001").text
    assert "NON à jour" in page
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True)
    assert "réception refusée" in r.text

    # 3. Propriétaire : notification, refus d'un centre non agréé, puis validation
    login(client, "proprietaire", "owner123")
    assert client.get("/api/notifications/count").json()["pending"] == 1
    page = client.get("/owner").text
    notif_uid = re.search(r"/owner/requests/(NOTIF-[0-9A-F]+)/approve", page).group(1)
    r = client.post(f"/owner/requests/{notif_uid}/approve", follow_redirects=True,
                    data={"destination": "CT-EXPRESS"})
    assert "pas agréé" in r.text
    r = client.post(f"/owner/requests/{notif_uid}/approve", follow_redirects=True,
                    data={"destination": "CT-NANTERRE", "comment": "Enlèvement J+2"})
    assert "Waste" in r.text
    assert repo.get_passport("BAT-DOC-001")["battery"]["status"] == "Waste"
    assert client.get("/api/notifications/count").json()["pending"] == 0
    r = client.post(f"/owner/requests/{notif_uid}/approve", follow_redirects=True,
                    data={"destination": "CT-NANTERRE"})
    assert "déjà été traitée" in r.text

    # 4. Un autre centre de tri ne peut pas réceptionner
    login(client, "centretri2", "tri123")
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True)
    assert "attendue par" in r.text

    # 5. Le centre destinataire ne peut pas réceptionner avant l'enlèvement
    login(client, "centretri", "tri123")
    assert "BAT-DOC-001" in client.get("/tri").text
    page = client.get("/tri/b/BAT-DOC-001").text
    assert "WASTE" in page and "En attente de l'enlèvement" in page
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True)
    assert "pas encore été enlevée" in r.text

    # 6. Propriétaire : affecte un transporteur agréé (les non agréés sont refusés)
    login(client, "proprietaire", "owner123")
    order = repo.get_passport("BAT-DOC-001")["transfer"]["uid"]
    r = client.post(f"/transfers/{order}/schedule", follow_redirects=True,
                    data={"carrier": "TR-RAPIDFRET", "pickup_date": TOMORROW, "slot": "8h-12h"})
    assert "non agréé" in r.text
    r = client.post(f"/transfers/{order}/schedule", follow_redirects=True,
                    data={"carrier": "TR-TRANSBAT", "pickup_date": TOMORROW, "slot": "8h-12h"})
    assert "Transporteur affecté, les acteurs sont notifiés" in r.text
    assert repo.get_transfer(order)["carrierUid"] == "TR-TRANSBAT"

    # 7. Transporteur : scellé, pesée, contrôles ADR
    login(client, "transporteur", "trans123")
    assert "BAT-DOC-001" in client.get("/transport").text
    checks = {f"check_{k}": "1" for k in ("packaging", "terminals", "labels", "documents")}
    r = client.post(f"/transfers/{order}/pickup", follow_redirects=True,
                    data={"seal": "SC-104522", "weight": "522", "handed_over_by": "M. Brown"})
    assert "Contrôles non validés" in r.text
    r = client.post(f"/transfers/{order}/pickup", follow_redirects=True,
                    data={"seal": "SC-104522", "weight": "522", "handed_over_by": "M. Brown", **checks})
    assert "sous votre garde" in r.text
    assert repo.get_passport("BAT-DOC-001")["location"]["uid"] == "TR-TRANSBAT"

    # 8. Centre de tri : mauvais scellé bloqué, puis réception avec preuve de dépôt
    login(client, "centretri", "tri123")
    page = client.get("/tri/b/BAT-DOC-001").text
    assert "Confirmer la réception" in page
    rchecks = {"check_seal": "1", "check_packaging": "1"}
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True,
                    data={"seal": "SC-000000", "weight": "521", **rchecks})
    assert "Scellé non conforme" in r.text
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True,
                    data={"seal": "SC-104522", "weight": "521", **rchecks})
    assert "Réception enregistrée" in r.text and "Preuve de dépôt" in r.text
    p = repo.get_passport("BAT-DOC-001")
    assert p["transfer"]["state"] == "RECEIVED" and p["location"]["uid"] == "CT-NANTERRE"
    assert len(p["transfer"]["receiptCode"]) == 12

    # 9. Historique complet et traçable
    types = [e["type"] for e in repo.get_history("BAT-DOC-001")]
    for t in ("FAULT_REPORTED", "STATUS_CHANGED", "TRANSFER_ORDERED", "TRANSFER_SCHEDULED",
              "PICKED_UP", "RECEIVED"):
        assert t in types


def test_refus_proprietaire(client):
    login(client, "garagiste", "garage123")
    client.post("/garage/b/BAT-002/report",
                data={"fault_type": "Autre", "comment": "test", "destination": "CT-NANTERRE"})
    login(client, "proprietaire", "owner123")
    n = repo.list_notifications("EO-FLUX")[0]
    r = client.post(f"/owner/requests/{n['uid']}/reject", follow_redirects=True, data={"comment": ""})
    assert "obligatoire" in r.text
    client.post(f"/owner/requests/{n['uid']}/reject", data={"comment": "Sous garantie"})
    assert repo.get_passport("BAT-002")["battery"]["status"] == "Original"
    assert repo.get_notification(n["uid"])["state"] == "REJECTED"


def test_waste_battery_cannot_be_reported(client):
    login(client, "garagiste", "garage123")
    r = client.post("/garage/b/BAT-004/report", follow_redirects=True,
                    data={"fault_type": "Autre", "comment": ""})
    assert "interdite" in r.text


def test_all_pages_render(client):
    for user, pwd, urls in [
        ("garagiste", "garage123", ["/garage"] + [f"/garage/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("proprietaire", "owner123", ["/owner"] + [f"/owner/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("centretri", "tri123", ["/tri"] + [f"/tri/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("transporteur", "trans123", ["/transport", "/messages"]),
    ]:
        login(client, user, pwd)
        for u in urls:
            assert client.get(u).status_code == 200, u
        assert client.get("/garage/b/INCONNUE").status_code in (302, 303, 404)
        assert client.get("/api/battery/BAT-DOC-001").json()["module_alerts"]


def test_cypher_export_covers_seed():
    stmts = seed_data.cypher_statements()
    assert sum(s.startswith("MERGE (n:BatteryInstance") for s in stmts) == len(seed_data.BATTERIES)
    assert all(not s.endswith(";") for s in stmts)
