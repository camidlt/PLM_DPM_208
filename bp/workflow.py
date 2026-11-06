"""Règles métier du workflow : diagnostic → mise à jour statut → transfert → réception.

Les règles sont ici, indépendantes de la base : le mode mémoire et le mode
Neo4j appliquent exactement les mêmes contrôles.
"""

STATUSES = ["Original", "Reused", "Remanufactured", "Repurposed", "Waste"]

# Transitions de statut autorisées (cycle de vie du passeport).
# Le tronc commun n'utilise que Original → Waste ; les autres servent au défi 3.
ALLOWED_TRANSITIONS = {
    "Original": {"Waste", "Reused", "Remanufactured", "Repurposed"},
    "Reused": {"Waste", "Remanufactured", "Repurposed"},
    "Remanufactured": {"Waste", "Repurposed"},
    "Repurposed": {"Waste"},
    "Waste": set(),
}

FAULT_TYPES = [
    "Résistance interne anormale d'un module",
    "Perte de capacité importante (SOH bas)",
    "Dommage physique / gonflement",
    "Surchauffe",
    "Autre",
]


class WorkflowError(Exception):
    """Action refusée par une règle métier (message affiché à l'utilisateur)."""


def module_alerts(passport):
    """Modules dont la résistance interne dépasse le maximum constructeur."""
    return [m for m in passport.get("modules", [])
            if m.get("internalResistance_mOhm") is not None
            and m.get("maxInternalResistance_mOhm") is not None
            and m["internalResistance_mOhm"] > m["maxInternalResistance_mOhm"]]


def check_transition(current, target):
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise WorkflowError(f"Transition de statut interdite : {current} → {target}.")


def _owner_actors(operator_uid):
    from . import config
    return [a["actor_uid"] for a in config.ACCOUNTS.values()
            if a["role"] == "proprietaire" and a.get("operator_uid") == operator_uid]


def request_waste(repo, battery_id, garage, fault_type, comment, destination_uid="",
                  auto_logistics=False, pickup_date="", pickup_slot=""):
    """Le garagiste signale la batterie hors d'usage au propriétaire du passeport.

    Défi 2 : il propose le centre de tri agréé et peut demander la planification
    automatique de la collecte (date et créneau)."""
    from . import logistics, notify
    p = repo.get_passport(battery_id)
    if p is None:
        raise WorkflowError(f"Batterie {battery_id} introuvable.")
    status = p["battery"]["status"]
    if p.get("pending_request"):
        raise WorkflowError("Une demande est déjà en attente pour cette batterie.")
    check_transition(status, "Waste")
    if fault_type not in FAULT_TYPES:
        raise WorkflowError("Type de défaut inconnu.")
    centers = {c["uid"]: c for c in repo.list_actors("centre_tri")}
    if destination_uid not in centers:
        raise WorkflowError("Choisissez un centre de tri de destination.")
    logistics.check_actor(centers[destination_uid], "Centre de tri",
                          damage=logistics.damage_class(fault_type))
    if not p.get("operator"):
        raise WorkflowError("Aucun propriétaire (opérateur économique) lié à cette batterie.")
    alerts = module_alerts(p)
    diagnostic = (f"SOH {p['dynamic_performance'].get('soh')} % ; "
                  + (", ".join(f"module {m['index']} : {m['internalResistance_mOhm']} mΩ "
                               f"(max {m['maxInternalResistance_mOhm']})" for m in alerts)
                     or "aucun module hors seuil"))
    reason = f"{fault_type}. {comment}".strip()
    uid = repo.create_status_request(
        battery_id=battery_id, actor_uid=garage["actor_uid"],
        operator_uid=p["operator"]["uid"], from_status=status, requested_status="Waste",
        reason=reason, diagnostic=diagnostic, destination_uid=destination_uid,
        auto_logistics=bool(auto_logistics), pickup_date=(pickup_date or "").strip(),
        pickup_slot=(pickup_slot or "").strip())
    notify.notify(repo, _owner_actors(p["operator"]["uid"]), f"Demande hors d'usage : {battery_id}",
                  f"{garage.get('display', 'Le garage')} demande le passage de {battery_id} en Waste. "
                  f"Motif : {reason}. Diagnostic : {diagnostic}.", "/owner#inbox", battery_id)
    return uid


