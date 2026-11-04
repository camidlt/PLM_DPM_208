"""Battery Passport - PoC Hackathon ESILV x Capgemini Engineering.

Tronc commun : 3 interfaces par rôle autour d'une base graphe.
  - Garagiste (tablette)     : scan QR, consultation, signalement hors d'usage
  - Propriétaire (desktop)   : notifications, passage Original → Waste, ordre de transfert
  - Centre de tri (mobile)   : scan QR, vérification du statut Waste, accusé de réception

Défi 3 : aide à la décision du centre de tri (Reuse / Remanufacture / Repurpose / Recycle).

Lancement : python app.py   (voir README.md)
"""
from functools import wraps
from urllib.parse import parse_qs, urlparse

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)

from bp import config, make_repo, workflow
from bp.workflow import WorkflowError
from bp import decision

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
repo = make_repo()

ROLE_HOME = {"garagiste": "garage_home", "proprietaire": "owner_home", "centre_tri": "tri_home"}
ROLE_BATTERY = {"garagiste": "garage_battery", "proprietaire": "owner_battery",
                "centre_tri": "tri_battery"}
ROLE_LABEL = {"garagiste": "Garagiste", "proprietaire": "Propriétaire Battery Passport",
              "centre_tri": "Centre de tri"}
EVENT_LABEL = {"MANUFACTURED": "Fabrication", "PUT_ON_MARKET": "Mise sur le marché",
               "MAINTENANCE": "Maintenance", "FAULT_REPORTED": "Hors d'usage signalé",
               "STATUS_CHANGED": "Statut modifié", "TRANSFER_ORDERED": "Transfert ordonné",
               "REQUEST_REJECTED": "Demande refusée", "RECEIVED": "Réception centre de tri",
               "DECISION_RECORDED": "Décision enregistrée"}


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
                flash(f"Accès réservé au rôle « {ROLE_LABEL[role]} ».", "error")
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
    return dict(user=user, role_label=ROLE_LABEL, event_label=EVENT_LABEL,
                pending_count=pending, backend=repo.backend, base_url=config.BASE_URL,
                module_alerts=workflow.module_alerts, option_fr=decision.OPTION_FR)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        account = config.ACCOUNTS.get(username)
        if account and request.form.get("password") == account["password"]:
            session["user"] = username
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
    """Cible des QR codes :
       - Utilisateur connecté : orienté vers sa vue métier autorisée (intérêt légitime).
       - Grand public non connecté : orienté vers la vue publique restreinte (Règle réglementaire).
    """
    user = current_user()
    if user:
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


# --- Garagiste ---------------------------------------------------------------------
@app.route("/garage")
@login_required("garagiste")
def garage_home(user):
    return render_template("garage_home.html", batteries=repo.list_batteries())


@app.route("/garage/b/<battery_id>")
@login_required("garagiste")
def garage_battery(user, battery_id):
    p = load_passport(battery_id)
    return render_template("garage_battery.html", p=p, history=repo.get_history(battery_id),
                           fault_types=workflow.FAULT_TYPES)


@app.route("/garage/b/<battery_id>/report", methods=["POST"])
@login_required("garagiste")
def garage_report(user, battery_id):
    try:
        workflow.request_waste(repo, battery_id, user, request.form.get("fault_type", ""),
                               request.form.get("comment", ""))
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
                           centers=repo.list_actors("centre_tri"))


@app.route("/owner/b/<battery_id>")
@login_required("proprietaire")
def owner_battery(user, battery_id):
    p = load_passport(battery_id)
    return render_template("owner_battery.html", p=p, history=repo.get_history(battery_id),
                           centers=repo.list_actors("centre_tri"))


@app.route("/owner/requests/<notif_uid>/approve", methods=["POST"])
@login_required("proprietaire")
def owner_approve(user, notif_uid):
    try:
        workflow.approve_request(repo, notif_uid, user, request.form.get("destination", ""),
                                 request.form.get("comment", ""))
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


def _decision_context(p, user):
    """Prépare le contexte pour le panneau de décision (défi 3)."""
    battery_id = p["battery"]["batteryId"]
    loc = p.get("location") or {}
    ready = (p["battery"]["status"] == "Waste" and loc.get("uid") == user["actor_uid"])
    policy = repo.get_center_policy(user["actor_uid"])
    tab = request.args.get("tab", "classement")
    demands = repo.list_demands()
    result = None
    if ready:
        result = decision.recommend(p, demands, params=policy)
    return dict(ready=ready, result=result, tab=tab, demands=demands, policy=policy,
                criteria=decision.CRITERIA, weights=decision.DEFAULT_WEIGHTS,
                decisions=repo.get_decisions(battery_id))


@app.route("/tri/b/<battery_id>")
@login_required("centre_tri")
def tri_battery(user, battery_id):
    p = load_passport(battery_id)
    d = _decision_context(p, user)
    return render_template("tri_battery.html", p=p, d=d, history=repo.get_history(battery_id))


@app.route("/tri/b/<battery_id>/receive", methods=["POST"])
@login_required("centre_tri")
def tri_receive(user, battery_id):
    try:
        workflow.confirm_reception(repo, battery_id, user)
        flash("Réception enregistrée dans le Battery Passport.", "success")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("tri_battery", battery_id=battery_id))


