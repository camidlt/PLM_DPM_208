"""Battery Passport, PoC du hackathon ESILV x Capgemini Engineering « Battery to the Future ».

Une seule application FastAPI :
  - /                   page de présentation (jury), flux live de l'ESP32
  - /garage             garagiste (tablette) : scan QR, passeport, télémétrie live, signalement
  - /owner              propriétaire du passeport (desktop) : Original vers Waste, ordre de transfert
  - /tri                centre de tri (mobile) : contrôle du statut, réception, aide à la décision (défi 3)
  - /public/b/<id>      passeport public (Annexe XIII)
  - POST /api/telemetry mesures BMS envoyées par l'ESP32 en Wi-Fi (défi 1)

Lancement : uvicorn app:app --host 0.0.0.0 --port 8000   (voir README.md)
"""
import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from bp import config, decision, make_repo, telemetry, workflow
from bp.workflow import WorkflowError

log = logging.getLogger("bp")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO_BATTERY = os.environ.get("BP_DEMO_BATTERY", "DLR-1985")
DEVICE_TOKEN = os.environ.get("BP_DEVICE_TOKEN", "")      # vide = pas de contrôle
DEVICE_ONLINE_S = 10                                       # appareil « en ligne » si vu il y a moins de 10 s
MQTT_HOST = os.environ.get("MQTT_HOST", "")                # vide = MQTT désactivé (Wi-Fi HTTP par défaut)
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
TOPIC_PREFIX = os.environ.get("TOPIC_PREFIX", "esilv-hack-2026/equipe-XX")

repo = make_repo()
DEVICES = {}  # identifiant appareil -> dernier contact (état volatil, hors graphe)

ROLE_HOME = {"garagiste": "garage_home", "proprietaire": "owner_home", "centre_tri": "tri_home"}
ROLE_BATTERY = {"garagiste": "garage_battery", "proprietaire": "owner_battery",
                "centre_tri": "tri_battery"}
ROLE_LABEL = {"garagiste": "Garagiste", "proprietaire": "Propriétaire du passeport",
              "centre_tri": "Centre de tri"}
EVENT_LABEL = {"MANUFACTURED": "Fabrication", "PUT_ON_MARKET": "Mise sur le marché",
               "MAINTENANCE": "Maintenance", "FAULT_REPORTED": "Hors d'usage signalé",
               "STATUS_CHANGED": "Statut modifié", "TRANSFER_ORDERED": "Transfert ordonné",
               "REQUEST_REJECTED": "Demande refusée", "RECEIVED": "Réception centre de tri",
               "DECISION_RECORDED": "Décision enregistrée", "BMS_ALERT": "Alerte BMS"}


# --- MQTT (optionnel, pour le simulateur Wokwi) ----------------------------------------
def start_mqtt():
    if not MQTT_HOST:
        log.info("MQTT désactivé (MQTT_HOST vide) : l'ESP32 envoie en HTTP sur /api/telemetry")
        return None
    import paho.mqtt.client as mqtt
    topic = f"{TOPIC_PREFIX}/battery/+/telemetry"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("MQTT connecté à %s, abonnement %s", MQTT_HOST, topic)
        c.subscribe(topic)

    def on_message(c, userdata, msg):
        try:
            ingest(json.loads(msg.payload), device_id="mqtt", source="MQTT")
        except Exception as e:  # ne jamais tuer la boucle MQTT
            log.warning("Message MQTT ignoré : %s", e)

    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        client.loop_start()
    except Exception as e:
        log.warning("Connexion MQTT impossible (%s), l'ingestion HTTP reste disponible", e)
    return client


@asynccontextmanager
async def lifespan(_app):
    log.info("Base de données : %s · QR codes vers %s", repo.backend, config.BASE_URL)
    client = start_mqtt()
    yield
    if client:
        client.loop_stop()


app = FastAPI(title="Battery Passport", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, same_site="lax")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(ROOT, "templates"))


