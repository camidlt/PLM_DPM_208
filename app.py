"""Battery Passport - PoC Hackathon ESILV x Capgemini Engineering.

Tronc commun : 3 interfaces par rôle autour d'une base graphe.
  - Garagiste (tablette)     : scan QR, consultation, signalement hors d'usage
  - Propriétaire (desktop)   : notifications, passage Original → Waste, ordre de transfert
  - Centre de tri (mobile)   : scan QR, vérification du statut Waste, accusé de réception

Lancement : python app.py   (voir README.md)
"""
from datetime import date
from functools import wraps
from urllib.parse import parse_qs, urlparse

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)

from bp import config, decision, logistics, make_repo, telemetry, workflow
from bp.workflow import WorkflowError

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
repo = make_repo()

ROLE_HOME = {"garagiste": "garage_home", "proprietaire": "owner_home", "centre_tri": "tri_home",
             "transporteur": "transport_home", "admin": "admin_home"}
ROLE_BATTERY = {"garagiste": "garage_battery", "proprietaire": "owner_battery",
                "centre_tri": "tri_battery", "transporteur": "transport_battery", "admin": "admin_home"}
ROLE_LABEL = {"garagiste": "Garagiste", "proprietaire": "Propriétaire Battery Passport",
              "centre_tri": "Centre de tri", "transporteur": "Transporteur", "admin": "Administrateur"}
OPTION_LABELS = {
    "Reuse": "Réutilisation",
    "Remanufacture": "Reconditionnement",
    "Repurpose": "Seconde vie",
    "Recycle": "Recyclage",
}
STATUS_LABELS = {
    "Original": "Origine (Original)",
    "Waste": "Hors d'usage (Waste)",
    "Recycled": "Recyclée (Recycled)",
    "Repurposed": "Seconde vie (Repurposed)",
    "SecondLife": "Seconde vie",
    "Remanufactured": "Reconditionnée (Remanufactured)",
    "Reused": "Réutilisée (Reused)",
    "PENDING": "En attente",
    "APPROVED": "Approuvée",
    "REJECTED": "Refusée",
    "ORDERED": "En transit",
    "RECEIVED": "Réceptionné",
}
EVENT_LABEL = {"MANUFACTURED": "Fabrication", "PUT_ON_MARKET": "Mise sur le marché",
               "MAINTENANCE": "Maintenance", "FAULT_REPORTED": "Hors d'usage signalé",
               "STATUS_CHANGED": "Statut modifié", "TRANSFER_ORDERED": "Transfert ordonné",
               "REQUEST_REJECTED": "Demande refusée", "RECEIVED": "Réception centre de tri",
               "BMS_ALERT": "Alerte BMS", "ORIENTATION_DECIDED": "Orientation de fin de vie",
               "TRANSFER_SCHEDULED": "Enlèvement planifié", "PICKED_UP": "Enlèvement au garage",
               "RECEPTION_REFUSED": "Réception refusée", "TRANSFER_CANCELLED": "Transfert annulé"}


# --- Authentification ------------------------------------------------------------
def current_user():
    username = session.get("user")
    if username not in config.ACCOUNTS:
        return None
    return {"username": username, **config.ACCOUNTS[username]}


def login_required(role=None):
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("login", next=request.full_path))
            if role and user["role"] != role:
                if session.get("is_admin"):
                    for u_name, acc in config.ACCOUNTS.items():
                        if acc["role"] == role:
                            session["user"] = u_name
                            user = current_user()
                            break
                    return view(user, *args, **kwargs)
                flash(f"Accès réservé au rôle « {ROLE_LABEL.get(role, role)} ».", "error")
                return redirect(url_for(ROLE_HOME[user["role"]]))
            return view(user, *args, **kwargs)
        return wrapper
    return deco