@app.route("/tri/b/<battery_id>/decision", methods=["POST"])
@login_required("centre_tri")
def tri_decision(user, battery_id):
    """Enregistre la décision du centre de tri (défi 3)."""
    try:
        p = load_passport(battery_id)
        policy = repo.get_center_policy(user["actor_uid"])
        demands = repo.list_demands()
        result = decision.recommend(p, demands, params=policy)
        chosen = request.form.get("chosen", "")
        comment = request.form.get("comment", "")
        opts = {o["option"]: o for o in result["options"]}
        if chosen not in opts:
            flash("Option inconnue.", "error")
            return redirect(url_for("tri_battery", battery_id=battery_id))
        if not opts[chosen]["feasible"]:
            flash(f"{chosen} est exclu : " + " ; ".join(opts[chosen]["excluded_because"]), "error")
            return redirect(url_for("tri_battery", battery_id=battery_id))
        if chosen != result["recommendation"] and not (comment or "").strip():
            flash("Choix différent de la recommandation : commentaire obligatoire.", "error")
            return redirect(url_for("tri_battery", battery_id=battery_id))
        loc = p.get("location") or {}
        if p["battery"]["status"] != "Waste":
            flash("Décision impossible : le statut n'est pas « Waste ».", "error")
            return redirect(url_for("tri_battery", battery_id=battery_id))
        if loc.get("uid") != user["actor_uid"]:
            flash("Décision impossible : la batterie n'est pas réceptionnée par votre centre.", "error")
            return redirect(url_for("tri_battery", battery_id=battery_id))
        repo.record_decision(battery_id, user["actor_uid"], chosen, comment, result)
        flash(f"Décision « {chosen} » enregistrée dans le Battery Passport.", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("tri_battery", battery_id=battery_id))


@app.route("/tri/priorities", methods=["POST"])
@login_required("centre_tri")
def tri_priorities(user):
    policy = repo.get_center_policy(user["actor_uid"])
    toggle_key = request.form.get("toggle")
    if toggle_key in policy:
        policy[toggle_key] = not policy[toggle_key]
        repo.set_center_policy(user["actor_uid"], policy["use_market"], policy["use_hierarchy"])
        flash("Priorités du centre de tri mises à jour.", "success")
    back = request.form.get("back") or url_for("tri_home")
    return redirect(back)


@app.route("/tri/market")
@login_required("centre_tri")
def tri_market(user):
    back = request.args.get("back", "")
    return render_template("tri_market.html", demands=repo.list_demands(),
                           option_fr=decision.OPTION_FR, back=back)


@app.route("/tri/market/<demand_uid>/toggle", methods=["POST"])
@login_required("centre_tri")
def tri_market_toggle(user, demand_uid):
    demands = {d["uid"]: d for d in repo.list_demands()}
    if demand_uid not in demands:
        flash("Demande inconnue.", "error")
    else:
        new_state = not demands[demand_uid].get("active")
        repo.set_demand_active(demand_uid, new_state)
        flash(f"Demande « {demands[demand_uid]['title']} » {'activée' if new_state else 'désactivée'}.", "success")
    back = request.form.get("back", "")
    if back and back.startswith("/tri/"):
        return redirect(back)
    return redirect(url_for("tri_market"))


@app.route("/tri/market/add", methods=["POST"])
@login_required("centre_tri")
def tri_market_add(user):
    title = request.form.get("title", "").strip()
    option = request.form.get("option", "Repurpose")
    partner = request.form.get("partner", "").strip() or "Partenaire industriel"
    urgency = request.form.get("urgency", "normale")
    location = request.form.get("location", "").strip() or "France"
    try:
        min_soce = int(request.form.get("min_soce", 60))
    except (ValueError, TypeError):
        min_soce = 60
    try:
        quantity = int(request.form.get("quantity", 10))
    except (ValueError, TypeError):
        quantity = 10
    chems = request.form.getlist("chemistries")
    if not chems:
        chems = ["NMC 811", "LFP"]

    if not title:
        flash("Le titre de la demande est obligatoire.", "error")
    else:
        repo.add_demand(center_uid=user["actor_uid"], title=title, option=option,
                        partner=partner, chemistries=chems, min_soce=min_soce,
                        urgency=urgency, quantity=quantity, location=location)
        flash(f"Demande « {title} » ajoutée au catalogue du marché.", "success")
    back = request.form.get("back", "")
    if back and back.startswith("/tri/"):
        return redirect(back)
    return redirect(url_for("tri_market"))


@app.route("/tri/market/<demand_uid>/delete", methods=["POST"])
@login_required("centre_tri")
def tri_market_delete(user, demand_uid):
    demands = {d["uid"]: d for d in repo.list_demands()}
    if demand_uid in demands:
        title = demands[demand_uid]["title"]
        repo.delete_demand(demand_uid)
        flash(f"Demande « {title} » retirée du catalogue du marché.", "success")
    else:
        flash("Demande introuvable.", "error")
    back = request.form.get("back", "")
    if back and back.startswith("/tri/"):
        return redirect(back)
    return redirect(url_for("tri_market"))


# --- API JSON (pour les défis 1 et 3, et les notifications) --------------------------
@app.route("/api/battery/<battery_id>")
@login_required()
def api_battery(user, battery_id):
    p = load_passport(battery_id)
    return jsonify(passport=p, history=repo.get_history(battery_id),
                   module_alerts=workflow.module_alerts(p))


@app.route("/api/battery/<battery_id>/recommendation")
@login_required()
def api_recommendation(user, battery_id):
    """API JSON de recommandation (défi 3)."""
    p = load_passport(battery_id)
    center_uid = request.args.get("center_uid") or user.get("actor_uid")
    policy = repo.get_center_policy(center_uid) if center_uid else {}
    demands = repo.list_demands()
    result = decision.recommend(p, demands, params=policy)
    return jsonify(result)


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
