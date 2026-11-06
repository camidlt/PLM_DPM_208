"""Défi 2 : logistique et conformité du transfert vers le centre de tri.

Cycle de vie d'un ordre de transfert (TransferOrder.state) :

    ORDERED ──► SCHEDULED ──► PICKED_UP ──► RECEIVED
       │            │              └──────► REFUSED  ──► nouvel ordre (redirection)
       └────────────┴──► CANCELLED ──────────────────► nouvel ordre

  ORDERED    créé quand le propriétaire valide Original → Waste (tronc commun)
  SCHEDULED  le propriétaire affecte un transporteur agréé et une date d'enlèvement
  PICKED_UP  le transporteur enlève au garage : scellé, pesée, contrôles ADR, remise signée
  RECEIVED   le centre de tri destinataire vérifie scellé + pesée : accusé de réception
  REFUSED    anomalie à réception (scellé, fuite...) : la batterie reste chez le transporteur
  CANCELLED  annulation par le propriétaire, possible tant que la batterie n'est pas enlevée

Sécurité et traçabilité :
  * agréments vérifiés (centre ET transporteur, date de validité, batteries endommagées) ;
  * chaque étape est un (:LogisticsStep) signé par son acteur et chaîné par empreinte
    SHA-256 (prevHash → hash) : toute modification a posteriori casse la chaîne ;
  * le numéro de scellé saisi à l'enlèvement doit être retrouvé à l'arrivée ;
  * la batterie est localisée à chaque étape ((:BatteryInstance)-[:LOCATED_AT]->(:Actor)).
"""
import hashlib
import json
import re
from datetime import date, datetime

from . import config, notify
from .workflow import WorkflowError

STATES = {
    "ORDERED": "À planifier",
    "SCHEDULED": "Enlèvement planifié",
    "PICKED_UP": "En transit",
    "RECEIVED": "Réceptionnée",
    "REFUSED": "Refusée à réception",
    "CANCELLED": "Annulé",
}
STEP_LABELS = {
    "ORDER_CREATED": "Ordre de transfert créé",
    "ORDER_REDIRECTED": "Ordre de redirection créé",
    "CARRIER_ASSIGNED": "Transporteur affecté",
    "PICKED_UP": "Enlèvement au garage",
    "RECEIVED": "Réception au centre de tri",
    "REFUSED": "Réception refusée",
    "CANCELLED": "Ordre annulé",
}

# ADR (transport routier de marchandises dangereuses) : batteries Li-ion transportées seules
UN_DESIGNATION = "UN 3480 DÉCHET BATTERIES LITHIUM-ION, 9, (E)"
ADR_CLASSES = {
    "standard": dict(label="Batterie à recycler (non endommagée)", provision="DS 377",
                     packing="P909", marking="BATTERIES LITHIUM-ION À RECYCLER"),
    "damaged": dict(label="Batterie endommagée ou défectueuse", provision="DS 376",
                    packing="P908 / LP904", marking="BATTERIE LITHIUM-ION ENDOMMAGÉE/DÉFECTUEUSE"),
    "critical": dict(label="Batterie défectueuse critique (risque d'emballement)", provision="DS 376",
                     packing="P911 / LP906", marking="BATTERIE LITHIUM-ION ENDOMMAGÉE/DÉFECTUEUSE"),
}
ADR_HEAVY_KG = 333   # au-delà : conducteur formé ADR et consignes écrites à bord

PICKUP_CHECKS = {
    "packaging": "Emballage conforme à l'instruction ADR indiquée",
    "terminals": "Bornes protégées contre les courts-circuits",
    "labels": "Étiquette QR, marquage UN 3480 et étiquette classe 9 apposés",
    "documents": "Ordre de transfert et consignes écrites à bord",
}
RECEPTION_CHECKS = {
    "seal": "Scellé intact",
    "packaging": "Emballage intact : ni fuite, ni échauffement, ni odeur",
}
WEIGHT_TOLERANCE = 0.05   # écart de pesée toléré entre enlèvement et réception
SEAL_RE = re.compile(r"^[A-Z0-9-]{4,20}$")


def now():
    return datetime.now().isoformat(timespec="seconds")


# --- Conformité des acteurs ---------------------------------------------------------
def damage_class(reason):
    """Classe ADR déduite du défaut signalé par le garagiste."""
    reason = reason or ""
    if "Surchauffe" in reason:
        return "critical"
    if "Dommage physique" in reason:
        return "damaged"
    return "standard"


