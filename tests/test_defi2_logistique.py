"""Défi 2 : logistique du transfert (transporteur, scellé, pesée, ADR, documents, notifications)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402
from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import app, repo  # noqa: E402
from bp import logistics  # noqa: E402

PICKUP_CHECKS = {f"check_{k}": "1" for k in logistics.PICKUP_CHECKS}
RECEPTION_CHECKS = {f"check_{k}": "1" for k in logistics.RECEPTION_CHECKS}
BANNED = re.compile("[–—\U0001F300-\U0001FAFF☀-➿⭐⭕]")


TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def client():
    repo.reset()
    return TestClient(app, follow_redirects=False)


def login(c, username, password):
    c.get("/logout")
    c.post("/login", data={"username": username, "password": password})


def report_and_approve(c, battery="BAT-DOC-001", auto=True, fault="Résistance interne anormale d'un module",
                       destination="CT-NANTERRE"):
    login(c, "garagiste", "garage123")
    data = {"fault_type": fault, "comment": "HS", "destination": destination,
            "pickup_date": TOMORROW, "pickup_slot": "14h-18h"}
    if auto:
        data["auto_logistics"] = "1"
    c.post(f"/garage/b/{battery}/report", data=data)
    login(c, "proprietaire", "owner123")
    n = next(n for n in repo.list_notifications("EO-FLUX") if n["state"] == "PENDING")
    r = c.post(f"/owner/requests/{n['uid']}/approve", data={}, follow_redirects=True)
    return repo.get_passport(battery)["transfer"], r


def pickup(c, order, seal="SC-104522", weight="522"):
    login(c, "transporteur", "trans123")
    return c.post(f"/transfers/{order}/pickup", follow_redirects=True,
                  data={"seal": seal, "weight": weight, "handed_over_by": "M. Brown", **PICKUP_CHECKS})


def test_auto_pickup_books_an_approved_carrier(client):
    t, r = report_and_approve(client)
    assert "planifiée automatiquement" in r.text
    assert t["state"] == "SCHEDULED" and t["carrierUid"] == "TR-TRANSBAT"
    assert t["pickupDate"] == TOMORROW and t["pickupSlot"] == "14h-18h"
    # le centre proposé par le garagiste est retenu sans ressaisie
    assert t["toUid"] == "CT-NANTERRE"


def test_garage_cannot_pick_unapproved_or_unequipped_centre(client):
    login(client, "garagiste", "garage123")
    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Autre", "destination": "CT-EXPRESS"})
    assert "non agréé" in r.text
    # Rhône Batteries n'accepte pas les batteries endommagées
    r = client.post("/garage/b/BAT-DOC-001/report", follow_redirects=True,
                    data={"fault_type": "Surchauffe", "destination": "CT-LYON"})
    assert "endommagées" in r.text
    assert repo.get_passport("BAT-DOC-001")["pending_request"] is None


def test_every_actor_is_notified(client):
    t, _ = report_and_approve(client)
    pickup(client, t["uid"])
    login(client, "centretri", "tri123")
    client.post("/tri/b/BAT-DOC-001/receive",
                data={"seal": "SC-104522", "weight": "521", **RECEPTION_CHECKS})
    subjects = {uid: [m["subject"] for m in repo.list_messages(uid)]
                for uid in ("OWNER-FLUX", "GARAGE-HV", "TR-TRANSBAT", "CT-NANTERRE")}
    assert any("Demande hors d'usage" in s for s in subjects["OWNER-FLUX"])
    assert any("Enlèvement planifié" in s for s in subjects["TR-TRANSBAT"])
    assert any("Batterie enlevée" in s for s in subjects["CT-NANTERRE"])
    assert any("Preuve de dépôt" in s for s in subjects["GARAGE-HV"])
    assert any("Preuve de dépôt" in s for s in subjects["TR-TRANSBAT"])
    # compteur non lu, puis lu après ouverture de la messagerie
    login(client, "transporteur", "trans123")
    assert client.get("/api/notifications/count").json()["unread"] >= 2
    assert "Enlèvement planifié" in client.get("/messages").text
    assert client.get("/api/notifications/count").json()["unread"] == 0


def test_weight_deviation_is_flagged(client):
    t, _ = report_and_approve(client)
    pickup(client, t["uid"], weight="522")
    login(client, "centretri", "tri123")
    client.post("/tri/b/BAT-DOC-001/receive",
                data={"seal": "SC-104522", "weight": "450", **RECEPTION_CHECKS})
    t = repo.get_transfer(t["uid"])
    assert t["state"] == "RECEIVED" and "Écart de pesée" in t["anomaly"]


def test_refusal_then_redirection_without_new_pickup(client):
    t, _ = report_and_approve(client, fault="Autre")
    pickup(client, t["uid"])
    login(client, "centretri", "tri123")
    r = client.post("/tri/b/BAT-DOC-001/refuse", follow_redirects=True, data={"reason": "Scellé rompu"})
    assert "Réception refusée" in r.text
    assert repo.get_transfer(t["uid"])["state"] == "REFUSED"
    assert repo.get_passport("BAT-DOC-001")["location"]["uid"] == "TR-TRANSBAT"
    # le propriétaire redirige vers un autre centre : la batterie reste sous scellé dans le camion
    login(client, "proprietaire", "owner123")
    r = client.post("/owner/b/BAT-DOC-001/new-order", data={"destination": "CT-NANTERRE"}, follow_redirects=True)
    assert "autre centre" in r.text
    client.post("/owner/b/BAT-DOC-001/new-order", data={"destination": "CT-LYON"})
    t2 = repo.get_passport("BAT-DOC-001")["transfer"]
    assert t2["state"] == "PICKED_UP" and t2["sealNumber"] == "SC-104522" and t2["toUid"] == "CT-LYON"
    login(client, "centretri2", "tri123")
    r = client.post("/tri/b/BAT-DOC-001/receive", follow_redirects=True,
                    data={"seal": "SC-104522", "weight": "522", **RECEPTION_CHECKS})
    assert "Réception enregistrée" in r.text


def test_cancel_before_pickup_only(client):
    t, _ = report_and_approve(client, auto=False)
    assert t["state"] == "ORDERED"
    r = client.post(f"/transfers/{t['uid']}/cancel", data={"reason": ""}, follow_redirects=True)
    assert "obligatoire" in r.text
    client.post(f"/transfers/{t['uid']}/cancel", data={"reason": "Reprise usine"})
    assert repo.get_transfer(t["uid"])["state"] == "CANCELLED"
    # le transporteur ne voit pas une mission qui ne lui est pas affectée
    login(client, "transporteur", "trans123")
    assert client.get(f"/transfers/{t['uid']}").status_code == 404


def test_signed_chain_and_tampering(client):
    t, _ = report_and_approve(client)
    pickup(client, t["uid"])
    steps = repo.get_transfer_steps(t["uid"])
    assert [s["type"] for s in steps] == ["ORDER_CREATED", "CARRIER_ASSIGNED", "PICKED_UP"]
    assert logistics.verify_chain(steps) == (True, None)
    steps[1]["dataJson"] = steps[1]["dataJson"].replace("TR-TRANSBAT", "TR-RAPIDFRET")
    assert logistics.verify_chain(steps) == (False, 2)


def test_documents_and_pages_render_cleanly(client):
    t, _ = report_and_approve(client)
    pickup(client, t["uid"])
    pages = {}
    for user, pwd in (("proprietaire", "owner123"), ("transporteur", "trans123"), ("garagiste", "garage123")):
        login(client, user, pwd)
        for u in [f"/transfers/{t['uid']}", f"/transfers/{t['uid']}/doc/ordre",
                  f"/transfers/{t['uid']}/doc/etiquette", f"/transfers/{t['uid']}/doc/manifeste"]:
            r = client.get(u)
            assert r.status_code == 200, (user, u)
            pages[(user, u)] = r.text
        pages[(user, "/messages")] = client.get("/messages").text
    label = pages[("proprietaire", f"/transfers/{t['uid']}/doc/etiquette")]
    assert "UN 3480" in label and "SC-104522" in label and "<svg" in label
    assert client.get(f"/transfers/{t['uid']}/doc/inconnu").status_code == 404
    doc = client.get(f"/api/transfers/{t['uid']}").json()
    assert doc["dangerousGoods"]["unNumber"] == "UN 3480" and doc["integrity"]["valid"]
    for key, html in pages.items():
        bad = BANNED.findall(html)
        assert not bad, f"{key} contient {bad[:5]}"
