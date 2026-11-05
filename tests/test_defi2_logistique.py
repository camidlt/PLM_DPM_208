"""Défi 2 : logistique et conformité du transfert. python -m pytest -q"""
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest  # noqa: E402

from app import app, repo  # noqa: E402
from bp import logistics  # noqa: E402

TODAY = date.today().isoformat()
PICKUP_OK = {f"check_{k}": "1" for k in logistics.PICKUP_CHECKS}
RECEPTION_OK = {f"check_{k}": "1" for k in logistics.RECEPTION_CHECKS}


@pytest.fixture
def client():
    repo.reset()
    app.config["TESTING"] = True
    return app.test_client()


def login(c, username, password):
    c.get("/logout")
    c.post("/login", data={"username": username, "password": password})


def text(r):
    return r.get_data(as_text=True)


def approve(c, battery="BAT-DOC-001", fault="Résistance interne anormale d'un module",
            destination="CT-NANTERRE", auto=False, pickup_date=TODAY, pickup_slot="8h-12h"):
    """Tronc commun : signalement par le garage, validation par le propriétaire."""
    login(c, "garagiste", "garage123")
    r = c.post(f"/garage/b/{battery}/report", follow_redirects=True,
               data={"fault_type": fault, "comment": "HS", "destination": destination,
                     "auto_logistics": "1" if auto else "", "pickup_date": pickup_date,
                     "pickup_slot": pickup_slot})
    login(c, "proprietaire", "owner123")
    page = text(c.get("/owner"))
    match = re.search(r"/owner/requests/(NOTIF-[0-9A-F]+)/approve", page)
    if not match:
        return text(r)
    notif = match.group(1)
    r = c.post(f"/owner/requests/{notif}/approve", follow_redirects=True)
    t = repo.get_passport(battery)["transfer"]
    return t["uid"] if t else text(r)


def schedule(c, order, carrier="TR-TRANSBAT", day=TODAY):
    login(c, "proprietaire", "owner123")
    return c.post(f"/transfers/{order}/schedule", data={"carrier": carrier, "pickup_date": day,
                                                        "slot": "8h-12h"}, follow_redirects=True)


def pickup(c, order, seal="SC-104522", weight="522", **extra):
    login(c, "transporteur", "trans123")
    data = {"seal": seal, "weight": weight, "handed_over_by": "M. Brown", **PICKUP_OK, **extra}
    return c.post(f"/transfers/{order}/pickup", data=data, follow_redirects=True)


def receive(c, seal="SC-104522", weight="521", battery="BAT-DOC-001", user=("centretri", "tri123")):
    login(c, *user)
    return c.post(f"/tri/b/{battery}/receive", data={"seal": seal, "weight": weight, **RECEPTION_OK},
                  follow_redirects=True)


def test_parcours_logistique_complet(client):
    order = approve(client)
    t = repo.get_transfer(order)
    assert t["state"] == "ORDERED" and t["adrPacking"] == "P909" and t["declaredWeightKg"] == 520

    assert "Transporteur affecté" in text(schedule(client, order))
    t = repo.get_transfer(order)
    assert t["state"] == "SCHEDULED" and t["carrierUid"] == "TR-TRANSBAT" and t["pickupDate"] == TODAY

    # le transporteur voit sa mission, et le scan du QR ouvre la mission
    login(client, "transporteur", "trans123")
    assert "BAT-DOC-001" in text(client.get("/transport"))
    assert client.get("/b/BAT-DOC-001").headers["Location"].endswith("/transport/b/BAT-DOC-001")
    assert client.get("/transport/b/BAT-DOC-001").headers["Location"].endswith(f"/transfers/{order}")

    assert "Enlèvement enregistré" in text(pickup(client, order))
    p = repo.get_passport("BAT-DOC-001")
    assert p["transfer"]["state"] == "PICKED_UP" and p["location"]["uid"] == "TR-TRANSBAT"

    r = receive(client)
    assert "Preuve de dépôt" in text(r)
    t = repo.get_transfer(order)
    assert t["state"] == "RECEIVED" and len(t["receiptCode"]) == 12 and not t["anomaly"]
    assert repo.get_passport("BAT-DOC-001")["location"]["uid"] == "CT-NANTERRE"

    # étapes signées et chaîne d'intégrité
    doc = logistics.transfer_document(repo, order)
    assert [s["type"] for s in doc["steps"]] == ["ORDER_CREATED", "CARRIER_ASSIGNED", "PICKED_UP", "RECEIVED"]
    assert doc["integrity"]["valid"] and doc["custody"]["receiptCode"] == t["receiptCode"]
    assert doc["steps"][-1]["hash"].upper().startswith(t["receiptCode"])
    types = [e["type"] for e in repo.get_history("BAT-DOC-001")]
    for e in ("TRANSFER_SCHEDULED", "PICKED_UP", "RECEIVED"):
        assert e in types