@app.context_processor
def inject_globals():
    user = current_user()
    pending = 0
    if user and user["role"] == "proprietaire":
        pending = sum(1 for n in repo.list_notifications(user["operator_uid"])
                      if n["state"] == "PENDING")
    unread = 0
    if user:
        unread = sum(1 for m in repo.list_messages(user["actor_uid"]) if not m.get("read"))
    return dict(user=user, role_label=ROLE_LABEL, event_label=EVENT_LABEL,
                option_label=OPTION_LABELS, status_label=STATUS_LABELS,
                is_admin=session.get("is_admin", False), all_accounts=config.ACCOUNTS,
                pending_count=pending, backend=repo.backend, base_url=config.BASE_URL,
                module_alerts=workflow.module_alerts,
                # défi 2
                unread_count=unread, transfer_states=logistics.STATES, role_home=ROLE_HOME,
                agreement_problems=logistics.agreement_problems, damage_class=logistics.damage_class)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        account = config.ACCOUNTS.get(username)
        if account and request.form.get("password") == account["password"]:
            session["user"] = username
            if username == "admin":
                session["is_admin"] = True
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for(ROLE_HOME[account["role"]]))
        flash("Identifiant ou mot de passe incorrect.", "error")
    return render_template("login.html", accounts=config.ACCOUNTS)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def index(user):
    return redirect(url_for(ROLE_HOME[user["role"]]))


# --- QR code / scan --------------------------------------------------------------
def parse_battery_code(code):
    """Accepte une URL de QR code (…/b/BAT-001 ou …?battery=BAT-001) ou un ID brut."""
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


@app.route("/b/<battery_id>")
def battery_entry(battery_id):
    """Cible des QR codes : renvoie chaque rôle vers sa propre vue ou la vue publique."""
    user = current_user()
    if user and user.get("role") in ROLE_BATTERY:
        return redirect(url_for(ROLE_BATTERY[user["role"]], battery_id=battery_id))
    return redirect(url_for("public_battery", battery_id=battery_id))


@app.route("/public/b/<battery_id>")
def public_battery(battery_id):
    """Vue publique accessible à tous sans authentification (Annexe XIII)."""
    p = load_passport(battery_id)
    return render_template("public_battery.html", p=p)


@app.route("/scan")
@login_required()
def scan(user):
    battery_id = parse_battery_code(request.args.get("code"))
    if not battery_id or repo.get_passport(battery_id) is None:
        flash("QR code ou identifiant de batterie non reconnu.", "error")
        return redirect(url_for(ROLE_HOME[user["role"]]))
    return redirect(url_for(ROLE_BATTERY[user["role"]], battery_id=battery_id))


def load_passport(battery_id):
    p = repo.get_passport(battery_id)
    if p is None:
        abort(404)
    return p


def challenge_context(p, history):
    """Données des défis 1 (télémétrie) et 3 (aide à la décision) pour les écrans batterie."""
    battery_id = p["battery"]["batteryId"]
    readings = repo.get_telemetry(battery_id)
    return dict(readings=readings,
                chart=telemetry.resistance_chart(readings, p["modules"]),
                reco=decision.recommend(p, history, readings),
                orientation=repo.get_orientation(battery_id),
                decision_options=decision.OPTIONS,
                recovery_targets=decision.RECOVERY_TARGETS)


# --- Garagiste ---------------------------------------------------------------------
@app.route("/garage")
@login_required("garagiste")
def garage_home(user):
    return render_template("garage_home.html", batteries=repo.list_batteries())


@app.route("/garage/b/<battery_id>")
@login_required("garagiste")
def garage_battery(user, battery_id):
    p = load_passport(battery_id)
    history = repo.get_history(battery_id)
    return render_template("garage_battery.html", p=p, history=history,
                           fault_types=workflow.FAULT_TYPES,
                           centers=repo.list_actors("centre_tri"),
                           today=date.today().isoformat(),
                           **challenge_context(p, history))


