"""Base de données en mémoire (même modèle de graphe que Neo4j).

Permet de faire tourner la démo sans Neo4j. Les données sont partagées entre
tous les navigateurs connectés au même serveur, et remises à zéro au redémarrage.
"""
import copy
import json
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
        orders = sorted(self._in(battery_uid, "FOR", "TransferOrder"),
                        key=lambda t: t["createdAt"], reverse=True)
        if not orders:
            return None
        t = orders[0]
        to = self._out(t["uid"], "TO")[0]
        frm = (self._out(t["uid"], "FROM") or [{}])[0]
        return dict(self._clean(t), toUid=to["uid"], toName=to["name"], toAgreed=to.get("agreed"),
                    fromName=frm.get("name"))

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

    # --- défi 3 : demandes du marché et décisions ------------------------------
    def list_demands(self):
        with self.lock:
            return sorted((self._clean(n) for n in self.nodes.values()
                           if n["_label"] == "MarketDemand"),
                          key=lambda d: (d.get("option", ""), d.get("title", "")))

    def set_demand_active(self, demand_uid, active):
        with self.lock:
            n = self.nodes.get(demand_uid)
            if n and n["_label"] == "MarketDemand":
                n["active"] = bool(active)

    def add_demand(self, center_uid, title, option, partner, chemistries, min_soce, urgency, quantity=1, location="France"):
        with self.lock:
            uid = new_uid("DEM")
            self._add("MarketDemand", uid, title=title, option=option, partner=partner,
                      chemistries=chemistries, minSoce=min_soce, urgency=urgency,
                      quantity=quantity, location=location, active=True)
            self.rels.append([uid, "OFFERED_TO", center_uid])
            return uid

    def delete_demand(self, demand_uid):
        with self.lock:
            if demand_uid in self.nodes:
                del self.nodes[demand_uid]
                self.rels = [r for r in self.rels if r[0] != demand_uid and r[2] != demand_uid]

    def get_center_policy(self, center_uid):
        with self.lock:
            n = self.nodes.get(center_uid) or {}
            return dict(use_market=n.get("policyMarket", True),
                        use_hierarchy=n.get("policyHierarchy", True))

    def set_center_policy(self, center_uid, use_market, use_hierarchy):
        with self.lock:
            n = self.nodes.get(center_uid)
            if n:
                n["policyMarket"] = bool(use_market)
                n["policyHierarchy"] = bool(use_hierarchy)

    def get_decisions(self, battery_id):
        with self.lock:
            b = self._battery(battery_id)
            if b is None:
                return []
            decs = []
            for d in self._out(b["uid"], "HAS_DECISION", "Decision"):
                dec = self._clean(d)
                # chercher la demande du marché liée
                fulfilled = self._out(d["uid"], "FULFILLS", "MarketDemand")
                if fulfilled:
                    dec["demandTitle"] = fulfilled[0].get("title")
                decs.append(dec)
            return sorted(decs, key=lambda d: d.get("at", ""), reverse=True)

    def record_decision(self, battery_id, center_uid, chosen, comment, result):
        """Enregistre la décision du centre de tri (défi 3)."""
        with self.lock:
            from .decision import OPTION_FR
            b = self._battery(battery_id)
            overridden = chosen != result["recommendation"]
            demand_uid = None
            opts = {o["option"]: o for o in result["options"]}
            if opts[chosen]["demands"]:
                demand_uid = opts[chosen]["demands"][0]["uid"]
            uid = new_uid("DEC")
            self._add("Decision", uid,
                      recommendation=result["recommendation"], chosen=chosen,
                      overridden=overridden, comment=(comment or "").strip(),
                      scores=json.dumps({o["option"]: o["score"] for o in result["options"]}),
                      justification=result["justification"],
                      weights=json.dumps(result["weights"]),
                      marketDriven=result["market_driven"],
                      policyMarket=result.get("priorities", {}).get("use_market", True),
                      policyHierarchy=result.get("priorities", {}).get("use_hierarchy", True),
                      at=now(), decidedBy=self.nodes[center_uid]["name"])
            self.rels.append([b["uid"], "HAS_DECISION", uid])
            self.rels.append([center_uid, "MADE", uid])
            if demand_uid and demand_uid in self.nodes:
                self.rels.append([uid, "FULFILLS", demand_uid])
            detail = f"Décision : {chosen} (recommandé : {result['recommendation']})"
            if comment and comment.strip():
                detail += f" - {comment.strip()}"
            self._event(b["uid"], "DECISION_RECORDED", center_uid, detail)
            return uid

    # --- écritures (appelées par bp.workflow après contrôle des règles) ---------
    def create_status_request(self, battery_id, actor_uid, operator_uid, from_status,
                              requested_status, reason, diagnostic):
        with self.lock:
            b = self._battery(battery_id)
            uid = self._add("Notification", new_uid("NOTIF"), type="STATUS_CHANGE_REQUEST",
                            fromStatus=from_status, requestedStatus=requested_status,
                            reason=reason, diagnostic=diagnostic, state="PENDING", createdAt=now())
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
