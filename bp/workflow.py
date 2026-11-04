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


def request_waste(repo, battery_id, garage, fault_type, comment):
    """Le garagiste signale la batterie hors d'usage au propriétaire du passeport."""
    p = repo.get_passport(battery_id)
    if p is None:
        raise WorkflowError(f"Batterie {battery_id} introuvable.")
    status = p["battery"]["status"]
    if p.get("pending_request"):
        raise WorkflowError("Une demande est déjà en attente pour cette batterie.")
    check_transition(status, "Waste")
    if fault_type not in FAULT_TYPES:
        raise WorkflowError("Type de défaut inconnu.")
    if not p.get("operator"):
        raise WorkflowError("Aucun propriétaire (opérateur économique) lié à cette batterie.")
    alerts = module_alerts(p)
    diagnostic = (f"SOH {p['dynamic_performance'].get('soh')} % ; "
                  + (", ".join(f"module {m['index']} : {m['internalResistance_mOhm']} mΩ "
                               f"(max {m['maxInternalResistance_mOhm']})" for m in alerts)
                     or "aucun module hors seuil"))
    return repo.create_status_request(
        battery_id=battery_id, actor_uid=garage["actor_uid"],
        operator_uid=p["operator"]["uid"], from_status=status, requested_status="Waste",
        reason=f"{fault_type}. {comment}".strip(), diagnostic=diagnostic)


def approve_request(repo, notif_uid, owner, destination_uid, comment=""):
    """Le propriétaire valide : statut → Waste + ordre de transfert vers un centre de tri."""
    n = repo.get_notification(notif_uid)
    if n is None:
        raise WorkflowError("Demande introuvable.")
    if n["state"] != "PENDING":
        raise WorkflowError("Cette demande a déjà été traitée.")
    if n["operatorUid"] != owner["operator_uid"]:
        raise WorkflowError("Vous n'êtes pas propriétaire de ce passeport.")
    p = repo.get_passport(n["batteryId"])
    check_transition(p["battery"]["status"], n["requestedStatus"])
    centers = {c["uid"]: c for c in repo.list_actors("centre_tri")}
    if destination_uid not in centers:
        raise WorkflowError("Centre de tri inconnu.")
    if not centers[destination_uid].get("agreed"):
        raise WorkflowError("Ce centre de tri n'est pas agréé : transfert refusé.")
    repo.apply_approval(notif_uid=notif_uid, battery_id=n["batteryId"],
                        owner_uid=owner["actor_uid"], new_status=n["requestedStatus"],
                        from_status=p["battery"]["status"], destination_uid=destination_uid,
                        comment=comment)


def reject_request(repo, notif_uid, owner, comment):
    n = repo.get_notification(notif_uid)
    if n is None or n["state"] != "PENDING":
        raise WorkflowError("Demande introuvable ou déjà traitée.")
    if n["operatorUid"] != owner["operator_uid"]:
        raise WorkflowError("Vous n'êtes pas propriétaire de ce passeport.")
    if not comment.strip():
        raise WorkflowError("Un motif de refus est obligatoire.")
    repo.apply_rejection(notif_uid=notif_uid, battery_id=n["batteryId"],
                         owner_uid=owner["actor_uid"], comment=comment)


def confirm_reception(repo, battery_id, center):
    """Le centre de tri accuse réception. Refusé si le statut n'est pas à jour."""
    p = repo.get_passport(battery_id)
    if p is None:
        raise WorkflowError(f"Batterie {battery_id} introuvable.")
    if p["battery"]["status"] != "Waste":
        raise WorkflowError("Statut non à jour (pas « Waste ») : réception refusée, "
                            "contactez le propriétaire du passeport.")
    t = p.get("transfer")
    if not t or t["state"] != "ORDERED":
        raise WorkflowError("Aucun ordre de transfert en cours pour cette batterie.")
    if t["toUid"] != center["actor_uid"]:
        raise WorkflowError(f"Cette batterie est attendue par « {t['toName']} », pas par votre centre.")
    repo.apply_reception(order_uid=t["uid"], battery_id=battery_id, center_uid=center["actor_uid"])