# --- Gabarits ----------------------------------------------------------------------------
def url_for(name, **params):
    """url_for façon Flask : paramètres de chemin, le reste en query string."""
    if name == "static":
        return f"/static/{params['filename']}"
    route = next(r for r in app.routes if getattr(r, "name", None) == name)
    path_keys = set(getattr(route, "param_convertors", {}) or {})
    path = app.url_path_for(name, **{k: str(params.pop(k)) for k in list(params) if k in path_keys})
    query = {k: v for k, v in params.items() if v is not None}
    return str(path) + ("?" + urlencode(query) if query else "")


def fmt_ts(value):
    """2026-11-03T09:00:00 -> 03/11/2026 09:00"""
    if not value:
        return "Non renseigné"
    v = str(value).replace("Z", "")
    try:
        d, t = v.split("T")
        y, m, dd = d.split("-")
        return f"{dd}/{m}/{y} {t[:5]}"
    except ValueError:
        return v


def icon(name, cls="", label=None):
    """Icône Lucide depuis le sprite static/icons.svg."""
    aria = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    return Markup(f'<svg class="ic {escape(cls)}" {aria}><use href="/static/icons.svg#i-{escape(name)}"/></svg>')


templates.env.globals.update(url_for=url_for, icon=icon, role_label=ROLE_LABEL, event_label=EVENT_LABEL,
                             module_alerts=workflow.module_alerts, option_fr=decision.OPTION_FR,
                             demo_battery=DEMO_BATTERY)
templates.env.filters["ts"] = fmt_ts


class Redirect(Exception):
    def __init__(self, url):
        self.url = url


@app.exception_handler(Redirect)
async def _redirect(_request, exc):
    return RedirectResponse(exc.url, status_code=303)


def flash(request, message, category="success"):
    request.session.setdefault("_flashes", []).append([category, message])


def current_user(request):
    username = request.session.get("user")
    if username not in config.ACCOUNTS:
        return None
    return {"username": username, **config.ACCOUNTS[username]}


def require(request, role=None):
    user = current_user(request)
    if user is None:
        nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise Redirect(url_for("login", next=nxt))
    if role and user["role"] != role:
        flash(request, f"Accès réservé au rôle « {ROLE_LABEL[role]} ».", "error")
        raise Redirect(url_for(ROLE_HOME[user["role"]]))
    return user


def render(request, name, status_code=200, **ctx):
    user = current_user(request)
    pending = 0
    if user and user["role"] == "proprietaire":
        pending = sum(1 for n in repo.list_notifications(user["operator_uid"]) if n["state"] == "PENDING")
    ctx.update(request=request, user=user, pending_count=pending, backend=repo.backend,
               base_url=config.BASE_URL, flashes=request.session.pop("_flashes", []))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def load_passport(battery_id):
    p = repo.get_passport(battery_id)
    if p is None:
        raise StarletteHTTPException(404)
    return p


def back_to(form, default):
    back = form.get("back") or ""
    return back if back.startswith("/") and not back.startswith("//") else default


# --- Pages publiques -------------------------------------------------------------------
@app.get("/", name="landing")
def landing(request: Request):
    p = repo.get_passport(DEMO_BATTERY)
    # Défi 3 : recommandations réelles pour les batteries déjà au centre de tri de Nanterre
    policy, demands, outcomes = repo.get_center_policy("CT-NANTERRE"), repo.list_demands(), []
    for b in repo.list_batteries():
        bp_ = repo.get_passport(b["batteryId"])
        if b["status"] == "Waste" and (bp_.get("location") or {}).get("uid") == "CT-NANTERRE":
            outcomes.append(dict(batteryId=b["batteryId"],
                                 result=decision.recommend(bp_, demands, params=policy)))
    return render(request, "landing.html", p=p, live=live_payload(DEMO_BATTERY),
                  accounts=config.ACCOUNTS, batteries=repo.list_batteries(), outcomes=outcomes)


@app.get("/login", name="login")
def login_page(request: Request):
    return render(request, "login.html", accounts=config.ACCOUNTS,
                  next=request.query_params.get("next", ""), preset=request.query_params.get("as", ""))


@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip().lower()
    account = config.ACCOUNTS.get(username)
    nxt = request.query_params.get("next") or form.get("next") or ""
    if account and form.get("password") == account["password"]:
        request.session["user"] = username
        if nxt.startswith("/") and not nxt.startswith("//"):
            return RedirectResponse(nxt, status_code=303)
        return RedirectResponse(url_for(ROLE_HOME[account["role"]]), status_code=303)
    flash(request, "Identifiant ou mot de passe incorrect.", "error")
    return RedirectResponse(url_for("login", next=nxt or None), status_code=303)