def test_notifications_in_app(client):
    order = approve(client)
    schedule(client, order)
    login(client, "transporteur", "trans123")
    page = text(client.get("/messages"))
    assert "Enlèvement planifié : BAT-DOC-001" in page and "mail simulé" in page
    assert all(m["read"] for m in repo.list_messages("TR-TRANSBAT"))
    pickup(client, order)
    receive(client)
    owner_msgs = [m["subject"] for m in repo.list_messages("OWNER-FLUX")]
    assert "Batterie enlevée : BAT-DOC-001" in owner_msgs and "Preuve de dépôt : BAT-DOC-001" in owner_msgs
    assert any("Transfert annoncé" in m["subject"] for m in repo.list_messages("GARAGE-HV"))


def test_transporteur_non_agree_ou_non_equipe(client):
    order = approve(client)
    assert "non agréé" in text(schedule(client, order, carrier="TR-RAPIDFRET"))
    assert repo.get_transfer(order)["state"] == "ORDERED"
    assert "déjà passée" in text(schedule(client, order, day=(date.today() - timedelta(days=1)).isoformat()))
    # agrément expiré à la date d'enlèvement (Volt Express : valide jusqu'au 2027-03-31)
    assert "expiré" in text(schedule(client, order, carrier="TR-VOLTEXPRESS", day="2027-06-01"))


def test_batterie_endommagee(client):
    order = approve(client, battery="BAT-002", fault="Dommage physique / gonflement", destination="CT-LYON")
    assert "endommagées" in order          # Rhône Batteries n'accepte pas les batteries endommagées
    assert repo.get_passport("BAT-002")["battery"]["status"] == "Original"
    order = approve(client, battery="BAT-002", fault="Dommage physique / gonflement", destination="CT-NANTERRE")
    t = repo.get_passport("BAT-002")["transfer"]
    t = repo.get_transfer(t["uid"])
    assert t["damageClass"] == "damaged" and t["adrProvision"] == "DS 376" and "P908" in t["adrPacking"]
    # Volt Express (agréé, mais non équipé batteries endommagées) est refusé
    assert "non équipé" in text(schedule(client, t["uid"], carrier="TR-VOLTEXPRESS"))
    assert logistics.damage_class("Surchauffe. fumée") == "critical"


def test_controles_enlevement(client):
    order = approve(client)
    schedule(client, order)
    assert "scellé invalide" in text(pickup(client, order, seal="x"))
    assert "nombre attendu" in text(pickup(client, order, weight="lourd"))
    login(client, "transporteur", "trans123")
    r = client.post(f"/transfers/{order}/pickup", follow_redirects=True,
                    data={"seal": "SC-1", "weight": "520", "handed_over_by": "M. Brown"})
    assert "Contrôles non validés" in text(r) or "scellé invalide" in text(r)
    r = client.post(f"/transfers/{order}/pickup", follow_redirects=True,
                    data={"seal": "SC-1234", "weight": "520", "handed_over_by": "M. Brown"})
    assert "Contrôles non validés" in text(r)
    assert repo.get_transfer(order)["state"] == "SCHEDULED"
    # un autre rôle ne peut pas enregistrer l'enlèvement
    login(client, "garagiste", "garage123")
    r = client.post(f"/transfers/{order}/pickup", data={"seal": "SC-1234"})
    assert r.status_code == 302 and repo.get_transfer(order)["state"] == "SCHEDULED"


def test_reception_controle_scelle_et_pesee(client):
    order = approve(client)
    assert "pas encore été enlevée" in text(receive(client))
    schedule(client, order)
    pickup(client, order)
    assert "Scellé non conforme" in text(receive(client, seal="SC-999999"))
    assert "attendue par" in text(receive(client, user=("centretri2", "tri123")))
    receive(client, weight="480")      # -8 % : réception acceptée mais anomalie tracée
    t = repo.get_transfer(order)
    assert t["state"] == "RECEIVED" and "Écart de pesée" in t["anomaly"]


