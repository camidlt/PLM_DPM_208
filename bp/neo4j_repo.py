"""Accès Neo4j : mêmes méthodes que MemoryRepo, en Cypher.

Si le dump fourni par les organisateurs utilise d'autres noms de propriétés ou
de relations, c'est ici (et seulement ici) qu'il faut adapter les requêtes.
"""
import json
import uuid
from datetime import datetime

from neo4j import GraphDatabase

from . import config, seed_data, telemetry


def now():
    return datetime.now().isoformat(timespec="seconds")


def new_uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


PASSPORT_QUERY = """
MATCH (b:BatteryInstance {batteryId: $id})
OPTIONAL MATCH (m:Model)-[:HAS_BATTERY_INSTANCE]->(b)
OPTIONAL MATCH (t:Type)-[:HAS_MODEL]->(m)
OPTIONAL MATCH (eo:EconomicOperator)-[:BUILD]->(b)
OPTIONAL MATCH (m)-[:HAS_COMPOSITION]->(c:Composition)
OPTIONAL MATCH (c)-[:HAS_CATHODE]->(ca)
OPTIONAL MATCH (c)-[:HAS_ANODE]->(an)
OPTIONAL MATCH (c)-[:HAS_ELECTROLYTE]->(el)
OPTIONAL MATCH (m)-[:HAS_STATIC_PERFORMANCE]->(sp)
OPTIONAL MATCH (m)-[:HAS_STATIC_DURABILITY]->(sd)
OPTIONAL MATCH (m)-[:HAS_CARBON_FOOTPRINT]->(cf)
OPTIONAL MATCH (m)-[:HAS_CERTIFICATION]->(ce)
OPTIONAL MATCH (m)-[:HAS_CIRCULARITY]->(ci)
OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
OPTIONAL MATCH (b)-[:HAS_DYNAMIC_DURABILITY]->(dd)
OPTIONAL MATCH (b)-[:LOCATED_AT]->(loc:Actor)
RETURN b{.*} AS battery, m{.*} AS model, t{.*} AS type, eo{.*} AS operator,
       c{.*} AS composition, ca{.*} AS cathode, an{.*} AS anode, el{.*} AS electrolyte,
       sp{.*} AS static_performance, sd{.*} AS static_durability, cf{.*} AS carbon_footprint,
       ce{.*} AS certification, ci{.*} AS circularity, dp{.*} AS dynamic_performance,
       dd{.*} AS dynamic_durability, loc{.*} AS location
LIMIT 1
"""

NOTIF_RETURN = """
MATCH (n)-[:ABOUT]->(b:BatteryInstance)
MATCH (n)-[:ADDRESSED_TO]->(eo:EconomicOperator)
OPTIONAL MATCH (s:Actor)-[:SENT]->(n)
OPTIONAL MATCH (dest:Actor {uid: n.destinationUid})
RETURN n{.*, batteryId: b.batteryId, senderUid: s.uid, senderName: s.name, operatorUid: eo.uid,
         destinationName: dest.name} AS n
"""

# Ordre de transfert avec ses acteurs (départ, destination, transporteur affecté)
TRANSFER_RETURN = """
MATCH (t)-[:FOR]->(b:BatteryInstance)
MATCH (t)-[:TO]->(d:Actor)
OPTIONAL MATCH (t)-[:FROM]->(f:Actor)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(c:Actor)
RETURN t{.*, batteryId: b.batteryId, batteryStatus: b.status, toUid: d.uid, toName: d.name,
         toAgreed: d.agreed, fromUid: f.uid, fromName: f.name, carrierUid: c.uid,
         carrierName: c.name} AS t
"""

EVENT_CREATE = """
WITH b, actor
CREATE (e:Event {uid: $evt_uid, type: $etype, at: $at, actorName: actor.name, details: $details})
CREATE (b)-[:HAS_EVENT]->(e)
CREATE (actor)-[:PERFORMED]->(e)
"""