@app.get("/logout", name="logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url_for("landing"), status_code=303)


@app.get("/app", name="index")
def index(request: Request):
    user = require(request)
    return RedirectResponse(url_for(ROLE_HOME[user["role"]]), status_code=303)


# --- QR code / scan ---------------------------------------------------------------------
def parse_battery_code(code):
    """Accepte une URL de QR code (.../b/DLR-1985 ou ...?battery=DLR-1985) ou un identifiant brut."""
    code = (code or "").strip()
    if not code:
        return None
    if "://" in code:
        u = urlparse(code)
        if "battery" in parse_qs(u.query):
            return parse_qs(u.query)["battery"][0]
        parts = [p for p in u.path.split("/") if p]
        return parts[-1] if parts else None
    return code.upper()


@app.get("/b/{battery_id}", name="battery_entry")
def battery_entry(request: Request, battery_id: str):
    """Cible des QR codes : vue métier si connecté, sinon passeport public (Annexe XIII)."""
    user = current_user(request)
    if user:
        return RedirectResponse(url_for(ROLE_BATTERY[user["role"]], battery_id=battery_id), status_code=303)
    return RedirectResponse(url_for("public_battery", battery_id=battery_id), status_code=303)


@app.get("/public/b/{battery_id}", name="public_battery")
def public_battery(request: Request, battery_id: str):
    return render(request, "public_battery.html", p=load_passport(battery_id))


@app.get("/lookup", name="lookup")
def lookup(request: Request):
    """Recherche depuis la page d'accueil : ouvre la vue adaptée au visiteur."""
    battery_id = parse_battery_code(request.query_params.get("code"))
    if not battery_id or repo.get_passport(battery_id) is None:
        flash(request, "Identifiant de batterie non reconnu. Essayez DLR-1985.", "error")
        return RedirectResponse(url_for("landing") + "#acces", status_code=303)
    return RedirectResponse(url_for("battery_entry", battery_id=battery_id), status_code=303)


@app.get("/scan", name="scan")
def scan(request: Request):
    user = require(request)
    battery_id = parse_battery_code(request.query_params.get("code"))
    if not battery_id or repo.get_passport(battery_id) is None:
        flash(request, "QR code ou identifiant de batterie non reconnu.", "error")
        return RedirectResponse(url_for(ROLE_HOME[user["role"]]), status_code=303)
    return RedirectResponse(url_for(ROLE_BATTERY[user["role"]], battery_id=battery_id), status_code=303)


@app.get("/qr/{battery_id}.png", name="qr_png")
def qr_png(battery_id: str):
    import qrcode
    img = qrcode.make(f"{config.BASE_URL}/b/{battery_id}", box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


# --- Garagiste ----------------------------------------------------------------------------
@app.get("/garage", name="garage_home")
def garage_home(request: Request):
    require(request, "garagiste")
    return render(request, "garage_home.html", batteries=repo.list_batteries())


@app.get("/garage/b/{battery_id}", name="garage_battery")
def garage_battery(request: Request, battery_id: str):
    require(request, "garagiste")
    p = load_passport(battery_id)
    return render(request, "garage_battery.html", p=p, history=repo.get_history(battery_id),
                  fault_types=workflow.FAULT_TYPES, live=live_payload(battery_id))


@app.post("/garage/b/{battery_id}/report", name="garage_report")
async def garage_report(request: Request, battery_id: str):
    user = require(request, "garagiste")
    form = await request.form()
    try:
        workflow.request_waste(repo, battery_id, user, form.get("fault_type", ""), form.get("comment", ""))
        flash(request, "Demande envoyée au propriétaire du Battery Passport.")
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(url_for("garage_battery", battery_id=battery_id), status_code=303)


# --- Propriétaire -------------------------------------------------------------------------
@app.get("/owner", name="owner_home")
def owner_home(request: Request):
    user = require(request, "proprietaire")
    notifs = repo.list_notifications(user["operator_uid"])
    return render(request, "owner_home.html",
                  pending=[n for n in notifs if n["state"] == "PENDING"],
                  processed=[n for n in notifs if n["state"] != "PENDING"],
                  batteries=repo.list_batteries(), centers=repo.list_actors("centre_tri"))


@app.get("/owner/b/{battery_id}", name="owner_battery")
def owner_battery(request: Request, battery_id: str):
    require(request, "proprietaire")
    p = load_passport(battery_id)
    return render(request, "owner_battery.html", p=p, history=repo.get_history(battery_id),
                  centers=repo.list_actors("centre_tri"), live=live_payload(battery_id))


@app.post("/owner/requests/{notif_uid}/approve", name="owner_approve")
async def owner_approve(request: Request, notif_uid: str):
    user = require(request, "proprietaire")
    form = await request.form()
    try:
        workflow.approve_request(repo, notif_uid, user, form.get("destination", ""), form.get("comment", ""))
        flash(request, "Statut passé à « Waste » et ordre de transfert créé.")
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(back_to(form, url_for("owner_home")), status_code=303)


@app.post("/owner/requests/{notif_uid}/reject", name="owner_reject")
async def owner_reject(request: Request, notif_uid: str):
    user = require(request, "proprietaire")
    form = await request.form()
    try:
        workflow.reject_request(repo, notif_uid, user, form.get("comment", ""))
        flash(request, "Demande refusée, le garagiste en sera informé.")
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(back_to(form, url_for("owner_home")), status_code=303)


# --- Centre de tri ------------------------------------------------------------------------
@app.get("/tri", name="tri_home")
def tri_home(request: Request):
    user = require(request, "centre_tri")
    return render(request, "tri_home.html", transfers=repo.list_transfers_to(user["actor_uid"]),
                  batteries=repo.list_batteries())


def decision_context(request, p, user):
    """Contexte du panneau d'aide à la décision (défi 3)."""
    battery_id = p["battery"]["batteryId"]
    loc = p.get("location") or {}
    ready = p["battery"]["status"] == "Waste" and loc.get("uid") == user["actor_uid"]
    policy = repo.get_center_policy(user["actor_uid"])
    demands = repo.list_demands()
    return dict(ready=ready, result=decision.recommend(p, demands, params=policy) if ready else None,
                tab=request.query_params.get("tab", "classement"), demands=demands, policy=policy,
                criteria=decision.CRITERIA, weights=decision.DEFAULT_WEIGHTS,
                decisions=repo.get_decisions(battery_id))


@app.get("/tri/b/{battery_id}", name="tri_battery")
def tri_battery(request: Request, battery_id: str):
    user = require(request, "centre_tri")
    p = load_passport(battery_id)
    return render(request, "tri_battery.html", p=p, d=decision_context(request, p, user),
                  history=repo.get_history(battery_id))


@app.post("/tri/b/{battery_id}/receive", name="tri_receive")
def tri_receive(request: Request, battery_id: str):
    user = require(request, "centre_tri")
    try:
        workflow.confirm_reception(repo, battery_id, user)
        flash(request, "Réception enregistrée dans le Battery Passport.")
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(url_for("tri_battery", battery_id=battery_id), status_code=303)


@app.post("/tri/b/{battery_id}/decision", name="tri_decision")
async def tri_decision(request: Request, battery_id: str):
    """Enregistre la décision du centre de tri (défi 3)."""
    user = require(request, "centre_tri")
    form = await request.form()
    target = url_for("tri_battery", battery_id=battery_id) + "#decision"
    p = load_passport(battery_id)
    loc = p.get("location") or {}
    if p["battery"]["status"] != "Waste":
        flash(request, "Décision impossible : le statut n'est pas « Waste ».", "error")
        return RedirectResponse(target, status_code=303)
    if loc.get("uid") != user["actor_uid"]:
        flash(request, "Décision impossible : la batterie n'est pas réceptionnée par votre centre.", "error")
        return RedirectResponse(target, status_code=303)
    result = decision.recommend(p, repo.list_demands(), params=repo.get_center_policy(user["actor_uid"]))
    chosen, comment = form.get("chosen", ""), (form.get("comment") or "").strip()
    opts = {o["option"]: o for o in result["options"]}
    if chosen not in opts:
        flash(request, "Option inconnue.", "error")
    elif not opts[chosen]["feasible"]:
        flash(request, f"{chosen} est exclue : " + " ; ".join(opts[chosen]["excluded_because"]), "error")
    elif chosen != result["recommendation"] and not comment:
        flash(request, "Choix différent de la recommandation : commentaire obligatoire.", "error")
    else:
        repo.record_decision(battery_id, user["actor_uid"], chosen, comment, result)
        flash(request, f"Décision « {chosen} » enregistrée dans le Battery Passport.")
    return RedirectResponse(target, status_code=303)


@app.post("/tri/priorities", name="tri_priorities")
async def tri_priorities(request: Request):
    user = require(request, "centre_tri")
    form = await request.form()
    policy = repo.get_center_policy(user["actor_uid"])
    key = form.get("toggle")
    if key in policy:
        policy[key] = not policy[key]
        repo.set_center_policy(user["actor_uid"], policy["use_market"], policy["use_hierarchy"])
        flash(request, "Priorités du centre de tri mises à jour.")
    return RedirectResponse(back_to(form, url_for("tri_home")), status_code=303)


@app.get("/tri/market", name="tri_market")
def tri_market(request: Request):
    require(request, "centre_tri")
    back = request.query_params.get("back", "")
    return render(request, "tri_market.html", demands=repo.list_demands(),
                  back=back if back.startswith("/tri/") else url_for("tri_home"))


@app.post("/tri/market/{demand_uid}/toggle", name="tri_market_toggle")
async def tri_market_toggle(request: Request, demand_uid: str):
    require(request, "centre_tri")
    form = await request.form()
    demands = {d["uid"]: d for d in repo.list_demands()}
    if demand_uid not in demands:
        flash(request, "Demande inconnue.", "error")
    else:
        new_state = not demands[demand_uid].get("active")
        repo.set_demand_active(demand_uid, new_state)
        flash(request, f"Demande « {demands[demand_uid]['title']} » {'activée' if new_state else 'désactivée'}.")
    back = form.get("back") or ""
    return RedirectResponse(back if back.startswith("/tri/") else url_for("tri_market"), status_code=303)


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.post("/tri/market/add", name="tri_market_add")
async def tri_market_add(request: Request):
    """Ajoute une demande du marché au catalogue (défi 3, apport de Camille)."""
    user = require(request, "centre_tri")
    form = await request.form()
    title = (form.get("title") or "").strip()
    if not title:
        flash(request, "Le titre de la demande est obligatoire.", "error")
    else:
        option = form.get("option") if form.get("option") in decision.OPTIONS else "Repurpose"
        urgency = form.get("urgency") if form.get("urgency") in decision.URGENCY_BONUS else "normale"
        repo.add_demand(center_uid=user["actor_uid"], title=title, option=option,
                        partner=(form.get("partner") or "").strip() or "Partenaire industriel",
                        chemistries=form.getlist("chemistries") or ["NMC 811", "LFP"],
                        min_soce=max(0, min(100, _int(form.get("min_soce"), 60))), urgency=urgency,
                        quantity=max(1, _int(form.get("quantity"), 10)),
                        location=(form.get("location") or "").strip() or "France")
        flash(request, f"Demande « {title} » ajoutée au catalogue du marché.")
    back = form.get("back") or ""
    return RedirectResponse(back if back.startswith("/tri/") else url_for("tri_market"), status_code=303)


@app.post("/tri/market/{demand_uid}/delete", name="tri_market_delete")
async def tri_market_delete(request: Request, demand_uid: str):
    require(request, "centre_tri")
    form = await request.form()
    demands = {d["uid"]: d for d in repo.list_demands()}
    if demand_uid in demands:
        repo.delete_demand(demand_uid)
        flash(request, f"Demande « {demands[demand_uid]['title']} » retirée du catalogue du marché.")
    else:
        flash(request, "Demande introuvable.", "error")
    back = form.get("back") or ""
    return RedirectResponse(back if back.startswith("/tri/") else url_for("tri_market"), status_code=303)


# --- Défi 1 : télémétrie ESP32 --------------------------------------------------------------
def device_view():
    nowt = time.time()
    out = []
    for dev_id, d in sorted(DEVICES.items(), key=lambda kv: -kv[1]["lastSeen"]):
        age = nowt - d["lastSeen"]
        out.append(dict(id=dev_id, batteryId=d["batteryId"], source=d["source"], ip=d["ip"],
                        packets=d["packets"], ageSeconds=round(age, 1), online=age < DEVICE_ONLINE_S))
    return out


def live_payload(battery_id, limit=40):
    data = repo.get_telemetry(battery_id, limit=limit)
    if data is None:
        return None
    devices = [d for d in device_view() if d["batteryId"] == battery_id]
    data["device"] = devices[0] if devices else None
    data["online"] = bool(devices and devices[0]["online"])
    return data


def ingest(payload, device_id, source, ip=None):
    battery_id, ts, readings = telemetry.parse_payload(payload)
    raised = repo.record_telemetry(battery_id, readings, ts=ts, source=source)
    d = DEVICES.setdefault(device_id, dict(packets=0))
    d.update(lastSeen=time.time(), batteryId=battery_id, source=source, ip=ip, packets=d["packets"] + 1)
    return battery_id, raised


@app.post("/api/telemetry", name="api_telemetry")
async def api_telemetry(request: Request):
    """Point d'entrée de l'ESP32 (Wi-Fi), de l'émulateur Python et de tout BMS HTTP."""
    if DEVICE_TOKEN and request.headers.get("x-device-token") != DEVICE_TOKEN:
        return JSONResponse({"ok": False, "error": "Jeton d'appareil invalide (X-Device-Token)."}, 401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Corps JSON invalide."}, 400)
    ip = request.client.host if request.client else None
    device_id = request.headers.get("x-device-id") or payload.get("device") or ip or "inconnu"
    source = payload.get("source") or ("ESP32" if "esp32" in device_id.lower() else "HTTP")
    try:
        battery_id, raised = ingest(payload, device_id=device_id, source=source, ip=ip)
    except telemetry.TelemetryError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)
    return {"ok": True, "batteryId": battery_id, "alerts": raised}


@app.get("/api/live", name="api_live_public")
def api_live_public():
    """Flux de la batterie de démonstration pour la page d'accueil (banc BMS, données fictives)."""
    return live_payload(DEMO_BATTERY) or {}


@app.get("/api/battery/{battery_id}/live", name="api_live")
def api_live(request: Request, battery_id: str):
    require(request)
    data = live_payload(battery_id)
    if data is None:
        return JSONResponse({"error": "Batterie inconnue"}, 404)
    return data


@app.get("/api/devices", name="api_devices")
def api_devices():
    return device_view()


# --- API JSON -----------------------------------------------------------------------------
@app.get("/api/battery/{battery_id}", name="api_battery")
def api_battery(request: Request, battery_id: str):
    require(request)
    p = load_passport(battery_id)
    return dict(passport=p, history=repo.get_history(battery_id), module_alerts=workflow.module_alerts(p))


@app.get("/api/battery/{battery_id}/recommendation", name="api_recommendation")
def api_recommendation(request: Request, battery_id: str):
    user = require(request)
    p = load_passport(battery_id)
    center_uid = request.query_params.get("center_uid") or user.get("actor_uid")
    policy = repo.get_center_policy(center_uid) if center_uid else {}
    return decision.recommend(p, repo.list_demands(), params=policy)


@app.get("/api/notifications/count", name="api_notif_count")
def api_notif_count(request: Request):
    user = require(request)
    if user["role"] != "proprietaire":
        return {"pending": 0}
    return {"pending": sum(1 for n in repo.list_notifications(user["operator_uid"]) if n["state"] == "PENDING")}


@app.post("/admin/reset", name="admin_reset")
def admin_reset(request: Request):
    user = require(request)
    repo.reset()
    DEVICES.clear()
    flash(request, "Données de démo réinitialisées.")
    return RedirectResponse(url_for(ROLE_HOME[user["role"]]), status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, exc.status_code)
    msg = "Batterie ou page introuvable." if exc.status_code == 404 else str(exc.detail)
    return render(request, "error.html", status_code=exc.status_code, message=msg)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("BP_HOST", "0.0.0.0"), port=int(os.environ.get("BP_PORT", 8000)))