def agreement_problems(actor, on_date=None, damage="standard"):
    """Raisons pour lesquelles un centre de tri / transporteur ne peut pas être retenu."""
    on_date = on_date or date.today().isoformat()
    problems = []
    if not actor.get("agreed"):
        problems.append("non agréé")
    elif actor.get("agreementValidUntil") and actor["agreementValidUntil"] < on_date:
        problems.append(f"agrément expiré le {actor['agreementValidUntil']}")
    if actor.get("role") == "transporteur":
        if not actor.get("adr"):
            problems.append("non habilité ADR classe 9")
        if damage != "standard" and not actor.get("damagedCapable"):
            problems.append("non équipé pour les batteries endommagées")
    if actor.get("role") == "centre_tri" and damage != "standard" and not actor.get("acceptsDamaged"):
        problems.append("n'accepte pas les batteries endommagées")
    return problems


def check_actor(actor, kind, on_date=None, damage="standard"):
    problems = agreement_problems(actor, on_date, damage)
    if problems:
        raise WorkflowError(f"{kind} « {actor['name']} » refusé : {', '.join(problems)}.")


def annotate(actors, damage="standard", on_date=None):
    """Ajoute `problems` à chaque acteur (pour griser les choix impossibles à l'écran)."""
    return [dict(a, problems=agreement_problems(a, on_date, damage)) for a in actors]


