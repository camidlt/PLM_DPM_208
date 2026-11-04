"""Parcours complet du tronc commun, en mode mémoire : python -m pytest -q"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402

from app import app, repo  # noqa: E402
from bp import seed_data  # noqa: E402


@pytest.fixture
def client():
    repo.reset()
    app.config["TESTING"] = True
    return app.test_client()


def login(c, username, password):
    c.get("/logout")
    return c.post("/login", data={"username": username, "password": password}, follow_redirects=True)


def test_login_required(client):
    r = client.get("/garage")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_bad_password(client):
    r = login(client, "garagiste", "faux")
    assert "incorrect" in r.get_data(as_text=True)


def test_qr_entry_routes_each_role(client):
    login(client, "garagiste", "garage123")
    r = client.get("/b/BAT-DOC-001")
    assert r.headers["Location"].endswith("/garage/b/BAT-DOC-001")
    r = client.get("/scan?code=http://192.168.1.20:5000/b/BAT-DOC-001")
    assert r.headers["Location"].endswith("/garage/b/BAT-DOC-001")
    login(client, "centretri", "tri123")
    assert client.get("/b/BAT-DOC-001").headers["Location"].endswith("/tri/b/BAT-DOC-001")


def test_role_isolation(client):
    login(client, "garagiste", "garage123")
    r = client.get("/owner")
    assert r.status_code == 302 and r.headers["Location"].endswith("/garage")


def test_parcours_complet(client):
    # 1. Garagiste : voit l'alerte module 3 et signale hors d'usage
    login(client, "garagiste", "garage123")
    page = client.get("/garage/b/BAT-DOC-001").get_data(as_text=True)
    assert "Module 3 : 6.8 mΩ" in page and "Original" in page

    # destination non conforme rejetée dès le signalement
    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Résistance interne anormale d'un module", "comment": "HS",
                          "destination": "CT-EXPRESS"})
    assert "refusé" in r.get_data(as_text=True) or "agré" in r.get_data(as_text=True)

    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Résistance interne anormale d'un module", "comment": "HS",
                          "destination": "CT-NANTERRE"})
    assert "Demande envoyée" in r.get_data(as_text=True)
    # pas de double demande
    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Autre", "comment": "", "destination": "CT-NANTERRE"})
    assert "déjà en attente" in r.get_data(as_text=True)

    # 2. Centre de tri AVANT mise à jour : statut non à jour, réception refusée
    login(client, "centretri", "tri123")
    page = client.get("/tri/b/BAT-DOC-001").get_data(as_text=True)
    assert "NON à jour" in page
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True)
    assert "réception refusée" in r.get_data(as_text=True)

    # 3. Propriétaire : notification puis validation
    login(client, "proprietaire", "owner123")
    assert client.get("/api/notifications/count").json["pending"] == 1
    page = client.get("/owner").get_data(as_text=True)
    notif_uid = re.search(r"/owner/requests/(NOTIF-[0-9A-F]+)/approve", page).group(1)
    r = client.post(f"/owner/requests/{notif_uid}/approve", follow_redirects=True)
    assert "Waste" in r.get_data(as_text=True)
    assert repo.get_passport("BAT-DOC-001")["battery"]["status"] == "Waste"
    assert client.get("/api/notifications/count").json["pending"] == 0
    r = client.post(f"/owner/requests/{notif_uid}/approve", follow_redirects=True)
    assert "déjà été traitée" in r.get_data(as_text=True)

    # 4. Un autre centre de tri ne peut pas réceptionner
    login(client, "centretri2", "tri123")
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True)
    assert "attendue par" in r.get_data(as_text=True)

    # 5. Défi 2 : la réception exige un enlèvement par un transporteur agréé
    login(client, "centretri", "tri123")
    assert "Pas encore enlevée" in client.get("/tri/b/BAT-DOC-001").get_data(as_text=True)
    order = repo.get_passport("BAT-DOC-001")["transfer"]["uid"]
    login(client, "proprietaire", "owner123")
    client.post(f"/transfers/{order}/schedule", data={"carrier": "TR-TRANSBAT",
                                                      "pickup_date": date.today().isoformat()})
    login(client, "transporteur", "trans123")
    client.post(f"/transfers/{order}/pickup", data={
        "seal": "SC-104522", "weight": "522", "handed_over_by": "M. Brown",
        **{f"check_{k}": "1" for k in ("packaging", "terminals", "labels", "documents")}})

    # 6. Centre de tri destinataire : statut Waste, scellé et pesée, réception
    login(client, "centretri", "tri123")
    assert "BAT-DOC-001" in client.get("/tri").get_data(as_text=True)
    page = client.get("/tri/b/BAT-DOC-001").get_data(as_text=True)
    assert "✅ WASTE" in page and "Confirmer la réception" in page
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True,
                    data={"seal": "SC-104522", "weight": "521", "check_seal": "1", "check_packaging": "1"})
    assert "Réception enregistrée" in r.get_data(as_text=True)
    p = repo.get_passport("BAT-DOC-001")
    assert p["transfer"]["state"] == "RECEIVED" and p["location"]["uid"] == "CT-NANTERRE"

    # 7. Historique complet et traçable
    types = [e["type"] for e in repo.get_history("BAT-DOC-001")]
    for t in ("FAULT_REPORTED", "STATUS_CHANGED", "TRANSFER_ORDERED", "RECEIVED"):
        assert t in types


def test_refus_proprietaire(client):
    login(client, "garagiste", "garage123")
    client.post("/garage/b/BAT-002/report",
                data={"fault_type": "Autre", "comment": "test", "destination": "CT-NANTERRE"})
    login(client, "proprietaire", "owner123")
    n = repo.list_notifications("EO-FLUX")[0]
    r = client.post(f"/owner/requests/{n['uid']}/reject", follow_redirects=True, data={"comment": ""})
    assert "obligatoire" in r.get_data(as_text=True)
    client.post(f"/owner/requests/{n['uid']}/reject", data={"comment": "Sous garantie"})
    assert repo.get_passport("BAT-002")["battery"]["status"] == "Original"
    assert repo.get_notification(n["uid"])["state"] == "REJECTED"


def test_waste_battery_cannot_be_reported(client):
    login(client, "garagiste", "garage123")
    r = client.post("/garage/b/BAT-004/report", follow_redirects=True,
                    data={"fault_type": "Autre", "comment": "", "destination": "CT-NANTERRE"})
    assert "interdite" in r.get_data(as_text=True)


def test_all_pages_render(client):
    for user, pwd, urls in [
        ("garagiste", "garage123", ["/garage"] + [f"/garage/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("proprietaire", "owner123", ["/owner"] + [f"/owner/b/{b['id']}" for b in seed_data.BATTERIES]),
        ("centretri", "tri123", ["/tri"] + [f"/tri/b/{b['id']}" for b in seed_data.BATTERIES]),
    ]:
        login(client, user, pwd)
        for u in urls:
            assert client.get(u).status_code == 200, u
        assert client.get("/garage/b/INCONNUE").status_code in (302, 404)
        assert client.get("/api/battery/BAT-DOC-001").json["module_alerts"]


def test_cypher_export_covers_seed():
    stmts = seed_data.cypher_statements()
    assert sum(s.startswith("MERGE (n:BatteryInstance") for s in stmts) == len(seed_data.BATTERIES)
    assert all(not s.endswith(";") for s in stmts)
