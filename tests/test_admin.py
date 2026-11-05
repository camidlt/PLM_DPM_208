"""Tests du compte admin et de la commutation multi-comptes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BP_BACKEND"] = "memory"

import pytest
from app import app, repo
from bp import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    repo.reset()
    with app.test_client() as c:
        yield c


def test_admin_account_exists():
    assert "admin" in config.ACCOUNTS
    assert config.ACCOUNTS["admin"]["password"] == "admin"
    assert config.ACCOUNTS["admin"]["role"] == "admin"


def test_admin_login(client):
    res = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/admin")

    # Follow redirect to /admin
    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    html = res_admin.get_data(as_text=True)
    assert "Supervision" in html
    assert "Garage Hill Valley" in html
    # Vérification des deux onglets
    assert "tab-btn-comptes" in html
    assert "tab-btn-batteries" in html
    assert "account-search-input" in html
    assert "account-role-filter" in html
    assert "account-battery-filter" in html
    assert "battery-search-input" in html
    # Vérification des tableaux alignés et des 4 onglets de batteries
    assert "accounts-table" in html
    assert "batteries-table" in html
    assert "subtab-btn-healthy" in html
    assert "subtab-btn-damaged" in html
    assert "subtab-btn-transit" in html
    assert "subtab-btn-tri" in html


def test_admin_switch_account(client):
    client.post("/login", data={"username": "admin", "password": "admin"})

    res = client.get("/admin/switch/garagiste", follow_redirects=True)
    assert res.status_code == 200
    content = res.get_data(as_text=True)
    assert "Garage Hill Valley" in content
    assert "Mode Admin" in content

    res_prop = client.get("/admin/switch/proprietaire", follow_redirects=True)
    assert res_prop.status_code == 200
    content_prop = res_prop.get_data(as_text=True)
    assert "Flux Motors" in content_prop
    assert "Mode Admin" in content_prop

    res_back = client.get("/admin/switch/admin", follow_redirects=True)
    assert res_back.status_code == 200
    assert "Supervision" in res_back.get_data(as_text=True)


def test_admin_auto_switch_on_protected_routes(client):
    client.post("/login", data={"username": "admin", "password": "admin"})

    res = client.get("/garage", follow_redirects=True)
    assert res.status_code == 200
    assert "Garage Hill Valley" in res.get_data(as_text=True)

    res2 = client.get("/owner", follow_redirects=True)
    assert res2.status_code == 200
    assert "Flux Motors" in res2.get_data(as_text=True)


def test_non_admin_cannot_switch_or_access_admin(client):
    client.post("/login", data={"username": "garagiste", "password": "garage123"})

    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

    res_switch = client.get("/admin/switch/proprietaire", follow_redirects=False)
    assert res_switch.status_code == 302
    assert "/login" in res_switch.headers["Location"]


def test_admin_direct_status_change(client):
    """L'admin peut modifier directement le statut d'une batterie sans passer par un compte tiers."""
    client.post("/login", data={"username": "admin", "password": "admin"})

    # BAT-002 est initialement Original
    p_before = repo.get_passport("BAT-002")
    assert p_before["battery"]["status"] == "Original"

    # Modification directe vers Waste
    res = client.post("/admin/battery/BAT-002/status",
                      data={"status": "Waste", "comment": "Mise au rebut administrative directe"},
                      follow_redirects=True)
    assert res.status_code == 200

    p_after = repo.get_passport("BAT-002")
    assert p_after["battery"]["status"] == "Waste"

    # Vérification de l'événement dans l'historique
    history = repo.get_history("BAT-002")
    assert any("Statut modifié par l'administrateur : Waste" in e["details"] for e in history)


def test_admin_direct_incident_declaration(client):
    """L'admin peut déclarer directement une casse sans connexion au compte garagiste."""
    client.post("/login", data={"username": "admin", "password": "admin"})

    # BAT-DOC-001 est Original
    p_before = repo.get_passport("BAT-DOC-001")
    assert p_before["battery"]["status"] == "Original"

    # Déclaration directe d'une casse
    res = client.post("/admin/battery/BAT-DOC-001/incident",
                      data={
                          "fault_type": "Choc / déformation physique",
                          "comment": "Chute de pont en atelier, pack perforé",
                          "mode": "direct_waste",
                          "destination": "CT-NANTERRE",
                          "auto_logistics": "1"
                      },
                      follow_redirects=True)
    assert res.status_code == 200

    p_after = repo.get_passport("BAT-DOC-001")
    assert p_after["battery"]["status"] == "Waste"

    # Vérifie présence du transfert direct
    assert p_after.get("transfer") is not None
    assert p_after["transfer"]["toUid"] == "CT-NANTERRE"
