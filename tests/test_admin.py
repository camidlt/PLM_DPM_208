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
    assert "Supervision" in res_admin.get_data(as_text=True)
    assert "Garage Hill Valley" in res_admin.get_data(as_text=True)


def test_admin_switch_account(client):
    # Log in as admin
    client.post("/login", data={"username": "admin", "password": "admin"})

    # Switch to garagiste
    res = client.get("/admin/switch/garagiste", follow_redirects=True)
    assert res.status_code == 200
    content = res.get_data(as_text=True)
    assert "Garage Hill Valley" in content
    # Admin bar must be present because session['is_admin'] is preserved
    assert "Mode Admin" in content

    # Switch to proprietaire
    res_prop = client.get("/admin/switch/proprietaire", follow_redirects=True)
    assert res_prop.status_code == 200
    content_prop = res_prop.get_data(as_text=True)
    assert "Flux Motors" in content_prop
    assert "Mode Admin" in content_prop

    # Switch back to admin
    res_back = client.get("/admin/switch/admin", follow_redirects=True)
    assert res_back.status_code == 200
    assert "Supervision" in res_back.get_data(as_text=True)


def test_admin_auto_switch_on_protected_routes(client):
    # Log in as admin
    client.post("/login", data={"username": "admin", "password": "admin"})

    # Admin accesses /garage directly -> auto-switches to garagiste
    res = client.get("/garage", follow_redirects=True)
    assert res.status_code == 200
    assert "Garage Hill Valley" in res.get_data(as_text=True)

    # Admin accesses /owner directly -> auto-switches to proprietaire
    res2 = client.get("/owner", follow_redirects=True)
    assert res2.status_code == 200
    assert "Flux Motors" in res2.get_data(as_text=True)


def test_non_admin_cannot_switch_or_access_admin(client):
    # Log in as garagiste
    client.post("/login", data={"username": "garagiste", "password": "garage123"})

    # Try to access /admin
    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

    # Try to switch
    res_switch = client.get("/admin/switch/proprietaire", follow_redirects=False)
    assert res_switch.status_code == 302
    assert "/login" in res_switch.headers["Location"]

