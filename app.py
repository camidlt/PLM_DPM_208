"""Battery Passport, PoC du hackathon ESILV x Capgemini Engineering « Battery to the Future ».

Une seule application FastAPI :
  - /                   page de présentation (jury), flux live de l'ESP32
  - /garage             garagiste (tablette) : scan QR, passeport, télémétrie live, signalement
  - /owner              propriétaire du passeport (desktop) : Original vers Waste, ordre de transfert
  - /tri                centre de tri (mobile) : contrôle du statut, réception, aide à la décision (défi 3)
  - /transport          transporteur (mobile) : enlèvement scellé, pesé, contrôles ADR (défi 2)
  - /transfers/<ordre>  suivi du transfert, documents (étiquette UN 3480, ordre, manifeste)
  - /messages           notifications de chaque acteur
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
from datetime import date
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from bp import config, decision, logistics, make_repo, telemetry, workflow
from bp.workflow import WorkflowError

log = logging.getLogger("bp")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO_BATTERY = telemetry.normalize_id(os.environ.get("BP_DEMO_BATTERY", "BAT-DOC-001"))
# Clé machine du BMS : en-tête X-BMS-Key (ou X-Device-Token). BP_DEVICE_TOKEN reste accepté.
DEVICE_TOKEN = os.environ.get("BP_DEVICE_TOKEN", "") or config.BMS_API_KEY
# Appareils identifiés (X-Device-Id) acceptés sans clé : firmware ESP32 déjà flashé.
# BP_STRICT_KEY=1 impose la clé à tous les appareils.
STRICT_KEY = os.environ.get("BP_STRICT_KEY") == "1"
DEVICE_ONLINE_S = 10                                       # appareil « en ligne » si vu il y a moins de 10 s
MQTT_HOST = os.environ.get("MQTT_HOST", "")                # vide = MQTT désactivé (Wi-Fi HTTP par défaut)
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
TOPIC_PREFIX = os.environ.get("TOPIC_PREFIX", "esilv-hack-2026/equipe-XX")

repo = make_repo()
DEVICES = {}  # identifiant appareil -> dernier contact (état volatil, hors graphe)

ROLE_HOME = {"garagiste": "garage_home", "proprietaire": "owner_home", "centre_tri": "tri_home",
             "transporteur": "transport_home"}
ROLE_BATTERY = {"garagiste": "garage_battery", "proprietaire": "owner_battery",
                "centre_tri": "tri_battery", "transporteur": "transport_battery"}
ROLE_LABEL = {"garagiste": "Garagiste", "proprietaire": "Propriétaire du passeport",
              "centre_tri": "Centre de tri", "transporteur": "Transporteur"}
EVENT_LABEL = {"MANUFACTURED": "Fabrication", "PUT_ON_MARKET": "Mise sur le marché",
               "MAINTENANCE": "Maintenance", "FAULT_REPORTED": "Hors d'usage signalé",
               "STATUS_CHANGED": "Statut modifié", "TRANSFER_ORDERED": "Transfert ordonné",
               "TRANSFER_SCHEDULED": "Collecte planifiée", "TRANSFER_CANCELLED": "Transfert annulé",
               "PICKED_UP": "Enlèvement par le transporteur", "RECEPTION_REFUSED": "Réception refusée",
               "REQUEST_REJECTED": "Demande refusée", "RECEIVED": "Réception centre de tri",
               "DECISION_RECORDED": "Décision enregistrée", "BMS_ALERT": "Alerte BMS"}
PICKUP_SLOTS = ["8h-12h", "12h-14h", "14h-18h"]


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
        # ?v=<date de modification> : le navigateur recharge le fichier dès qu'il change
        path = os.path.join(ROOT, "static", params["filename"])
        try:
            return f"/static/{params['filename']}?v={int(os.path.getmtime(path))}"
        except OSError:
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
                             demo_battery=DEMO_BATTERY, transfer_states=logistics.STATES,
                             step_labels=logistics.STEP_LABELS)
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
    pending = unread = 0
    if user and user["role"] == "proprietaire":
        pending = sum(1 for n in repo.list_notifications(user["operator_uid"]) if n["state"] == "PENDING")
    if user:
        unread = repo.unread_count(user["actor_uid"])
    ctx.update(request=request, user=user, pending_count=pending, unread_count=unread, backend=repo.backend,
               base_url=config.BASE_URL, flashes=request.session.pop("_flashes", []))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def load_passport(battery_id):
    p = repo.get_passport(telemetry.normalize_id(battery_id))
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
    """Accepte une URL de QR code (.../b/BAT-DOC-001 ou ...?battery=BAT-DOC-001) ou un identifiant brut."""
    code = (code or "").strip()
    if not code:
        return None
    if "://" in code:
        u = urlparse(code)
        if "battery" in parse_qs(u.query):
            return telemetry.normalize_id(parse_qs(u.query)["battery"][0])
        parts = [p for p in u.path.split("/") if p]
        return telemetry.normalize_id(parts[-1]) if parts else None
    return telemetry.normalize_id(code)


@app.get("/b/{battery_id}", name="battery_entry")
def battery_entry(request: Request, battery_id: str):
    """Cible des QR codes : vue métier si connecté, sinon passeport public (Annexe XIII)."""
    user = current_user(request)
    battery_id = telemetry.normalize_id(battery_id)
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
        flash(request, "Identifiant de batterie non reconnu. Essayez BAT-DOC-001.", "error")
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
                  fault_types=workflow.FAULT_TYPES, live=live_payload(battery_id),
                  centers=logistics.annotate(repo.list_actors("centre_tri")),
                  today=date.today().isoformat(), slots=PICKUP_SLOTS)


@app.post("/garage/b/{battery_id}/report", name="garage_report")
async def garage_report(request: Request, battery_id: str):
    user = require(request, "garagiste")
    form = await request.form()
    try:
        workflow.request_waste(repo, battery_id, user, form.get("fault_type", ""), form.get("comment", ""),
                               form.get("destination", ""),
                               auto_logistics=bool(form.get("auto_logistics")),
                               pickup_date=form.get("pickup_date", ""),
                               pickup_slot=form.get("pickup_slot", ""))
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
                  batteries=repo.list_batteries(), centers=logistics.annotate(repo.list_actors("centre_tri")),
                  transfers=[t for t in repo.list_transfers()
                             if t["state"] not in ("RECEIVED", "CANCELLED")])


@app.get("/owner/b/{battery_id}", name="owner_battery")
def owner_battery(request: Request, battery_id: str):
    require(request, "proprietaire")
    p = load_passport(battery_id)
    return render(request, "owner_battery.html", p=p, history=repo.get_history(battery_id),
                  centers=logistics.annotate(repo.list_actors("centre_tri")), live=live_payload(battery_id))


@app.post("/owner/requests/{notif_uid}/approve", name="owner_approve")
async def owner_approve(request: Request, notif_uid: str):
    user = require(request, "proprietaire")
    form = await request.form()
    try:
        n = repo.get_notification(notif_uid)
        if n is None:
            raise WorkflowError("Demande introuvable.")
        order_uid = workflow.approve_request(repo, notif_uid, user, form.get("destination", ""),
                                             form.get("comment", ""))
        if n.get("autoLogistics"):
            carrier = workflow.auto_schedule(repo, n, order_uid, user)
            if carrier:
                flash(request, f"Statut passé à « Waste », ordre {order_uid} créé et collecte planifiée "
                               f"automatiquement avec {carrier['name']}.")
            else:
                flash(request, "Statut passé à « Waste » et ordre créé. Aucun transporteur éligible pour "
                               "la planification automatique : planifiez la collecte.", "error")
        else:
            flash(request, f"Statut passé à « Waste » et ordre {order_uid} créé : planifiez la collecte.")
            return RedirectResponse(url_for("transfer_detail", order_uid=order_uid), status_code=303)
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
                  history=repo.get_history(battery_id), reception_checks=logistics.RECEPTION_CHECKS)


@app.post("/tri/b/{battery_id}/receive", name="tri_receive")
async def tri_receive(request: Request, battery_id: str):
    user = require(request, "centre_tri")
    form = await request.form()
    try:
        receipt = workflow.confirm_reception(
            repo, battery_id, user, seal=form.get("seal", ""), weight=form.get("weight"),
            checks={k: form.get(f"check_{k}") for k in logistics.RECEPTION_CHECKS},
            comment=form.get("comment", ""))
        flash(request, f"Réception enregistrée dans le Battery Passport. Preuve de dépôt : {receipt}.")
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(url_for("tri_battery", battery_id=battery_id), status_code=303)


@app.post("/tri/b/{battery_id}/refuse", name="tri_refuse")
async def tri_refuse(request: Request, battery_id: str):
    user = require(request, "centre_tri")
    form = await request.form()
    try:
        logistics.refuse(repo, battery_id, user, form.get("reason", ""))
        flash(request, "Réception refusée : le propriétaire et le transporteur sont prévenus.")
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(url_for("tri_battery", battery_id=battery_id), status_code=303)


# --- Défi 2 : transporteur, ordres de transfert, documents, messagerie ---------------------
@app.get("/transport", name="transport_home")
def transport_home(request: Request):
    user = require(request, "transporteur")
    missions = repo.list_transfers(carrier_uid=user["actor_uid"])
    return render(request, "transport_home.html", batteries=repo.list_batteries(),
                  active=[t for t in missions if t["state"] in ("SCHEDULED", "PICKED_UP")],
                  done=[t for t in missions if t["state"] not in ("SCHEDULED", "PICKED_UP")])


@app.get("/transport/b/{battery_id}", name="transport_battery")
def transport_battery(request: Request, battery_id: str):
    """Scan du QR code par le transporteur : ouvre sa mission en cours pour cette batterie."""
    user = require(request, "transporteur")
    for t in repo.list_transfers(carrier_uid=user["actor_uid"]):
        if t["batteryId"] == battery_id and t["state"] in ("SCHEDULED", "PICKED_UP"):
            return RedirectResponse(url_for("transfer_detail", order_uid=t["uid"]), status_code=303)
    flash(request, f"Aucune mission en cours pour {battery_id}.", "error")
    return RedirectResponse(url_for("transport_home"), status_code=303)


def load_transfer(user, order_uid):
    t = repo.get_transfer(order_uid)
    if t is None or not logistics.can_view(user, t):
        raise StarletteHTTPException(404)
    return t


@app.get("/transfers/{order_uid}", name="transfer_detail")
def transfer_detail(request: Request, order_uid: str):
    user = require(request)
    t = load_transfer(user, order_uid)
    damage = t.get("damageClass", "standard")
    return render(request, "transfer.html", t=t, doc=logistics.transfer_document(repo, order_uid),
                  p=repo.get_passport(t["batteryId"]),
                  carriers=logistics.annotate(repo.list_actors("transporteur"), damage, t.get("pickupDate")),
                  centers=logistics.annotate(repo.list_actors("centre_tri"), damage),
                  pickup_checks=logistics.PICKUP_CHECKS, adr=logistics.ADR_CLASSES[damage],
                  today=date.today().isoformat(), slots=PICKUP_SLOTS)


async def _transfer_action(request, order_uid, fn, success):
    form = await request.form()
    try:
        fn(form)
        flash(request, success)
    except WorkflowError as e:
        flash(request, str(e), "error")
    return RedirectResponse(url_for("transfer_detail", order_uid=order_uid), status_code=303)


@app.post("/transfers/{order_uid}/schedule", name="transfer_schedule")
async def transfer_schedule(request: Request, order_uid: str):
    user = require(request, "proprietaire")
    return await _transfer_action(request, order_uid, lambda f: logistics.schedule(
        repo, order_uid, user, f.get("carrier"), f.get("pickup_date"), f.get("slot", ""),
        f.get("instructions", "")), "Transporteur affecté, les acteurs sont notifiés.")


@app.post("/transfers/{order_uid}/cancel", name="transfer_cancel")
async def transfer_cancel(request: Request, order_uid: str):
    user = require(request, "proprietaire")
    return await _transfer_action(request, order_uid, lambda f: logistics.cancel(
        repo, order_uid, user, f.get("reason")), "Ordre de transfert annulé.")


@app.post("/transfers/{order_uid}/pickup", name="transfer_pickup")
async def transfer_pickup(request: Request, order_uid: str):
    user = require(request, "transporteur")
    return await _transfer_action(request, order_uid, lambda f: logistics.pickup(
        repo, order_uid, user, f.get("seal"), f.get("weight"), f.get("handed_over_by"),
        {k: f.get(f"check_{k}") for k in logistics.PICKUP_CHECKS}),
        "Enlèvement enregistré : la batterie est sous votre garde.")


@app.post("/owner/b/{battery_id}/new-order", name="owner_new_order")
async def owner_new_order(request: Request, battery_id: str):
    user = require(request, "proprietaire")
    form = await request.form()
    try:
        uid = logistics.new_order(repo, battery_id, user, form.get("destination"), form.get("comment", ""))
        flash(request, "Nouvel ordre de transfert créé.")
        return RedirectResponse(url_for("transfer_detail", order_uid=uid), status_code=303)
    except WorkflowError as e:
        flash(request, str(e), "error")
        return RedirectResponse(url_for("owner_battery", battery_id=battery_id), status_code=303)


def qr_svg(text):
    """QR code en SVG généré côté serveur : les documents imprimés marchent sans internet."""
    try:
        import qrcode
        import qrcode.image.svg
        buf = io.BytesIO()
        qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=1).save(buf)
        svg = buf.getvalue().decode()
        return Markup(svg[svg.index("<svg"):])
    except Exception:  # noqa: BLE001 - le document reste lisible sans QR code
        return ""


@app.get("/transfers/{order_uid}/doc/{doc_type}", name="transfer_print")
def transfer_print(request: Request, order_uid: str, doc_type: str):
    """Documents imprimables (Imprimer, puis Enregistrer en PDF) : ordre, étiquette UN 3480, manifeste."""
    user = require(request)
    if doc_type not in ("ordre", "etiquette", "manifeste"):
        raise StarletteHTTPException(404)
    load_transfer(user, order_uid)
    doc = logistics.transfer_document(repo, order_uid)
    return templates.TemplateResponse(request, f"doc_{doc_type}.html",
                                      dict(doc=doc, qr=qr_svg(doc["battery"]["passportUrl"])))


@app.get("/api/transfers/{order_uid}", name="api_transfer")
def api_transfer(request: Request, order_uid: str):
    user = require(request)
    load_transfer(user, order_uid)
    return logistics.transfer_document(repo, order_uid)


@app.get("/messages", name="messages")
def messages(request: Request):
    user = require(request)
    msgs = repo.list_messages(user["actor_uid"])
    repo.mark_messages_read(user["actor_uid"])
    return render(request, "messages.html", messages=msgs)


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
    """Valide puis enregistre une trame. Toute trame invalide est rejetée en entier."""
    frame = telemetry.parse_frame(payload)
    battery_id = frame["batteryId"]
    p = repo.get_passport(battery_id)
    if p is None:
        raise telemetry.TelemetryError(f"Batterie {battery_id} inconnue.")
    known = {m["index"] for m in p["modules"]}
    unknown = sorted(rd["index"] for rd in frame["readings"] if rd["index"] not in known)
    if unknown:
        raise telemetry.TelemetryError(f"Module(s) inconnu(s) sur {battery_id} : {unknown}.")
    source = (payload.get("source") if isinstance(payload, dict) else None) or source
    raised = repo.record_telemetry(battery_id, frame["readings"], ts=frame["ts"], source=source,
                                   soh=frame["soh"], soc=frame["soc"])
    d = DEVICES.setdefault(device_id, dict(packets=0))
    d.update(lastSeen=time.time(), batteryId=battery_id, source=source, ip=ip, packets=d["packets"] + 1)
    return battery_id, raised


def device_authorized(request):
    """Clé machine (X-BMS-Key ou X-Device-Token). Un appareil identifié par X-Device-Id
    sans clé est accepté (firmware ESP32 déjà flashé), sauf en mode BP_STRICT_KEY=1."""
    key = request.headers.get("x-bms-key") or request.headers.get("x-device-token")
    if key:
        return key == DEVICE_TOKEN
    return bool(request.headers.get("x-device-id")) and not STRICT_KEY


@app.post("/api/telemetry", name="api_telemetry")
async def api_telemetry(request: Request):
    """Point d'entrée du BMS : une trame (objet JSON) ou un lot de trames (liste).
    Réponse 200 si tout est accepté, 207 si une partie du lot est rejetée, 400 sinon."""
    if not device_authorized(request):
        return JSONResponse({"ok": False, "error": "Clé machine absente ou invalide (en-tête X-BMS-Key)."}, 401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Corps JSON invalide."}, 400)
    try:
        frames = telemetry.parse_payload(payload)
    except telemetry.TelemetryError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)
    ip = request.client.host if request.client else None
    first = frames[0] if isinstance(frames[0], dict) else {}
    device_id = request.headers.get("x-device-id") or first.get("device") or ip or "inconnu"
    source = "ESP32" if "esp32" in device_id.lower() else "HTTP"
    accepted, alerts, errors = [], [], []
    for k, frame in enumerate(frames):
        try:
            battery_id, raised = ingest(frame, device_id=device_id, source=source, ip=ip)
            accepted.append(battery_id)
            alerts += raised
        except telemetry.TelemetryError as e:
            errors.append(dict(frame=k, error=str(e)))
    if not accepted:
        body = {"ok": False, "error": errors[0]["error"], "errors": errors}
        return JSONResponse(body, 400)
    body = {"ok": not errors, "accepted": len(accepted), "batteryId": accepted[0],
            "alerts": alerts, "errors": errors}
    return JSONResponse(body, 207 if errors else 200)


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
    unread = repo.unread_count(user["actor_uid"])
    if user["role"] != "proprietaire":
        return {"pending": 0, "unread": unread}
    return {"pending": sum(1 for n in repo.list_notifications(user["operator_uid"]) if n["state"] == "PENDING"),
            "unread": unread}


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
