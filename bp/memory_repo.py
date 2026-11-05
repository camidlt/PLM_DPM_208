"""Base de données en mémoire (même modèle de graphe que Neo4j).

Permet de faire tourner la démo sans Neo4j. Les données sont partagées entre
tous les navigateurs connectés au même serveur, et remises à zéro au redémarrage.
"""
import copy
import threading
import uuid
from datetime import datetime

from . import seed_data


def now():
    return datetime.now().isoformat(timespec="seconds")


def new_uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class MemoryRepo:
    backend = "memory"

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    # --- primitives de graphe ------------------------------------------------
    def reset(self):
        with self.lock:
            self.nodes = {uid: {"_label": label, **copy.deepcopy(props)}
                          for label, uid, props in seed_data.NODES}
            self.rels = [list(r) for r in seed_data.RELS]

    def _add(self, label, uid, **props):
        self.nodes[uid] = {"_label": label, "uid": uid, **props}
        return uid

    def _out(self, uid, rel_type, label=None):
        return [self.nodes[b] for a, r, b in self.rels
                if a == uid and r == rel_type and (label is None or self.nodes[b]["_label"] == label)]

    def _in(self, uid, rel_type, label=None):
        return [self.nodes[a] for a, r, b in self.rels
                if b == uid and r == rel_type and (label is None or self.nodes[a]["_label"] == label)]

    @staticmethod
    def _clean(n):
        return None if n is None else {k: v for k, v in n.items() if k != "_label"}

    def _one(self, lst):
        return self._clean(lst[0]) if lst else None

    def _battery(self, battery_id):
        for n in self.nodes.values():
            if n["_label"] == "BatteryInstance" and n.get("batteryId") == battery_id:
                return n
        return None

    def _event(self, battery_uid, etype, actor_uid, details):
        uid = self._add("Event", new_uid("EVT"), type=etype, at=now(),
                        actorName=self.nodes[actor_uid]["name"], details=details)
        self.rels.append([battery_uid, "HAS_EVENT", uid])
        self.rels.append([actor_uid, "PERFORMED", uid])

    # --- lectures --------------------------------------------------------------
    def list_batteries(self):
        with self.lock:
            out = []
            for n in self.nodes.values():
                if n["_label"] != "BatteryInstance":
                    continue
                model = self._one(self._in(n["uid"], "HAS_BATTERY_INSTANCE", "Model")) or {}
                dp = self._one(self._out(n["uid"], "HAS_DYNAMIC_PERFORMANCE")) or {}
                loc = self._one(self._out(n["uid"], "LOCATED_AT")) or {}
                out.append(dict(batteryId=n["batteryId"], status=n["status"],
                                model=model.get("name"), soh=dp.get("soh"), location=loc.get("name")))
            return sorted(out, key=lambda x: x["batteryId"])

    def get_passport(self, battery_id):
        with self.lock:
            b = self._battery(battery_id)
            if b is None:
                return None
            uid = b["uid"]
            model = (self._in(uid, "HAS_BATTERY_INSTANCE", "Model") or [None])[0]
            muid = model["uid"] if model else None
            comp = (self._out(muid, "HAS_COMPOSITION") or [None])[0] if muid else None
            cuid = comp["uid"] if comp else None
            sub = lambda u, r: self._one(self._out(u, r)) if u else None  # noqa: E731
            pending = [n for n in self._in(uid, "ABOUT", "Notification") if n["state"] == "PENDING"]
            return dict(
                battery=self._clean(b),
                model=self._clean(model),
                type=self._one(self._in(muid, "HAS_MODEL", "Type")) if muid else None,
                operator=self._one(self._in(uid, "BUILD", "EconomicOperator")),
                composition=self._clean(comp),
                cathode=sub(cuid, "HAS_CATHODE"),
                anode=sub(cuid, "HAS_ANODE"),
                electrolyte=sub(cuid, "HAS_ELECTROLYTE"),
                static_performance=sub(muid, "HAS_STATIC_PERFORMANCE"),
                static_durability=sub(muid, "HAS_STATIC_DURABILITY"),
                carbon_footprint=sub(muid, "HAS_CARBON_FOOTPRINT"),
                certification=sub(muid, "HAS_CERTIFICATION"),
                circularity=sub(muid, "HAS_CIRCULARITY"),
                dynamic_performance=sub(uid, "HAS_DYNAMIC_PERFORMANCE") or {},
                dynamic_durability=sub(uid, "HAS_DYNAMIC_DURABILITY") or {},
                modules=sorted((self._clean(m) for m in self._out(uid, "HAS_MODULE")),
                               key=lambda m: m["index"]),
                location=self._one(self._out(uid, "LOCATED_AT")),
                pending_request=self._notif_dict(pending[0]) if pending else None,
                transfer=self._latest_transfer(uid),
            )

    def _latest_transfer(self, battery_uid):
        # un ordre remplacé (défi 2 : annulation / redirection) passe après son remplaçant
        orders = sorted(self._in(battery_uid, "FOR", "TransferOrder"),
                        key=lambda t: (not t.get("supersededBy"), t["createdAt"]), reverse=True)
        if not orders:
            return None
        t = orders[0]
        to = self._out(t["uid"], "TO")[0]
        frm = (self._out(t["uid"], "FROM") or [{}])[0]
        car = (self._out(t["uid"], "ASSIGNED_TO") or [{}])[0]   # défi 2
        return dict(self._clean(t), toUid=to["uid"], toName=to["name"], toAgreed=to.get("agreed"),
                    fromName=frm.get("name"), carrierName=car.get("name"))

    def get_history(self, battery_id):
        with self.lock:
            b = self._battery(battery_id)
            if b is None:
                return []
            return sorted((self._clean(e) for e in self._out(b["uid"], "HAS_EVENT")),
                          key=lambda e: e["at"], reverse=True)

    def _notif_dict(self, n):
        battery = self._out(n["uid"], "ABOUT")[0]
        sender = (self._in(n["uid"], "SENT") or [{}])[0]
        op = self._out(n["uid"], "ADDRESSED_TO")[0]
        return dict(self._clean(n), batteryId=battery["batteryId"],
                    senderName=sender.get("name"), operatorUid=op["uid"])

    def get_notification(self, notif_uid):
        with self.lock:
            n = self.nodes.get(notif_uid)
            return self._notif_dict(n) if n and n["_label"] == "Notification" else None

    def list_notifications(self, operator_uid):
        with self.lock:
            notifs = [self._notif_dict(n) for n in self._in(operator_uid, "ADDRESSED_TO", "Notification")]
            return sorted(notifs, key=lambda n: n["createdAt"], reverse=True)

    def list_actors(self, role):
        with self.lock:
            return sorted((self._clean(n) for n in self.nodes.values()
                           if n["_label"] == "Actor" and n.get("role") == role),
                          key=lambda a: a["name"])

    def list_transfers_to(self, center_uid):
        with self.lock:
            out = []
            for t in self._in(center_uid, "TO", "TransferOrder"):
                b = self._out(t["uid"], "FOR")[0]
                out.append(dict(self._clean(t), batteryId=b["batteryId"], status=b["status"]))
            return sorted(out, key=lambda t: t["createdAt"], reverse=True)

    # --- écritures (appelées par bp.workflow après contrôle des règles) ---------
    def create_status_request(self, battery_id, actor_uid, operator_uid, from_status,
                                                            requested_status, reason, diagnostic, destination_uid,
                                                            auto_logistics=False, pickup_date="", pickup_slot=""):
        with self.lock:
            b = self._battery(battery_id)
            uid = self._add("Notification", new_uid("NOTIF"), type="STATUS_CHANGE_REQUEST",
                            fromStatus=from_status, requestedStatus=requested_status,
                                                        reason=reason, diagnostic=diagnostic,
                                                        destinationUid=destination_uid, autoLogistics=bool(auto_logistics),
                                                        pickupDate=pickup_date or "", pickupSlot=pickup_slot or "",
                                                        state="PENDING", createdAt=now())
            self.rels += [[actor_uid, "SENT", uid], [uid, "ABOUT", b["uid"]],
                          [uid, "ADDRESSED_TO", operator_uid]]
            self._event(b["uid"], "FAULT_REPORTED", actor_uid,
                        f"Hors d'usage signalé : {reason} | {diagnostic}")
            return uid

    def apply_approval(self, notif_uid, battery_id, owner_uid, new_status, from_status,
                       destination_uid, comment):
        with self.lock:
            b = self._battery(battery_id)
            n = self.nodes[notif_uid]
            n.update(state="APPROVED", decidedAt=now(), decidedBy=self.nodes[owner_uid]["name"],
                     comment=comment)
            b["status"] = new_status
            self._event(b["uid"], "STATUS_CHANGED", owner_uid, f"{from_status} → {new_status}")
            loc = (self._out(b["uid"], "LOCATED_AT") or [None])[0]
            t = self._add("TransferOrder", new_uid("TO"), state="ORDERED", createdAt=now())
            self.rels += [[t, "FOR", b["uid"]], [t, "TO", destination_uid], [notif_uid, "TRIGGERED", t]]
            if loc:
                self.rels.append([t, "FROM", loc["uid"]])
            self._event(b["uid"], "TRANSFER_ORDERED", owner_uid,
                        f"Transfert vers {self.nodes[destination_uid]['name']} ({t})")

    def apply_rejection(self, notif_uid, battery_id, owner_uid, comment):
        with self.lock:
            b = self._battery(battery_id)
            self.nodes[notif_uid].update(state="REJECTED", decidedAt=now(),
                                         decidedBy=self.nodes[owner_uid]["name"], comment=comment)
            self._event(b["uid"], "REQUEST_REJECTED", owner_uid, f"Demande refusée : {comment}")

    def apply_reception(self, order_uid, battery_id, center_uid):
        with self.lock:
            b = self._battery(battery_id)
            self.nodes[order_uid].update(state="RECEIVED", receivedAt=now())
            self.rels = [r for r in self.rels if not (r[0] == b["uid"] and r[1] == "LOCATED_AT")]
            self.rels.append([b["uid"], "LOCATED_AT", center_uid])
            self._event(b["uid"], "RECEIVED", center_uid, f"Batterie réceptionnée (ordre {order_uid})")

    # --- Défi 2 : logistique du transfert -------------------------------------------
    def get_actor(self, uid):
        with self.lock:
            n = self.nodes.get(uid)
            return self._clean(n) if n and n["_label"] == "Actor" else None

    def _transfer_dict(self, t):
        b = self._out(t["uid"], "FOR")[0]
        to = self._out(t["uid"], "TO")[0]
        frm = (self._out(t["uid"], "FROM") or [{}])[0]
        car = (self._out(t["uid"], "ASSIGNED_TO") or [{}])[0]
        return dict(self._clean(t), batteryId=b["batteryId"], batteryStatus=b["status"],
                    toUid=to["uid"], toName=to["name"], toAgreed=to.get("agreed"),
                    fromUid=frm.get("uid"), fromName=frm.get("name"),
                    carrierUid=car.get("uid"), carrierName=car.get("name"))

    def get_transfer(self, order_uid):
        with self.lock:
            t = self.nodes.get(order_uid)
            return self._transfer_dict(t) if t and t["_label"] == "TransferOrder" else None

    def list_transfers(self, carrier_uid=None):
        with self.lock:
            out = [self._transfer_dict(t) for t in self.nodes.values() if t["_label"] == "TransferOrder"]
            if carrier_uid:
                out = [t for t in out if t["carrierUid"] == carrier_uid]
            return sorted(out, key=lambda t: t["createdAt"], reverse=True)

    def create_transfer(self, battery_id, from_uid, to_uid, props, carrier_uid=None):
        with self.lock:
            b = self._battery(battery_id)
            uid = self._add("TransferOrder", new_uid("TO"), createdAt=now(), **props)
            self.rels += [[uid, "FOR", b["uid"]], [uid, "TO", to_uid]]
            if from_uid:
                self.rels.append([uid, "FROM", from_uid])
            if carrier_uid:
                self.rels.append([uid, "ASSIGNED_TO", carrier_uid])
            return uid

    def update_transfer(self, order_uid, props, carrier_uid=None, location_uid=None):
        """Met à jour l'ordre ; change le transporteur affecté et/ou la localisation de la batterie."""
        with self.lock:
            self.nodes[order_uid].update(props)
            if carrier_uid:
                self.rels = [r for r in self.rels if not (r[0] == order_uid and r[1] == "ASSIGNED_TO")]
                self.rels.append([order_uid, "ASSIGNED_TO", carrier_uid])
            if location_uid:
                b = self._out(order_uid, "FOR")[0]
                self.rels = [r for r in self.rels if not (r[0] == b["uid"] and r[1] == "LOCATED_AT")]
                self.rels.append([b["uid"], "LOCATED_AT", location_uid])

    def add_transfer_step(self, order_uid, actor_uid, step):
        with self.lock:
            uid = self._add("LogisticsStep", new_uid("STEP"), **step)
            self.rels += [[order_uid, "HAS_STEP", uid], [actor_uid, "PERFORMED", uid]]
            return uid

    def get_transfer_steps(self, order_uid):
        with self.lock:
            return sorted((self._clean(s) for s in self._out(order_uid, "HAS_STEP")),
                          key=lambda s: s["seq"])

    def add_message(self, to_uid, props):
        with self.lock:
            uid = self._add("Message", new_uid("MSG"), read=False, at=now(), **props)
            self.rels.append([uid, "SENT_TO", to_uid])
            return uid

    def list_messages(self, actor_uid):
        with self.lock:
            return sorted((self._clean(m) for m in self._in(actor_uid, "SENT_TO", "Message")),
                          key=lambda m: m["at"], reverse=True)

    def mark_messages_read(self, actor_uid):
        with self.lock:
            for m in self._in(actor_uid, "SENT_TO", "Message"):
                m["read"] = True

    # --- Défi 1 : télémétrie BMS -------------------------------------------------
    def record_telemetry(self, frame, update_current=True):
        with self.lock:
            b = self._battery(frame["batteryId"])
            props = dict(at=frame["at"], source=frame["source"],
                         moduleIndexes=[m["index"] for m in frame["modules"]],
                         resistances=[m["r"] for m in frame["modules"]])
            if frame["modules"] and all(m["t"] is not None for m in frame["modules"]):
                props["temperatures"] = [m["t"] for m in frame["modules"]]
            props.update({k: frame[k] for k in ("soh", "soc") if frame[k] is not None})
            uid = self._add("TelemetryReading", new_uid("TEL"), **props)
            self.rels.append([b["uid"], "HAS_TELEMETRY", uid])
            if not update_current:
                return uid
            by_index = {m["index"]: m for m in self._out(b["uid"], "HAS_MODULE")}
            for m in frame["modules"]:
                node = by_index[m["index"]]
                node.update(internalResistance_mOhm=m["r"], measuredAt=frame["at"])
                if m["t"] is not None:
                    node["temperature_C"] = m["t"]
            dp = (self._out(b["uid"], "HAS_DYNAMIC_PERFORMANCE") or [None])[0]
            if dp is not None and (frame["soh"] is not None or frame["soc"] is not None):
                dp.update({k: frame[k] for k in ("soh", "soc") if frame[k] is not None},
                          measuredAt=frame["at"])
            return uid

    def get_telemetry(self, battery_id, limit=50):
        """Relevés BMS du plus ancien au plus récent (les `limit` derniers)."""
        with self.lock:
            b = self._battery(battery_id)
            if b is None:
                return []
            out = sorted((self._clean(r) for r in self._out(b["uid"], "HAS_TELEMETRY")),
                         key=lambda r: r["at"])
            return out[-limit:]

    def add_event(self, battery_id, etype, actor_uid, details):
        with self.lock:
            self._event(self._battery(battery_id)["uid"], etype, actor_uid, details)

    # --- Défi 3 : orientation de fin de vie ----------------------------------------
    def record_orientation(self, battery_id, actor_uid, choice, recommended, comment):
        with self.lock:
            b = self._battery(battery_id)
            uid = self._add("OrientationDecision", new_uid("ORI"), choice=choice,
                            recommended=recommended, comment=comment, at=now(),
                            decidedBy=self.nodes[actor_uid]["name"])
            self.rels += [[b["uid"], "HAS_ORIENTATION", uid], [actor_uid, "DECIDED", uid]]
            details = f"Orientation : {choice}" + (f" (recommandé : {recommended})"
                                                    if choice != recommended else " (conforme à la recommandation)")
            self._event(b["uid"], "ORIENTATION_DECIDED", actor_uid,
                        details + (f". {comment}" if comment else ""))
            return uid

    def get_orientation(self, battery_id):
        with self.lock:
            b = self._battery(battery_id)
            if b is None:
                return None
            ds = sorted(self._out(b["uid"], "HAS_ORIENTATION"), key=lambda d: d["at"])
            return self._clean(ds[-1]) if ds else None