# --- Chaîne d'étapes signées ----------------------------------------------------------
def _hash(step):
    payload = {k: step[k] for k in ("seq", "type", "at", "actorUid", "actorName", "dataJson", "prevHash")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_step(repo, order_uid, actor_uid, step_type, data):
    steps = repo.get_transfer_steps(order_uid)
    actor = repo.get_actor(actor_uid)
    step = dict(seq=len(steps) + 1, type=step_type, at=now(), actorUid=actor_uid,
                actorName=actor["name"], dataJson=json.dumps(data, ensure_ascii=False, sort_keys=True),
                prevHash=steps[-1]["hash"] if steps else "0" * 64)
    step["hash"] = _hash(step)
    repo.add_transfer_step(order_uid, actor_uid, step)
    return step


def verify_chain(steps):
    """(True, None) si la chaîne est intacte, sinon (False, n° de la première étape altérée)."""
    prev = "0" * 64
    for s in steps:
        if s.get("prevHash") != prev or _hash(s) != s.get("hash"):
            return False, s.get("seq")
        prev = s["hash"]
    return True, None


# --- Contrôles communs --------------------------------------------------------------
def _load(repo, order_uid):
    t = repo.get_transfer(order_uid)
    if t is None:
        raise WorkflowError("Ordre de transfert introuvable.")
    return t


def _check_owner(repo, t, owner):
    p = repo.get_passport(t["batteryId"])
    if not p.get("operator") or p["operator"]["uid"] != owner.get("operator_uid"):
        raise WorkflowError("Vous n'êtes pas propriétaire de ce passeport.")
    return p


def _expect(t, *states):
    if t["state"] not in states:
        raise WorkflowError(f"Action impossible : l'ordre {t['uid']} est « {STATES.get(t['state'], t['state'])} ».")


def _number(value, label, lo, hi):
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise WorkflowError(f"{label} : nombre attendu.")
    if not lo <= v <= hi:
        raise WorkflowError(f"{label} : valeur hors plage ({lo} à {hi}).")
    return round(v, 1)


def _missing_checks(checks, expected):
    missing = [label for key, label in expected.items() if not checks.get(key)]
    if missing:
        raise WorkflowError("Contrôles non validés : " + " ; ".join(missing) + ".")


def _link(t):
    return f"/transfers/{t['uid']}"


# --- Étapes du workflow ---------------------------------------------------------------
def init_order(repo, battery_id, owner_uid, reason, comment=""):
    """Complète l'ordre créé à la validation du propriétaire (classe ADR, poids, étape n°1)."""
    p = repo.get_passport(battery_id)
    t = repo.get_transfer(p["transfer"]["uid"])
    damage = damage_class(reason)
    adr = ADR_CLASSES[damage]
    weight = (p.get("model") or {}).get("weight_kg")
    props = dict(damageClass=damage, unDesignation=UN_DESIGNATION, adrProvision=adr["provision"],
                 adrPacking=adr["packing"], adrMarking=adr["marking"], wasteCode=config.WASTE_CODE,
                 declaredWeightKg=weight, ownerComment=comment)
    repo.update_transfer(t["uid"], props)
    record_step(repo, t["uid"], owner_uid, "ORDER_CREATED",
                dict(destination=t["toUid"], origin=t.get("fromUid") or t.get("fromName"),
                     damageClass=damage, declaredWeightKg=weight, comment=comment))
    notify.notify(repo, [t.get("fromUid"), t["toUid"]], f"Transfert annoncé : {battery_id}",
                  f"Ordre {t['uid']} : {battery_id} ({adr['label'].lower()}) sera transférée de "
                  f"{t.get('fromName') or 'origine non renseignée'} vers {t['toName']}. Enlèvement à planifier.",
                  _link(t), battery_id, t["uid"])
    return t["uid"]


def schedule(repo, order_uid, owner, carrier_uid, pickup_date, slot="", instructions=""):
    """Le propriétaire affecte un transporteur agréé et fixe la date d'enlèvement."""
    t = _load(repo, order_uid)
    _check_owner(repo, t, owner)
    _expect(t, "ORDERED", "SCHEDULED")
    carrier = repo.get_actor(carrier_uid or "")
    if carrier is None or carrier.get("role") != "transporteur":
        raise WorkflowError("Transporteur inconnu.")
    try:
        day = date.fromisoformat(pickup_date or "")
    except ValueError:
        raise WorkflowError("Date d'enlèvement invalide.")
    if day < date.today():
        raise WorkflowError("La date d'enlèvement est déjà passée.")
    check_actor(carrier, "Transporteur", day.isoformat(), t.get("damageClass", "standard"))
    rescheduled = t["state"] == "SCHEDULED"
    repo.update_transfer(order_uid, dict(state="SCHEDULED", pickupDate=day.isoformat(),
                                         pickupSlot=slot.strip(), instructions=instructions.strip(),
                                         scheduledAt=now()), carrier_uid=carrier_uid)
    record_step(repo, order_uid, owner["actor_uid"], "CARRIER_ASSIGNED",
                dict(carrier=carrier_uid, pickupDate=day.isoformat(), slot=slot.strip(),
                     rescheduled=rescheduled))
    repo.add_event(t["batteryId"], "TRANSFER_SCHEDULED", owner["actor_uid"],
                   f"Enlèvement {'replanifié' if rescheduled else 'planifié'} le {day.isoformat()} "
                   f"{slot.strip()} par {carrier['name']} ({order_uid})")
    notify.notify(repo, [carrier_uid, t.get("fromUid"), t["toUid"], t.get("carrierUid")],
                  f"Enlèvement planifié : {t['batteryId']}",
                  f"{carrier['name']} enlèvera {t['batteryId']} chez {t.get('fromName')} le "
                  f"{day.isoformat()} {slot.strip()}, à destination de {t['toName']}. "
                  f"Emballage : {t.get('adrPacking')}.", _link(t), t["batteryId"], order_uid)


def cancel(repo, order_uid, owner, reason):
    t = _load(repo, order_uid)
    _check_owner(repo, t, owner)
    _expect(t, "ORDERED", "SCHEDULED")
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("Le motif d'annulation est obligatoire.")
    repo.update_transfer(order_uid, dict(state="CANCELLED", cancelledAt=now(), cancelReason=reason))
    record_step(repo, order_uid, owner["actor_uid"], "CANCELLED", dict(reason=reason))
    repo.add_event(t["batteryId"], "TRANSFER_CANCELLED", owner["actor_uid"],
                   f"Ordre {order_uid} annulé : {reason}")
    notify.notify(repo, [t.get("carrierUid"), t.get("fromUid"), t["toUid"]],
                  f"Transfert annulé : {t['batteryId']}", f"L'ordre {order_uid} est annulé : {reason}",
                  _link(t), t["batteryId"], order_uid)


def pickup(repo, order_uid, carrier_user, seal, weight, handed_over_by, checks):
    """Le transporteur enlève la batterie au garage (remise contradictoire)."""
    t = _load(repo, order_uid)
    _expect(t, "SCHEDULED")
    if t.get("carrierUid") != carrier_user["actor_uid"]:
        raise WorkflowError("Cette mission est affectée à un autre transporteur.")
    p = repo.get_passport(t["batteryId"])
    if t.get("fromUid") and (p.get("location") or {}).get("uid") != t["fromUid"]:
        raise WorkflowError(f"La batterie n'est pas chez {t.get('fromName')}.")
    seal = (seal or "").strip().upper()
    if not SEAL_RE.match(seal):
        raise WorkflowError("Numéro de scellé invalide (4 à 20 caractères : lettres, chiffres, tirets).")
    weight = _number(weight, "Poids à l'enlèvement (kg)", 1, 5000)
    handed_over_by = (handed_over_by or "").strip()
    if not handed_over_by:
        raise WorkflowError("Indiquez le nom de la personne du garage qui remet la batterie.")
    _missing_checks(checks, PICKUP_CHECKS)
    repo.update_transfer(order_uid, dict(state="PICKED_UP", sealNumber=seal, pickupWeightKg=weight,
                                         handedOverBy=handed_over_by, pickedUpAt=now()),
                         location_uid=carrier_user["actor_uid"])
    record_step(repo, order_uid, carrier_user["actor_uid"], "PICKED_UP",
                dict(seal=seal, weightKg=weight, handedOverBy=handed_over_by,
                     checks=sorted(PICKUP_CHECKS)))
    repo.add_event(t["batteryId"], "PICKED_UP", carrier_user["actor_uid"],
                   f"Enlevée chez {t.get('fromName')} (remise par {handed_over_by}), scellé {seal}, "
                   f"{weight} kg ({order_uid})")
    notify.notify(repo, [_owner_actor(p), t["toUid"], t.get("fromUid")],
                  f"Batterie enlevée : {t['batteryId']}",
                  f"{t['carrierName']} a enlevé {t['batteryId']} chez {t.get('fromName')}. Scellé {seal}, "
                  f"{weight} kg. En route vers {t['toName']}.", _link(t), t["batteryId"], order_uid)


def _owner_actor(p):
    """Acteur « propriétaire » représentant l'opérateur économique de la batterie."""
    op = (p.get("operator") or {}).get("uid")
    return next((a["actor_uid"] for a in config.ACCOUNTS.values()
                 if a["role"] == "proprietaire" and a.get("operator_uid") == op), None)


def receive(repo, battery_id, center, seal, weight, checks, comment=""):
    """Le centre de tri destinataire accuse réception (preuve de dépôt)."""
    p = repo.get_passport(battery_id)
    if p is None:
        raise WorkflowError(f"Batterie {battery_id} introuvable.")
    if p["battery"]["status"] != "Waste":
        raise WorkflowError("Statut non à jour (pas « Waste ») : réception refusée, "
                            "contactez le propriétaire du passeport.")
    t = p.get("transfer")
    if not t or t["state"] in ("RECEIVED", "REFUSED", "CANCELLED"):
        raise WorkflowError("Aucun ordre de transfert en cours pour cette batterie.")
    if t["toUid"] != center["actor_uid"]:
        raise WorkflowError(f"Cette batterie est attendue par « {t['toName']} », pas par votre centre.")
    if t["state"] != "PICKED_UP":
        raise WorkflowError("La batterie n'a pas encore été enlevée par un transporteur : réception impossible.")
    t = repo.get_transfer(t["uid"])
    seal = (seal or "").strip().upper()
    if seal != t.get("sealNumber"):
        raise WorkflowError("Scellé non conforme : le numéro ne correspond pas à celui posé à l'enlèvement. "
                            "Refusez la réception.")
    weight = _number(weight, "Poids à réception (kg)", 1, 5000)
    _missing_checks(checks, RECEPTION_CHECKS)
    deviation = abs(weight - t["pickupWeightKg"]) / t["pickupWeightKg"]
    anomaly = (f"Écart de pesée de {deviation:.1%} (enlèvement {t['pickupWeightKg']} kg)"
               if deviation > WEIGHT_TOLERANCE else "")
    comment = (comment or "").strip()
    step = record_step(repo, t["uid"], center["actor_uid"], "RECEIVED",
                       dict(seal=seal, weightKg=weight, anomaly=anomaly, comment=comment))
    receipt = step["hash"][:12].upper()
    repo.update_transfer(t["uid"], dict(state="RECEIVED", receivedAt=step["at"], receptionWeightKg=weight,
                                        weightDeviationPct=round(deviation * 100, 1), anomaly=anomaly,
                                        receptionComment=comment, receiptCode=receipt),
                         location_uid=center["actor_uid"])
    repo.add_event(battery_id, "RECEIVED", center["actor_uid"],
                   f"Batterie réceptionnée (ordre {t['uid']}), preuve de dépôt {receipt}"
                   + (f". {anomaly}" if anomaly else ""))
    notify.notify(repo, [_owner_actor(p), t.get("fromUid"), t.get("carrierUid")],
                  f"Preuve de dépôt : {battery_id}",
                  f"{t['toName']} a réceptionné {battery_id} ({weight} kg, scellé {seal} conforme). "
                  f"Code de preuve de dépôt : {receipt}." + (f" Anomalie : {anomaly}." if anomaly else ""),
                  _link(t), battery_id, t["uid"])
    return receipt


def refuse(repo, battery_id, center, reason):
    """Anomalie à l'arrivée : la batterie reste sous la garde du transporteur."""
    p = repo.get_passport(battery_id)
    t = (p or {}).get("transfer")
    if not t or t["state"] != "PICKED_UP":
        raise WorkflowError("Aucune livraison en cours pour cette batterie.")
    if t["toUid"] != center["actor_uid"]:
        raise WorkflowError(f"Cette batterie est attendue par « {t['toName']} », pas par votre centre.")
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("Le motif du refus est obligatoire.")
    t = repo.get_transfer(t["uid"])
    repo.update_transfer(t["uid"], dict(state="REFUSED", refusedAt=now(), refusalReason=reason))
    record_step(repo, t["uid"], center["actor_uid"], "REFUSED", dict(reason=reason))
    repo.add_event(battery_id, "RECEPTION_REFUSED", center["actor_uid"],
                   f"Réception refusée ({t['uid']}) : {reason}. Batterie sous la garde de {t['carrierName']}.")
    notify.notify(repo, [_owner_actor(p), t.get("carrierUid")],
                  f"Réception refusée : {battery_id}",
                  f"{t['toName']} a refusé {battery_id} : {reason}. La batterie reste chez "
                  f"{t['carrierName']} : créez un ordre de redirection.", _link(t), battery_id, t["uid"])


def new_order(repo, battery_id, owner, destination_uid, comment=""):
    """Nouvel ordre après une annulation, ou redirection après un refus à réception."""
    p = repo.get_passport(battery_id)
    if p is None:
        raise WorkflowError(f"Batterie {battery_id} introuvable.")
    prev = p.get("transfer")
    if not prev or prev["state"] not in ("CANCELLED", "REFUSED"):
        raise WorkflowError("Un nouvel ordre n'est possible qu'après une annulation ou un refus à réception.")
    prev = repo.get_transfer(prev["uid"])
    _check_owner(repo, prev, owner)
    if p["battery"]["status"] != "Waste":
        raise WorkflowError("Le statut de la batterie n'est pas « Waste ».")
    dest = repo.get_actor(destination_uid or "")
    if dest is None or dest.get("role") != "centre_tri":
        raise WorkflowError("Centre de tri inconnu.")
    damage = prev.get("damageClass", "standard")
    check_actor(dest, "Centre de tri", damage=damage)
    keep = {k: prev.get(k) for k in ("damageClass", "unDesignation", "adrProvision", "adrPacking",
                                     "adrMarking", "wasteCode", "declaredWeightKg") if prev.get(k) is not None}
    keep.update(previousOrder=prev["uid"], ownerComment=(comment or "").strip())
    location = (p.get("location") or {}).get("uid")
    if prev["state"] == "REFUSED":
        if destination_uid == prev["toUid"]:
            raise WorkflowError("Choisissez un autre centre de tri que celui qui a refusé la batterie.")
        # la batterie est déjà dans le camion, sous scellé : redirection directe
        keep.update(state="PICKED_UP", sealNumber=prev["sealNumber"], pickupWeightKg=prev["pickupWeightKg"],
                    handedOverBy=prev.get("handedOverBy"), pickedUpAt=prev.get("pickedUpAt"))
        uid = repo.create_transfer(battery_id, location, destination_uid, keep, carrier_uid=prev["carrierUid"])
        step_type, carrier = "ORDER_REDIRECTED", prev["carrierUid"]
    else:
        keep["state"] = "ORDERED"
        uid = repo.create_transfer(battery_id, location, destination_uid, keep)
        step_type, carrier = "ORDER_CREATED", None
    repo.update_transfer(prev["uid"], dict(supersededBy=uid))
    record_step(repo, uid, owner["actor_uid"], step_type,
                dict(destination=destination_uid, previousOrder=prev["uid"], comment=keep["ownerComment"]))
    repo.add_event(battery_id, "TRANSFER_ORDERED", owner["actor_uid"],
                   f"{'Redirection' if carrier else 'Nouvel ordre'} vers {dest['name']} ({uid}), "
                   f"remplace {prev['uid']}")
    notify.notify(repo, [destination_uid, carrier, None if carrier else location],
                  f"{'Redirection' if carrier else 'Transfert annoncé'} : {battery_id}",
                  f"Ordre {uid} : {battery_id} est {'redirigée' if carrier else 'à transférer'} vers {dest['name']}.",
                  f"/transfers/{uid}", battery_id, uid)
    return uid


# --- Droits de consultation et documents -------------------------------------------------
def can_view(user, t):
    if user["role"] == "proprietaire":
        return True   # le PoC n'a qu'un propriétaire ; à filtrer par opérateur en multi-fabricants
    return user.get("actor_uid") in (t.get("fromUid"), t.get("toUid"), t.get("carrierUid"))


def transfer_document(repo, order_uid):
    """Manifeste complet du transfert (JSON) : sert aux documents imprimables et à l'API."""
    t = _load(repo, order_uid)
    p = repo.get_passport(t["batteryId"])
    steps = repo.get_transfer_steps(order_uid)
    valid, broken = verify_chain(steps)
    actor = lambda uid: repo.get_actor(uid) if uid else None  # noqa: E731
    party = lambda a: a and {k: a.get(k) for k in (  # noqa: E731
        "uid", "name", "role", "address", "city", "email", "siret", "agreed", "agreementNumber",
        "agreementValidUntil", "adr") if a.get(k) not in (None, "")}
    weight = t.get("receptionWeightKg") or t.get("pickupWeightKg") or t.get("declaredWeightKg") or 0
    adr = ADR_CLASSES.get(t.get("damageClass", "standard"), ADR_CLASSES["standard"])
    return {
        "schema": "battery-passport/transfer-manifest/1",
        "generatedAt": now(),
        "order": {k: t.get(k) for k in (
            "uid", "state", "createdAt", "pickupDate", "pickupSlot", "instructions", "scheduledAt",
            "pickedUpAt", "receivedAt", "refusedAt", "refusalReason", "cancelledAt", "cancelReason",
            "previousOrder", "ownerComment") if t.get(k) not in (None, "")},
        "stateLabel": STATES.get(t["state"], t["state"]),
        "battery": {
            "batteryId": p["battery"]["batteryId"], "batteryPassportId": p["battery"].get("batteryPassportId"),
            "serialNumber": p["battery"].get("serialNumber"), "status": p["battery"]["status"],
            "model": (p.get("model") or {}).get("name"),
            "chemistry": (p.get("composition") or {}).get("batteryChemistry"),
            "declaredWeightKg": t.get("declaredWeightKg"), "passportUrl": f"{config.BASE_URL}/b/{t['batteryId']}",
        },
        "parties": {
            "producer": party(p.get("operator") or {}),
            "holder": party(actor(t.get("fromUid"))),
            "carrier": party(actor(t.get("carrierUid"))),
            "destination": party(actor(t["toUid"])),
        },
        "dangerousGoods": {
            "unNumber": "UN 3480", "designation": t.get("unDesignation", UN_DESIGNATION), "class": "9",
            "tunnelCode": "E", "condition": adr["label"], "specialProvision": t.get("adrProvision"),
            "packingInstruction": t.get("adrPacking"), "marking": t.get("adrMarking"),
            "heavyLoad": weight > ADR_HEAVY_KG,
        },
        "waste": {"code": t.get("wasteCode", config.WASTE_CODE), "passportStatus": p["battery"]["status"]},
        "custody": {k: t.get(k) for k in (
            "sealNumber", "handedOverBy", "pickupWeightKg", "receptionWeightKg", "weightDeviationPct",
            "anomaly", "receptionComment", "receiptCode") if t.get(k) not in (None, "")},
        "steps": [dict(seq=s["seq"], type=s["type"], label=STEP_LABELS.get(s["type"], s["type"]),
                       at=s["at"], actor=s["actorName"], actorUid=s["actorUid"],
                       data=json.loads(s.get("dataJson") or "{}"), prevHash=s["prevHash"], hash=s["hash"])
                  for s in steps],
        "integrity": {"algorithm": "SHA-256 chaîné", "valid": valid, "brokenAtStep": broken,
                      "lastHash": steps[-1]["hash"] if steps else None},
    }