class Neo4jRepo:
    backend = "neo4j"

    def __init__(self, uri=None, user=None, password=None, database=None):
        self.driver = GraphDatabase.driver(uri or config.NEO4J_URI,
                                           auth=(user or config.NEO4J_USER,
                                                 password or config.NEO4J_PASSWORD))
        self.database = database or config.NEO4J_DATABASE
        self.driver.verify_connectivity()

    def _read(self, query, **params):
        records, _, _ = self.driver.execute_query(query, params, database_=self.database,
                                                  routing_="r")
        return records

    def _write(self, query, **params):
        records, _, _ = self.driver.execute_query(query, params, database_=self.database)
        return records

    # --- initialisation -------------------------------------------------------
    def reset(self):
        """Efface les nœuds de démo puis recharge le jeu de données."""
        self._write("MATCH (n) WHERE n:Notification OR n:TransferOrder OR n:Event OR n:Decision "
                    "OR n:Measurement OR n:Alert OR n:LogisticsStep OR n:Message OR n:TelemetryReading "
                    "DETACH DELETE n")
        uids = [uid for _, uid, _ in seed_data.NODES]
        self._write("MATCH (n) WHERE n.uid IN $uids DETACH DELETE n", uids=uids)
        for stmt in seed_data.cypher_statements():
            self._write(stmt)

    # --- défi 1 : télémétrie BMS ------------------------------------------------
    def record_telemetry(self, battery_id, readings, ts=None, source="BMS", soh=None, soc=None):
        ts = ts or now()
        mods = {r["m"]["index"]: r["m"] for r in self._read(
            "MATCH (:BatteryInstance {batteryId: $id})-[:HAS_MODULE]->(m:Module) "
            "RETURN m{.*, index: coalesce(m.index, m.position)} AS m", id=battery_id)}
        if not mods:
            raise telemetry.TelemetryError(f"Batterie {battery_id} inconnue.")
        # Un nœud (:TelemetryReading) par trame : l'historique complet reste dans le graphe
        props = dict(uid=new_uid("TEL"), at=ts, source=source,
                     moduleIndexes=[rd["index"] for rd in readings],
                     resistances=[rd["r"] for rd in readings],
                     temperatures=[rd["t"] for rd in readings])
        props.update({k: v for k, v in (("soh", soh), ("soc", soc)) if v is not None})
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            CREATE (b)-[:HAS_TELEMETRY]->(:TelemetryReading $props)
            WITH b
            OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
            FOREACH (_ IN CASE WHEN dp IS NULL OR ($soh IS NULL AND $soc IS NULL) THEN [] ELSE [1] END |
              SET dp.soh = coalesce($soh, dp.soh), dp.soc = coalesce($soc, dp.soc), dp.measuredAt = $ts)
            SET b.lastTelemetryAt = $ts
            """, bid=battery_id, props=props, soh=soh, soc=soc, ts=ts)
        raised = []
        for rd in readings:
            m = mods.get(rd["index"])
            if m is None:
                continue
            rmax = m.get("maxInternalResistance_mOhm") or 2.0
            was = m.get("health")
            health, over = telemetry.next_health(rd["r"], rmax, m.get("consecutiveOver") or 0)
            msg = telemetry.alert_message(rd["index"], rd["r"], rmax) \
                if health == "CRITICAL" and was != "CRITICAL" else None
            self._write("""
                MATCH (b:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m:Module {uid: $muid})
                SET m.internalResistance_mOhm = $r, m.measuredAt = $ts, m.health = $health,
                    m.consecutiveOver = $over, m.lastVoltage = $v, m.lastCurrent = $i,
                    m.lastTemperature = $t, m.source = $src, b.lastTelemetryAt = $ts
                CREATE (m)-[:HAS_MEASUREMENT]->(:Measurement {ts: $ts, internalResistance_mOhm: $r,
                        voltage: $v, current: $i, temperature: $t})
                WITH b, m
                FOREACH (_ IN CASE WHEN $msg IS NULL THEN [] ELSE [1] END |
                  CREATE (m)-[:RAISED]->(:Alert {uid: $auid, level: 'CRITICAL', at: $ts, open: true,
                          module: m.index, value: $r, threshold: $rmax, message: $msg})
                  CREATE (b)-[:HAS_EVENT]->(:Event {uid: $euid, type: 'BMS_ALERT', at: $ts,
                          actorName: 'BMS (' + $src + ')', details: $msg}))
                """, bid=battery_id, muid=m["uid"], r=rd["r"], ts=ts, health=health, over=over,
                v=rd["v"], i=rd["i"], t=rd["t"], src=source, msg=msg, rmax=rmax,
                auid=new_uid("ALERT"), euid=new_uid("EVT"))
            if msg:
                raised.append(msg)
        return raised

    def get_telemetry(self, battery_id, limit=60):
        rows = self._read("""
            MATCH (b:BatteryInstance {batteryId: $id})-[:HAS_MODULE]->(m:Module)
            OPTIONAL MATCH (m)-[:RAISED]->(a:Alert)
            RETURN b.lastTelemetryAt AS last, coalesce(m.index, m.position) AS index,
                   m{.*} AS m, collect(a{.*}) AS alerts
            ORDER BY index""", id=battery_id)
        if not rows:
            return None
        # courbes : les derniers relevés (:TelemetryReading), du plus ancien au plus récent
        readings = list(reversed([r["r"] for r in self._read("""
            MATCH (:BatteryInstance {batteryId: $id})-[:HAS_TELEMETRY]->(r:TelemetryReading)
            RETURN r{.at, .moduleIndexes, .resistances, .temperatures} AS r
            ORDER BY r.at DESC LIMIT $limit""", id=battery_id, limit=limit)]))
        series = {}
        for rd in readings:
            temps = rd.get("temperatures") or []
            for k, idx in enumerate(rd.get("moduleIndexes") or []):
                series.setdefault(idx, []).append(dict(
                    ts=rd["at"], r=rd["resistances"][k], v=None, i=None,
                    t=temps[k] if k < len(temps) else None))
        mods, alerts = [], []
        for row in rows:
            row = dict(row.data(), points=series.get(row["index"], []))
            m = row["m"]
            r = m.get("internalResistance_mOhm", m.get("lastResistance"))
            rmax = m.get("maxInternalResistance_mOhm")
            mods.append(dict(index=row["index"], r=r, rmax=rmax,
                             health=m.get("health") or telemetry.health_from_value(r, rmax),
                             t=m.get("lastTemperature"), v=m.get("lastVoltage"),
                             at=m.get("measuredAt"), points=row["points"]))
            alerts += row["alerts"]
        extra = self._read("""
            MATCH (b:BatteryInstance {batteryId: $id})
            OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
            OPTIONAL MATCH (b)-[:HAS_TELEMETRY]->(r:TelemetryReading)
            RETURN dp.soh AS soh, dp.soc AS soc, count(r) AS readings""", id=battery_id)[0]
        return dict(batteryId=battery_id, lastTelemetryAt=rows[0]["last"], modules=mods,
                    soh=extra["soh"], soc=extra["soc"], readings=extra["readings"],
                    alerts=sorted(alerts, key=lambda a: a.get("at", ""), reverse=True))

    def count_readings(self, battery_id):
        return self._read("MATCH (:BatteryInstance {batteryId: $id})-[:HAS_TELEMETRY]->(r) "
                          "RETURN count(r) AS n", id=battery_id)[0]["n"]

    # --- lectures ----------------------------------------------------------------
    def list_batteries(self):
        return [r.data() for r in self._read("""
            MATCH (b:BatteryInstance)
            OPTIONAL MATCH (m:Model)-[:HAS_BATTERY_INSTANCE]->(b)
            OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
            OPTIONAL MATCH (b)-[:LOCATED_AT]->(l:Actor)
            RETURN b.batteryId AS batteryId, b.status AS status, m.name AS model,
                   coalesce(dp.soh, dp.soce) AS soh, coalesce(l.name, b.manufacturingPlace, 'Non assigné') AS location
            ORDER BY batteryId""")]

    def get_passport(self, battery_id):
        rows = self._read(PASSPORT_QUERY, id=battery_id)
        if not rows:
            return None
        p = rows[0].data()
        p["dynamic_performance"] = p["dynamic_performance"] or {}
        if "soh" not in p["dynamic_performance"] and "soce" in p["dynamic_performance"]:
            p["dynamic_performance"]["soh"] = p["dynamic_performance"]["soce"]
        p["dynamic_durability"] = p["dynamic_durability"] or {}
        raw_modules = [r["m"] for r in self._read(
            "MATCH (:BatteryInstance {batteryId: $id})-[:HAS_MODULE]->(m:Module) "
            "RETURN m{.*} AS m ORDER BY coalesce(m.index, m.position)", id=battery_id)]
        for mod in raw_modules:
            if "index" not in mod and "position" in mod:
                mod["index"] = mod["position"]
            if "internalResistance_mOhm" not in mod and "lastResistance" in mod:
                mod["internalResistance_mOhm"] = mod["lastResistance"]
            elif "internalResistance_mOhm" not in mod and "initialInternalResistance" in mod:
                mod["internalResistance_mOhm"] = mod["initialInternalResistance"]
            mod.setdefault("health", telemetry.health_from_value(
                mod.get("internalResistance_mOhm"), mod.get("maxInternalResistance_mOhm")))
        p["modules"] = raw_modules
        pending = self._read(
            "MATCH (n:Notification {state: 'PENDING'})-[:ABOUT]->(:BatteryInstance {batteryId: $id}) "
            "WITH n LIMIT 1" + NOTIF_RETURN, id=battery_id)
        p["pending_request"] = pending[0]["n"] if pending else None
        transfer = self._read(
            "MATCH (t:TransferOrder)-[:FOR]->(:BatteryInstance {batteryId: $id}) "
            "WITH t ORDER BY t.supersededBy IS NULL DESC, t.createdAt DESC LIMIT 1" + TRANSFER_RETURN, id=battery_id)
        p["transfer"] = transfer[0]["t"] if transfer else None
        return p

    def get_history(self, battery_id):
        return [r["e"] for r in self._read(
            "MATCH (:BatteryInstance {batteryId: $id})-[:HAS_EVENT]->(e:Event) "
            "RETURN e{.*} AS e ORDER BY e.at DESC", id=battery_id)]

    def get_notification(self, notif_uid):
        rows = self._read("MATCH (n:Notification {uid: $uid})" + NOTIF_RETURN, uid=notif_uid)
        return rows[0]["n"] if rows else None

    def list_notifications(self, operator_uid):
        return [r["n"] for r in self._read(
            "MATCH (n:Notification)-[:ADDRESSED_TO]->(:EconomicOperator {uid: $op})"
            + NOTIF_RETURN + " ORDER BY n.createdAt DESC", op=operator_uid)]

    def list_actors(self, role):
        return [r["a"] for r in self._read(
            "MATCH (a:Actor {role: $role}) RETURN a{.*} AS a ORDER BY a.name", role=role)]

    def list_transfers_to(self, center_uid):
        rows = self._read("MATCH (t:TransferOrder)-[:TO]->(:Actor {uid: $uid}) WITH t"
                          + TRANSFER_RETURN + " ORDER BY t.createdAt DESC", uid=center_uid)
        return [dict(r["t"], status=r["t"]["batteryStatus"]) for r in rows]

    # --- défi 2 : acteurs, transferts, étapes signées, messages ---------------------
    def get_actor(self, uid):
        rows = self._read("MATCH (a:Actor {uid: $uid}) RETURN a{.*} AS a", uid=uid)
        return rows[0]["a"] if rows else None

    def add_event(self, battery_id, etype, actor_uid, details):
        self._write("MATCH (b:BatteryInstance {batteryId: $bid}) MATCH (actor:Actor {uid: $actor_uid})"
                    + EVENT_CREATE, bid=battery_id, actor_uid=actor_uid, evt_uid=new_uid("EVT"),
                    etype=etype, at=now(), details=details)

    def get_transfer(self, order_uid):
        rows = self._read("MATCH (t:TransferOrder {uid: $uid}) WITH t" + TRANSFER_RETURN, uid=order_uid)
        return rows[0]["t"] if rows else None

    def list_transfers(self, carrier_uid=None):
        if carrier_uid:
            q = "MATCH (t:TransferOrder)-[:ASSIGNED_TO]->(:Actor {uid: $uid}) WITH t"
        else:
            q = "MATCH (t:TransferOrder) WITH t"
        return [r["t"] for r in self._read(q + TRANSFER_RETURN + " ORDER BY t.createdAt DESC",
                                           uid=carrier_uid)]

    def create_transfer(self, battery_id, from_uid, to_uid, props, carrier_uid=None):
        uid = new_uid("TO")
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (dest:Actor {uid: $to_uid})
            CREATE (t:TransferOrder $props)
            SET t.uid = $uid, t.createdAt = $at
            CREATE (t)-[:FOR]->(b)
            CREATE (t)-[:TO]->(dest)
            WITH t
            OPTIONAL MATCH (f:Actor {uid: $from_uid})
            OPTIONAL MATCH (c:Actor {uid: $carrier_uid})
            FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | CREATE (t)-[:FROM]->(f))
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | CREATE (t)-[:ASSIGNED_TO]->(c))
            """, bid=battery_id, to_uid=to_uid, props=props, uid=uid, at=now(),
            from_uid=from_uid or "", carrier_uid=carrier_uid or "")
        return uid

    def update_transfer(self, order_uid, props, carrier_uid=None, location_uid=None):
        self._write("MATCH (t:TransferOrder {uid: $uid}) SET t += $props", uid=order_uid, props=props)
        if carrier_uid:
            self._write("""
                MATCH (t:TransferOrder {uid: $uid})
                OPTIONAL MATCH (t)-[old:ASSIGNED_TO]->()
                DELETE old
                WITH DISTINCT t
                MATCH (c:Actor {uid: $carrier}) CREATE (t)-[:ASSIGNED_TO]->(c)
                """, uid=order_uid, carrier=carrier_uid)
        if location_uid:
            self._write("""
                MATCH (t:TransferOrder {uid: $uid})-[:FOR]->(b:BatteryInstance)
                OPTIONAL MATCH (b)-[old:LOCATED_AT]->()
                DELETE old
                WITH DISTINCT b
                MATCH (a:Actor {uid: $loc}) CREATE (b)-[:LOCATED_AT]->(a)
                """, uid=order_uid, loc=location_uid)

    def add_transfer_step(self, order_uid, actor_uid, step):
        uid = new_uid("STEP")
        self._write("""
            MATCH (t:TransferOrder {uid: $order}) MATCH (a:Actor {uid: $actor})
            CREATE (s:LogisticsStep $props) SET s.uid = $uid
            CREATE (t)-[:HAS_STEP]->(s)
            CREATE (a)-[:PERFORMED]->(s)
            """, order=order_uid, actor=actor_uid, props=step, uid=uid)
        return uid

    def get_transfer_steps(self, order_uid):
        return [r["s"] for r in self._read(
            "MATCH (:TransferOrder {uid: $uid})-[:HAS_STEP]->(s:LogisticsStep) "
            "RETURN s{.*} AS s ORDER BY s.seq", uid=order_uid)]

    def add_message(self, to_uid, props):
        uid = new_uid("MSG")
        self._write("""
            MATCH (a:Actor {uid: $to})
            CREATE (m:Message $props) SET m.uid = $uid, m.read = false, m.at = $at
            CREATE (m)-[:SENT_TO]->(a)
            """, to=to_uid, props=props, uid=uid, at=now())
        return uid

    def list_messages(self, actor_uid):
        return [r["m"] for r in self._read(
            "MATCH (m:Message)-[:SENT_TO]->(:Actor {uid: $uid}) RETURN m{.*} AS m ORDER BY m.at DESC",
            uid=actor_uid)]

    def unread_count(self, actor_uid):
        return self._read("MATCH (m:Message {read: false})-[:SENT_TO]->(:Actor {uid: $uid}) "
                          "RETURN count(m) AS n", uid=actor_uid)[0]["n"]

    def mark_messages_read(self, actor_uid):
        self._write("MATCH (m:Message {read: false})-[:SENT_TO]->(:Actor {uid: $uid}) SET m.read = true",
                    uid=actor_uid)

    # --- défi 3 : demandes du marché et décisions ------------------------------
    def list_demands(self):
        return [r["d"] for r in self._read(
            "MATCH (d:MarketDemand) RETURN d{.*} AS d ORDER BY d.option, d.title")]

    def set_demand_active(self, demand_uid, active):
        self._write("MATCH (d:MarketDemand {uid: $uid}) SET d.active = $active",
                     uid=demand_uid, active=bool(active))

    def add_demand(self, center_uid, title, option, partner, chemistries, min_soce, urgency, quantity=1, location="France"):
        uid = new_uid("DEM")
        self._write("""
            MATCH (actor:Actor {uid: $center_uid})
            CREATE (d:MarketDemand {uid: $uid, title: $title, option: $option, partner: $partner,
                    chemistries: $chemistries, minSoce: $min_soce, urgency: $urgency,
                    quantity: $quantity, location: $location, active: true})
            CREATE (d)-[:OFFERED_TO]->(actor)
            """, center_uid=center_uid, uid=uid, title=title, option=option, partner=partner,
            chemistries=chemistries, min_soce=min_soce, urgency=urgency, quantity=quantity, location=location)
        return uid

    def delete_demand(self, demand_uid):
        self._write("MATCH (d:MarketDemand {uid: $uid}) DETACH DELETE d", uid=demand_uid)

    def get_center_policy(self, center_uid):
        rows = self._read("MATCH (c:Actor {uid: $uid}) RETURN coalesce(c.policyMarket, true) AS m, "
                          "coalesce(c.policyHierarchy, true) AS h", uid=center_uid)
        return dict(use_market=rows[0]["m"], use_hierarchy=rows[0]["h"]) if rows else \
            dict(use_market=True, use_hierarchy=True)

    def set_center_policy(self, center_uid, use_market, use_hierarchy):
        self._write("MATCH (c:Actor {uid: $uid}) SET c.policyMarket = $m, c.policyHierarchy = $h",
                    uid=center_uid, m=bool(use_market), h=bool(use_hierarchy))

    def get_decisions(self, battery_id):
        return [r["d"] for r in self._read("""
            MATCH (:BatteryInstance {batteryId: $id})-[:HAS_DECISION]->(d:Decision)
            OPTIONAL MATCH (d)-[:FULFILLS]->(m:MarketDemand)
            RETURN d{.*, demandTitle: m.title} AS d ORDER BY d.at DESC, coalesce(d.ts, 0) DESC""",
            id=battery_id)]

    def record_decision(self, battery_id, center_uid, chosen, comment, result):
        """Enregistre la décision du centre de tri (défi 3)."""
        overridden = chosen != result["recommendation"]
        demand_uid = None
        opts = {o["option"]: o for o in result["options"]}
        if opts[chosen]["demands"]:
            demand_uid = opts[chosen]["demands"][0]["uid"]
        props = dict(recommendation=result["recommendation"], chosen=chosen, overridden=overridden,
                     comment=(comment or "").strip(),
                     scores=json.dumps({o["option"]: o["score"] for o in result["options"]}),
                     justification=result["justification"], weights=json.dumps(result["weights"]),
                     marketDriven=result["market_driven"],
                     policyMarket=result.get("priorities", {}).get("use_market", True),
                     policyHierarchy=result.get("priorities", {}).get("use_hierarchy", True))
        uid = f"DEC-{uuid.uuid4().hex[:8].upper()}"
        detail = f"Décision : {chosen} (recommandé : {result['recommendation']})" + (
            f" - {props['comment']}" if props["comment"] else "")
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $center_uid})
            CREATE (d:Decision {uid: $uid, at: $at, ts: timestamp(), decidedBy: actor.name})
            SET d += $props
            CREATE (b)-[:HAS_DECISION]->(d)
            CREATE (actor)-[:MADE]->(d)
            WITH b, actor, d
            OPTIONAL MATCH (m:MarketDemand {uid: $demand_uid})
            FOREACH (_ IN CASE WHEN m IS NULL THEN [] ELSE [1] END | CREATE (d)-[:FULFILLS]->(m))
            WITH b, actor
            CREATE (e:Event {uid: $evt_uid, type: 'DECISION_RECORDED', at: $at, ts: timestamp(),
                             actorName: actor.name, details: $details})
            CREATE (b)-[:HAS_EVENT]->(e)
            CREATE (actor)-[:PERFORMED]->(e)
            """, bid=battery_id, center_uid=center_uid, uid=uid, at=now(), props=props,
            demand_uid=demand_uid, evt_uid=f"EVT-{uuid.uuid4().hex[:8].upper()}", details=detail)
        return uid

    # --- écritures --------------------------------------------------------------
    def create_status_request(self, battery_id, actor_uid, operator_uid, from_status,
                              requested_status, reason, diagnostic, destination_uid="",
                              auto_logistics=False, pickup_date="", pickup_slot=""):
        uid = new_uid("NOTIF")
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $actor_uid})
            MATCH (eo:EconomicOperator {uid: $op_uid})
            CREATE (n:Notification {uid: $uid, type: 'STATUS_CHANGE_REQUEST',
                    fromStatus: $from_status, requestedStatus: $requested, reason: $reason,
                    diagnostic: $diagnostic, destinationUid: $dest, autoLogistics: $auto,
                    pickupDate: $pdate, pickupSlot: $pslot, state: 'PENDING', createdAt: $at})
            CREATE (actor)-[:SENT]->(n)
            CREATE (n)-[:ABOUT]->(b)
            CREATE (n)-[:ADDRESSED_TO]->(eo)
            """ + EVENT_CREATE,
            bid=battery_id, actor_uid=actor_uid, op_uid=operator_uid, uid=uid,
            from_status=from_status, requested=requested_status, reason=reason,
            diagnostic=diagnostic, dest=destination_uid or "", auto=bool(auto_logistics),
            pdate=pickup_date or "", pslot=pickup_slot or "",
            at=now(), evt_uid=new_uid("EVT"), etype="FAULT_REPORTED",
            details=f"Hors d'usage signalé : {reason} | {diagnostic}")
        return uid

    def apply_approval(self, notif_uid, battery_id, owner_uid, new_status, from_status,
                       destination_uid, comment):
        order_uid = new_uid("TO")
        dest_name = self._read("MATCH (d:Actor {uid: $uid}) RETURN d.name AS name",
                               uid=destination_uid)[0]["name"]
        at = now()
        self._write("""
            MATCH (n:Notification {uid: $nuid})
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $owner_uid})
            MATCH (dest:Actor {uid: $dest_uid})
            OPTIONAL MATCH (b)-[:LOCATED_AT]->(loc:Actor)
            SET n.state = 'APPROVED', n.decidedAt = $at, n.decidedBy = actor.name,
                n.comment = $comment, b.status = $new_status
            CREATE (t:TransferOrder {uid: $order_uid, state: 'ORDERED', createdAt: $at})
            CREATE (t)-[:FOR]->(b)
            CREATE (t)-[:TO]->(dest)
            CREATE (n)-[:TRIGGERED]->(t)
            FOREACH (_ IN CASE WHEN loc IS NULL THEN [] ELSE [1] END | CREATE (t)-[:FROM]->(loc))
            WITH b, actor
            CREATE (e1:Event {uid: $evt1, type: 'STATUS_CHANGED', at: $at,
                              actorName: actor.name, details: $details1})
            CREATE (e2:Event {uid: $evt2, type: 'TRANSFER_ORDERED', at: $at,
                              actorName: actor.name, details: $details2})
            CREATE (b)-[:HAS_EVENT]->(e1), (b)-[:HAS_EVENT]->(e2)
            CREATE (actor)-[:PERFORMED]->(e1), (actor)-[:PERFORMED]->(e2)
            """,
            nuid=notif_uid, bid=battery_id, owner_uid=owner_uid, dest_uid=destination_uid,
            at=at, comment=comment, new_status=new_status, order_uid=order_uid,
            evt1=new_uid("EVT"), evt2=new_uid("EVT"),
            details1=f"{from_status} → {new_status}",
            details2=f"Transfert vers {dest_name} ({order_uid})")

    def apply_rejection(self, notif_uid, battery_id, owner_uid, comment):
        self._write("""
            MATCH (n:Notification {uid: $nuid})
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $owner_uid})
            SET n.state = 'REJECTED', n.decidedAt = $at, n.decidedBy = actor.name, n.comment = $comment
            """ + EVENT_CREATE,
            nuid=notif_uid, bid=battery_id, owner_uid=owner_uid, at=now(), comment=comment,
            evt_uid=new_uid("EVT"), etype="REQUEST_REJECTED", details=f"Demande refusée : {comment}")

    def apply_reception(self, order_uid, battery_id, center_uid):
        self._write("""
            MATCH (t:TransferOrder {uid: $order_uid})
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $center_uid})
            SET t.state = 'RECEIVED', t.receivedAt = $at
            WITH t, b, actor
            OPTIONAL MATCH (b)-[old:LOCATED_AT]->()
            DELETE old
            WITH DISTINCT b, actor
            CREATE (b)-[:LOCATED_AT]->(actor)
            """ + EVENT_CREATE,
            order_uid=order_uid, bid=battery_id, center_uid=center_uid, at=now(),
            evt_uid=new_uid("EVT"), etype="RECEIVED",
            details=f"Batterie réceptionnée (ordre {order_uid})")