def test_refus_puis_redirection(client):
    order = approve(client)
    schedule(client, order)
    pickup(client, order)
    login(client, "centretri", "tri123")
    r = client.post("/tri/b/BAT-DOC-001/refuse", data={"reason": "Emballage chaud"}, follow_redirects=True)
    assert "Réception refusée" in text(r)
    assert repo.get_transfer(order)["state"] == "REFUSED"
    assert repo.get_passport("BAT-DOC-001")["location"]["uid"] == "TR-TRANSBAT"

    login(client, "proprietaire", "owner123")
    r = client.post("/owner/b/BAT-DOC-001/new-order", data={"destination": "CT-NANTERRE"}, follow_redirects=True)
    assert "autre centre" in text(r)
    client.post("/owner/b/BAT-DOC-001/new-order", data={"destination": "CT-LYON"})
    new = repo.get_passport("BAT-DOC-001")["transfer"]
    new = repo.get_transfer(new["uid"])
    assert new["uid"] != order and new["state"] == "PICKED_UP" and new["sealNumber"] == "SC-104522"
    assert new["previousOrder"] == order and new["carrierUid"] == "TR-TRANSBAT"
    r = receive(client, user=("centretri2", "tri123"))
    assert "Preuve de dépôt" in text(r)
    assert repo.get_passport("BAT-DOC-001")["location"]["uid"] == "CT-LYON"


def test_annulation_puis_nouvel_ordre(client):
    order = approve(client)
    schedule(client, order)
    login(client, "proprietaire", "owner123")
    r = client.post(f"/transfers/{order}/cancel", data={"reason": ""}, follow_redirects=True)
    assert "obligatoire" in text(r)
    client.post(f"/transfers/{order}/cancel", data={"reason": "Reprise usine"})
    assert repo.get_transfer(order)["state"] == "CANCELLED"
    assert "TRANSFER_CANCELLED" in [e["type"] for e in repo.get_history("BAT-DOC-001")]
    client.post("/owner/b/BAT-DOC-001/new-order", data={"destination": "CT-LYON"})
    new = repo.get_passport("BAT-DOC-001")["transfer"]
    assert new["uid"] != order and new["state"] == "ORDERED" and new["toUid"] == "CT-LYON"
    # pas d'annulation après l'enlèvement
    schedule(client, new["uid"])
    pickup(client, new["uid"])
    login(client, "proprietaire", "owner123")
    r = client.post(f"/transfers/{new['uid']}/cancel", data={"reason": "x"}, follow_redirects=True)
    assert "Action impossible" in text(r)


def test_documents_et_droits(client):
    order = approve(client)
    schedule(client, order)
    pickup(client, order)
    for user in (("proprietaire", "owner123"), ("transporteur", "trans123"), ("centretri", "tri123"),
                 ("garagiste", "garage123")):
        login(client, *user)
        assert client.get(f"/transfers/{order}").status_code == 200, user
        for doc in ("ordre", "etiquette", "manifeste"):
            page = text(client.get(f"/transfers/{order}/{doc}"))
            assert "UN 3480" in page and "SC-104522" in page, (user, doc)
        d = client.get(f"/api/transfers/{order}").json
        assert d["schema"] == "battery-passport/transfer-manifest/1"
        assert d["dangerousGoods"]["heavyLoad"] and d["parties"]["carrier"]["uid"] == "TR-TRANSBAT"
    # un centre de tri non concerné n'a pas accès
    login(client, "centretri2", "tri123")
    assert client.get(f"/transfers/{order}").status_code == 404
    assert client.get(f"/api/transfers/{order}").status_code == 404
    assert client.get(f"/transfers/{order}/inconnu").status_code == 404


def test_chaine_falsifiee_detectee(client):
    order = approve(client)
    schedule(client, order)
    steps = repo.get_transfer_steps(order)
    assert logistics.verify_chain(steps) == (True, None)
    steps[0]["dataJson"] = steps[0]["dataJson"].replace("CT-NANTERRE", "CT-EXPRESS")
    assert logistics.verify_chain(steps) == (False, 1)


def test_toutes_les_pages_du_defi2(client):
    order = approve(client)
    for user, urls in [(("proprietaire", "owner123"), ["/owner", f"/transfers/{order}", "/messages"]),
                       (("transporteur", "trans123"), ["/transport", "/messages"]),
                       (("garagiste", "garage123"), ["/garage/b/BAT-DOC-001"])]:
        login(client, *user)
        for u in urls:
            assert client.get(u).status_code == 200, u
    login(client, "garagiste", "garage123")
    assert "Enlèvement à planifier" in text(client.get("/garage/b/BAT-DOC-001"))


def test_planification_auto_apres_validation(client):
    order = approve(client, auto=True)
    login(client, "proprietaire", "owner123")
    r = client.get("/owner", follow_redirects=True)
    page = text(r)
    assert "collecte planifiée automatiquement" in page or order.startswith("TO-")
    t = repo.get_passport("BAT-DOC-001")["transfer"]
    t = repo.get_transfer(t["uid"])
    assert t["state"] == "SCHEDULED"
    assert t["carrierUid"] == "TR-TRANSBAT"
    assert t["pickupDate"] == TODAY