@app.route("/garage/b/<battery_id>/report", methods=["POST"])
@login_required("garagiste")
def garage_report(user, battery_id):
    try:
        workflow.request_waste(repo, battery_id, user, request.form.get("fault_type", ""),
                               request.form.get("comment", ""),
                               request.form.get("destination", ""),
                               auto_logistics=bool(request.form.get("auto_logistics")),
                               pickup_date=request.form.get("pickup_date", ""),
                               pickup_slot=request.form.get("pickup_slot", ""))
        flash("Demande envoyée au propriétaire du Battery Passport.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("garage_battery", battery_id=battery_id))


# --- Propriétaire ------------------------------------------------------------------
@app.route("/owner")
@login_required("proprietaire")
def owner_home(user):
    notifs = repo.list_notifications(user["operator_uid"])
    return render_template("owner_home.html",
                           pending=[n for n in notifs if n["state"] == "PENDING"],
                           processed=[n for n in notifs if n["state"] != "PENDING"],
                           batteries=repo.list_batteries(),
                           centers=repo.list_actors("centre_tri"),
                           transfers=repo.list_transfers())


@app.route("/owner/b/<battery_id>")
@login_required("proprietaire")
def owner_battery(user, battery_id):
    p = load_passport(battery_id)
    history = repo.get_history(battery_id)
    return render_template("owner_battery.html", p=p, history=history,
                           centers=repo.list_actors("centre_tri"), **challenge_context(p, history))


@app.route("/owner/requests/<notif_uid>/approve", methods=["POST"])
@login_required("proprietaire")
def owner_approve(user, notif_uid):
    try:
        n = repo.get_notification(notif_uid)
        if n is None:
            raise WorkflowError("Demande introuvable.")
        order_uid = workflow.approve_request(repo, notif_uid, user, "")
        if n.get("autoLogistics"):
            pickup_date = n.get("pickupDate") or date.today().isoformat()
            slot = n.get("pickupSlot") or "8h-12h"
            damage = logistics.damage_class(n.get("reason"))
            carriers = [c for c in repo.list_actors("transporteur")
                        if not logistics.agreement_problems(c, pickup_date, damage)]
            if carriers:
                carrier = sorted(carriers, key=lambda c: c["name"])[0]
                logistics.schedule(repo, order_uid, user, carrier["uid"], pickup_date, slot,
                                   "Planification automatique demandée par le garagiste.")
                flash("Statut passé à « Waste », ordre créé et collecte planifiée automatiquement.",
                      "success")
            else:
                flash("Statut passé à « Waste » et ordre créé. Aucun transporteur éligible pour "
                      "la planification automatique : planifiez manuellement.", "error")
        else:
            flash("Statut passé à « Waste » et ordre de transfert créé.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(request.form.get("back") or url_for("owner_home"))


@app.route("/owner/requests/<notif_uid>/reject", methods=["POST"])
@login_required("proprietaire")
def owner_reject(user, notif_uid):
    try:
        workflow.reject_request(repo, notif_uid, user, request.form.get("comment", ""))
        flash("Demande refusée, le garagiste en sera informé.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(request.form.get("back") or url_for("owner_home"))


# --- Centre de tri -----------------------------------------------------------------
@app.route("/tri")
@login_required("centre_tri")
def tri_home(user):
    return render_template("tri_home.html", transfers=repo.list_transfers_to(user["actor_uid"]),
                           batteries=repo.list_batteries())


@app.route("/tri/b/<battery_id>")
@login_required("centre_tri")
def tri_battery(user, battery_id):
    p = load_passport(battery_id)
    history = repo.get_history(battery_id)
    return render_template("tri_battery.html", p=p, history=history, **challenge_context(p, history))


@app.route("/tri/b/<battery_id>/receive", methods=["POST"])
@login_required("centre_tri")
def tri_receive(user, battery_id):
    f = request.form
    try:
        receipt = workflow.confirm_reception(
            repo, battery_id, user, seal=f.get("seal", ""), weight=f.get("weight"),
            checks={k: f.get(f"check_{k}") for k in logistics.RECEPTION_CHECKS},
            comment=f.get("comment", ""))
        flash(f"Réception enregistrée dans le Battery Passport. Preuve de dépôt : {receipt}.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("tri_battery", battery_id=battery_id))


@app.route("/tri/b/<battery_id>/orientation", methods=["POST"])
@login_required("centre_tri")
def tri_orientation(user, battery_id):
    """Défi 3 : le centre de tri enregistre l'orientation de fin de vie retenue."""
    p = load_passport(battery_id)
    history = repo.get_history(battery_id)
    reco = decision.recommend(p, history, repo.get_telemetry(battery_id))
    try:
        decision.record_orientation(repo, battery_id, user, request.form.get("choice", ""),
                                    request.form.get("comment", ""), reco)
        flash("Orientation enregistrée dans le Battery Passport.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("tri_battery", battery_id=battery_id) + "#decision")


# --- Défi 1 : réception des trames BMS ------------------------------------------------
@app.route("/api/telemetry", methods=["POST"])
def api_telemetry():
    """Trame BMS (objet JSON) ou lot de trames (liste). Authentification : en-tête X-BMS-Key."""
    if request.headers.get("X-BMS-Key") != config.BMS_API_KEY:
        return jsonify(error="Clé BMS absente ou invalide (en-tête X-BMS-Key)."), 401
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(error="Corps JSON attendu (Content-Type: application/json)."), 400
    frames = data if isinstance(data, list) else [data]
    results, errors = [], []
    for k, frame in enumerate(frames):
        try:
            results.append(telemetry.ingest(repo, frame))
        except WorkflowError as e:
            errors.append(dict(frame=k, error=str(e)))
    status = 201 if results and not errors else (207 if results else 400)
    return jsonify(accepted=len(results), results=results, errors=errors), status


@app.route("/api/telemetry/<battery_id>/latest")
def api_telemetry_latest(battery_id):
    """État mesuré actuel (pour la passerelle BMS), au format d'un relevé.
    Authentification : en-tête X-BMS-Key."""
    if request.headers.get("X-BMS-Key") != config.BMS_API_KEY:
        return jsonify(error="Clé BMS absente ou invalide (en-tête X-BMS-Key)."), 401
    p = repo.get_passport(battery_id.upper())
    if p is None:
        return jsonify(error=f"Batterie {battery_id} introuvable."), 404
    dp = p["dynamic_performance"]
    return jsonify(batteryId=p["battery"]["batteryId"], soh=dp.get("soh"), soc=dp.get("soc"),
                   at=max([m.get("measuredAt") or "" for m in p["modules"]] + [dp.get("measuredAt") or ""]),
                   moduleIndexes=[m["index"] for m in p["modules"]],
                   resistances=[m["internalResistance_mOhm"] for m in p["modules"]],
                   maxResistances=[m.get("maxInternalResistance_mOhm") for m in p["modules"]])


@app.route("/api/battery/<battery_id>/telemetry")
@login_required()
def api_battery_telemetry(user, battery_id):
    load_passport(battery_id)
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    return jsonify(batteryId=battery_id, readings=repo.get_telemetry(battery_id, limit))


@app.route("/api/battery/<battery_id>/decision")
@login_required()
def api_battery_decision(user, battery_id):
    """Défi 3 : recommandation calculée + orientation éventuellement déjà enregistrée."""
    p = load_passport(battery_id)
    history = repo.get_history(battery_id)
    return jsonify(batteryId=battery_id,
                   recommendation=decision.recommend(p, history, repo.get_telemetry(battery_id)),
                   orientation=repo.get_orientation(battery_id))


@app.route("/tri/b/<battery_id>/refuse", methods=["POST"])
@login_required("centre_tri")
def tri_refuse(user, battery_id):
    try:
        logistics.refuse(repo, battery_id, user, request.form.get("reason", ""))
        flash("Réception refusée : le propriétaire et le transporteur sont prévenus.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("tri_battery", battery_id=battery_id))


# --- Défi 2 : logistique du transfert ----------------------------------------------------
def load_transfer(user, order_uid):
    t = repo.get_transfer(order_uid)
    if t is None or not logistics.can_view(user, t):
        abort(404)
    return t


@app.route("/transfers/<order_uid>")
@login_required()
def transfer_detail(user, order_uid):
    t = load_transfer(user, order_uid)
    doc = logistics.transfer_document(repo, order_uid)
    damage = t.get("damageClass", "standard")
    carriers = logistics.annotate(repo.list_actors("transporteur"), damage, t.get("pickupDate"))
    centers = logistics.annotate(repo.list_actors("centre_tri"), damage)
    return render_template("transfer.html", t=t, doc=doc, carriers=carriers, centers=centers,
                           p=repo.get_passport(t["batteryId"]), pickup_checks=logistics.PICKUP_CHECKS,
                           adr=logistics.ADR_CLASSES[damage], today=date.today().isoformat())


def _transfer_action(fn, success, order_uid):
    try:
        fn()
        flash(success, "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("transfer_detail", order_uid=order_uid))


@app.route("/transfers/<order_uid>/schedule", methods=["POST"])
@login_required("proprietaire")
def transfer_schedule(user, order_uid):
    f = request.form
    return _transfer_action(lambda: logistics.schedule(
        repo, order_uid, user, f.get("carrier"), f.get("pickup_date"), f.get("slot", ""),
        f.get("instructions", "")), "Transporteur affecté, les acteurs sont notifiés.", order_uid)


@app.route("/transfers/<order_uid>/cancel", methods=["POST"])
@login_required("proprietaire")
def transfer_cancel(user, order_uid):
    return _transfer_action(lambda: logistics.cancel(repo, order_uid, user, request.form.get("reason")),
                            "Ordre de transfert annulé.", order_uid)


@app.route("/transfers/<order_uid>/pickup", methods=["POST"])
@login_required("transporteur")
def transfer_pickup(user, order_uid):
    f = request.form
    return _transfer_action(lambda: logistics.pickup(
        repo, order_uid, user, f.get("seal"), f.get("weight"), f.get("handed_over_by"),
        {k: f.get(f"check_{k}") for k in logistics.PICKUP_CHECKS}),
        "Enlèvement enregistré : la batterie est sous votre garde.", order_uid)


@app.route("/owner/b/<battery_id>/new-order", methods=["POST"])
@login_required("proprietaire")
def owner_new_order(user, battery_id):
    try:
        uid = logistics.new_order(repo, battery_id, user, request.form.get("destination"),
                                  request.form.get("comment", ""))
        flash("Nouvel ordre de transfert créé.", "success")
        return redirect(url_for("transfer_detail", order_uid=uid))
    except WorkflowError as e:
        flash(str(e), "error")
        return redirect(url_for("owner_battery", battery_id=battery_id))


def qr_svg(text):
    """QR code en SVG généré côté serveur : les documents imprimés marchent sans internet."""
    try:
        import io
        import qrcode
        import qrcode.image.svg
        buf = io.BytesIO()
        qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=1).save(buf)
        svg = buf.getvalue().decode()
        return svg[svg.index("<svg"):]
    except Exception:  # noqa: BLE001 - à défaut, la librairie JS du navigateur prend le relais
        return ""


@app.route("/transfers/<order_uid>/<doc_type>")
@login_required()
def transfer_print(user, order_uid, doc_type):
    """Documents imprimables (Imprimer → Enregistrer en PDF) : ordre, étiquette, manifeste."""
    if doc_type not in ("ordre", "etiquette", "manifeste"):
        abort(404)
    load_transfer(user, order_uid)
    doc = logistics.transfer_document(repo, order_uid)
    return render_template(f"doc_{doc_type}.html", doc=doc, qr=qr_svg(doc["battery"]["passportUrl"]))


@app.route("/api/transfers/<order_uid>")
@login_required()
def api_transfer(user, order_uid):
    load_transfer(user, order_uid)
    resp = jsonify(logistics.transfer_document(repo, order_uid))
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = f'attachment; filename="manifeste-{order_uid}.json"'
    return resp


@app.route("/transport")
@login_required("transporteur")
def transport_home(user):
    missions = repo.list_transfers(carrier_uid=user["actor_uid"])
    return render_template("transport_home.html", batteries=repo.list_batteries(),
                           active=[t for t in missions if t["state"] in ("SCHEDULED", "PICKED_UP")],
                           done=[t for t in missions if t["state"] not in ("SCHEDULED", "PICKED_UP")])


@app.route("/transport/b/<battery_id>")
@login_required("transporteur")
def transport_battery(user, battery_id):
    """Scan du QR code par le transporteur : ouvre sa mission en cours pour cette batterie."""
    for t in repo.list_transfers(carrier_uid=user["actor_uid"]):
        if t["batteryId"] == battery_id and t["state"] in ("SCHEDULED", "PICKED_UP"):
            return redirect(url_for("transfer_detail", order_uid=t["uid"]))
    flash(f"Aucune mission en cours pour {battery_id}.", "error")
    return redirect(url_for("transport_home"))


@app.route("/messages")
@login_required()
def messages(user):
    msgs = repo.list_messages(user["actor_uid"])
    repo.mark_messages_read(user["actor_uid"])
    return render_template("messages.html", messages=msgs)


# --- API JSON (pour les défis 1 et 3, et les notifications) --------------------------
@app.route("/api/battery/<battery_id>")
@login_required()
def api_battery(user, battery_id):
    p = load_passport(battery_id)
    return jsonify(passport=p, history=repo.get_history(battery_id),
                   module_alerts=workflow.module_alerts(p))


@app.route("/api/notifications/count")
@login_required()
def api_notif_count(user):
    if user["role"] != "proprietaire":
        return jsonify(pending=0)
    return jsonify(pending=sum(1 for n in repo.list_notifications(user["operator_uid"])
                               if n["state"] == "PENDING"))


@app.route("/admin/reset", methods=["POST"])
@login_required()
def admin_reset(user):
    repo.reset()
    flash("Données de démo réinitialisées.", "success")
    if session.get("is_admin") or user["role"] == "admin":
        return redirect(url_for("admin_home"))
    return redirect(url_for(ROLE_HOME[user["role"]]))


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", message="Batterie ou page introuvable."), 404


if __name__ == "__main__":
    import os
    print(f" * Base de données : {repo.backend}")
    print(f" * QR codes pointent vers : {config.BASE_URL}")
    app.run(host=os.environ.get("BP_HOST", "0.0.0.0"), port=int(os.environ.get("BP_PORT", 5000)),
            debug=os.environ.get("BP_DEBUG") == "1")


# --- Administration & commutation de compte --------------------------------------
@app.route("/admin")
def admin_home():
    if not session.get("is_admin"):
        user = current_user()
        if not user or user["role"] != "admin":
            flash("Accès réservé à l'administrateur.", "error")
            return redirect(url_for("login", next=request.full_path))
    session["user"] = "admin"
    user = current_user()
    batteries = repo.list_batteries()
    notifications = repo.list_notifications("EO-FLUX")
    return render_template("admin_home.html",
                           user=user,
                           batteries=batteries,
                           notifications=notifications,
                           accounts=config.ACCOUNTS)


@app.route("/admin/switch/<target_user>")
def admin_switch(target_user):
    if not session.get("is_admin"):
        flash("Action réservée aux administrateurs.", "error")
        return redirect(url_for("login"))
    if target_user not in config.ACCOUNTS:
        flash("Compte cible inconnu.", "error")
        return redirect(url_for("admin_home"))
    session["user"] = target_user
    nxt = request.args.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    target_acc = config.ACCOUNTS[target_user]
    flash(f"Compte actif : {target_acc['display']} ({ROLE_LABEL.get(target_acc['role'], target_acc['role'])}).", "info")
    return redirect(url_for(ROLE_HOME[target_acc["role"]]))