def approve_request(repo, notif_uid, owner, destination_uid="", comment=""):
    """Le propriétaire valide : statut → Waste + ordre de transfert vers un centre de tri.

    Sans destination explicite, le centre proposé par le garagiste est retenu.
    Renvoie l'identifiant de l'ordre de transfert créé."""
    from . import logistics
    n = repo.get_notification(notif_uid)
    if n is None:
        raise WorkflowError("Demande introuvable.")
    if n["state"] != "PENDING":
        raise WorkflowError("Cette demande a déjà été traitée.")
    if n["operatorUid"] != owner["operator_uid"]:
        raise WorkflowError("Vous n'êtes pas propriétaire de ce passeport.")
    p = repo.get_passport(n["batteryId"])
    check_transition(p["battery"]["status"], n["requestedStatus"])
    destination_uid = destination_uid or n.get("destinationUid") or ""
    centers = {c["uid"]: c for c in repo.list_actors("centre_tri")}
    if destination_uid not in centers:
        raise WorkflowError("Centre de tri inconnu.")
    if not centers[destination_uid].get("agreed"):
        raise WorkflowError("Ce centre de tri n'est pas agréé : transfert refusé.")
    logistics.check_actor(centers[destination_uid], "Centre de tri",
                          damage=logistics.damage_class(n.get("reason")))
    repo.apply_approval(notif_uid=notif_uid, battery_id=n["batteryId"],
                        owner_uid=owner["actor_uid"], new_status=n["requestedStatus"],
                        from_status=p["battery"]["status"], destination_uid=destination_uid,
                        comment=comment)
    return logistics.init_order(repo, n["batteryId"], owner["actor_uid"], n.get("reason"), comment)


def auto_schedule(repo, notif, order_uid, owner):
    """Planification automatique demandée par le garagiste : premier transporteur éligible.
    Renvoie le transporteur retenu, ou None si aucun n'est éligible."""
    from datetime import date

    from . import logistics
    pickup_date = notif.get("pickupDate") or date.today().isoformat()
    slot = notif.get("pickupSlot") or "8h-12h"
    damage = logistics.damage_class(notif.get("reason"))
    carriers = sorted((c for c in repo.list_actors("transporteur")
                       if not logistics.agreement_problems(c, pickup_date, damage)),
                      key=lambda c: c["name"])
    if not carriers:
        return None
    logistics.schedule(repo, order_uid, owner, carriers[0]["uid"], pickup_date, slot,
                       "Planification automatique demandée par le garagiste.")
    return carriers[0]


def reject_request(repo, notif_uid, owner, comment):
    from . import notify
    n = repo.get_notification(notif_uid)
    if n is None or n["state"] != "PENDING":
        raise WorkflowError("Demande introuvable ou déjà traitée.")
    if n["operatorUid"] != owner["operator_uid"]:
        raise WorkflowError("Vous n'êtes pas propriétaire de ce passeport.")
    if not comment.strip():
        raise WorkflowError("Un motif de refus est obligatoire.")
    repo.apply_rejection(notif_uid=notif_uid, battery_id=n["batteryId"],
                         owner_uid=owner["actor_uid"], comment=comment)
    notify.notify(repo, [n.get("senderUid")], f"Demande refusée : {n['batteryId']}",
                  f"Le propriétaire du passeport a refusé la demande hors d'usage : {comment}",
                  f"/garage/b/{n['batteryId']}", n["batteryId"])


def confirm_reception(repo, battery_id, center, seal="", weight=None, checks=None, comment=""):
    """Le centre de tri accuse réception. Défi 2 : la batterie doit avoir été enlevée par
    un transporteur, avec scellé et pesée vérifiés (règles dans bp/logistics.py).
    Renvoie le code de preuve de dépôt."""
    from . import logistics
    return logistics.receive(repo, battery_id, center, seal, weight, checks or {}, comment)
