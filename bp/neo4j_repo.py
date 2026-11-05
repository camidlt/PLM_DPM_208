"""Accès Neo4j : mêmes méthodes que MemoryRepo, en Cypher.

Si le dump fourni par les organisateurs utilise d'autres noms de propriétés ou
de relations, c'est ici (et seulement ici) qu'il faut adapter les requêtes.
"""
import uuid
from datetime import datetime

from neo4j import GraphDatabase

from . import config, seed_data


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
RETURN n{.*, batteryId: b.batteryId, senderName: s.name, operatorUid: eo.uid} AS n
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
        self._write("MATCH (n) WHERE n:Notification OR n:TransferOrder OR n:Event "
                    "OR n:TelemetryReading OR n:OrientationDecision OR n:LogisticsStep OR n:Message "
                    "DETACH DELETE n")
        uids = [uid for _, uid, _ in seed_data.NODES]
        self._write("MATCH (n) WHERE n.uid IN $uids DETACH DELETE n", uids=uids)
        for stmt in seed_data.cypher_statements():
            self._write(stmt)

    # --- lectures ----------------------------------------------------------------
    def list_batteries(self):
        return [r.data() for r in self._read("""
            MATCH (b:BatteryInstance)
            OPTIONAL MATCH (m:Model)-[:HAS_BATTERY_INSTANCE]->(b)
            OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
            OPTIONAL MATCH (b)-[:LOCATED_AT]->(l:Actor)
            RETURN b.batteryId AS batteryId, b.status AS status, m.name AS model,
                   dp.soh AS soh, l.name AS location
            ORDER BY batteryId""")]

    def get_passport(self, battery_id):
        rows = self._read(PASSPORT_QUERY, id=battery_id)
        if not rows:
            return None
        p = rows[0].data()
        p["dynamic_performance"] = p["dynamic_performance"] or {}
        p["dynamic_durability"] = p["dynamic_durability"] or {}
        p["modules"] = [r["m"] for r in self._read(
            "MATCH (:BatteryInstance {batteryId: $id})-[:HAS_MODULE]->(m:Module) "
            "RETURN m{.*} AS m ORDER BY m.index", id=battery_id)]
        pending = self._read(
            "MATCH (n:Notification {state: 'PENDING'})-[:ABOUT]->(:BatteryInstance {batteryId: $id}) "
            "WITH n LIMIT 1" + NOTIF_RETURN, id=battery_id)
        p["pending_request"] = pending[0]["n"] if pending else None
        transfer = self._read("""
            MATCH (t:TransferOrder)-[:FOR]->(:BatteryInstance {batteryId: $id})
            MATCH (t)-[:TO]->(d:Actor)
            OPTIONAL MATCH (t)-[:FROM]->(f:Actor)
            OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(c:Actor)
            RETURN t{.*, toUid: d.uid, toName: d.name, toAgreed: d.agreed, fromName: f.name,
                     carrierName: c.name} AS t
            ORDER BY t.supersededBy IS NULL DESC, t.createdAt DESC LIMIT 1""", id=battery_id)
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
        return [r["t"] for r in self._read("""
            MATCH (t:TransferOrder)-[:TO]->(:Actor {uid: $uid})
            MATCH (t)-[:FOR]->(b:BatteryInstance)
            RETURN t{.*, batteryId: b.batteryId, status: b.status} AS t
            ORDER BY t.createdAt DESC""", uid=center_uid)]

    # --- écritures --------------------------------------------------------------
    def create_status_request(self, battery_id, actor_uid, operator_uid, from_status,
                      requested_status, reason, diagnostic, destination_uid,
                      auto_logistics=False, pickup_date="", pickup_slot=""):
        uid = new_uid("NOTIF")
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $actor_uid})
            MATCH (eo:EconomicOperator {uid: $op_uid})
            CREATE (n:Notification {uid: $uid, type: 'STATUS_CHANGE_REQUEST',
                    fromStatus: $from_status, requestedStatus: $requested, reason: $reason,
                diagnostic: $diagnostic, destinationUid: $destination_uid,
                autoLogistics: $auto_logistics, pickupDate: $pickup_date,
                pickupSlot: $pickup_slot, state: 'PENDING', createdAt: $at})
            CREATE (actor)-[:SENT]->(n)
            CREATE (n)-[:ABOUT]->(b)
            CREATE (n)-[:ADDRESSED_TO]->(eo)
            """ + EVENT_CREATE,
            bid=battery_id, actor_uid=actor_uid, op_uid=operator_uid, uid=uid,
            from_status=from_status, requested=requested_status, reason=reason,
            diagnostic=diagnostic, destination_uid=destination_uid,
            auto_logistics=bool(auto_logistics), pickup_date=pickup_date or "",
            pickup_slot=pickup_slot or "", at=now(), evt_uid=new_uid("EVT"), etype="FAULT_REPORTED",
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

    # --- Défi 2 : logistique du transfert -------------------------------------------
    TRANSFER_RETURN = """
        MATCH (t)-[:FOR]->(b:BatteryInstance)
        MATCH (t)-[:TO]->(d:Actor)
        OPTIONAL MATCH (t)-[:FROM]->(f:Actor)
        OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(c:Actor)
        RETURN t{.*, batteryId: b.batteryId, batteryStatus: b.status, toUid: d.uid, toName: d.name,
                 toAgreed: d.agreed, fromUid: f.uid, fromName: f.name,
                 carrierUid: c.uid, carrierName: c.name} AS t"""

    def get_actor(self, uid):
        rows = self._read("MATCH (a:Actor {uid: $uid}) RETURN a{.*} AS a", uid=uid)
        return rows[0]["a"] if rows else None

    def get_transfer(self, order_uid):
        rows = self._read("MATCH (t:TransferOrder {uid: $uid})" + self.TRANSFER_RETURN, uid=order_uid)
        return rows[0]["t"] if rows else None

    def list_transfers(self, carrier_uid=None):
        if carrier_uid:
            q = "MATCH (t:TransferOrder)-[:ASSIGNED_TO]->(:Actor {uid: $cuid})"
        else:
            q = "MATCH (t:TransferOrder)"
        return [r["t"] for r in self._read(q + self.TRANSFER_RETURN + " ORDER BY t.createdAt DESC",
                                           cuid=carrier_uid)]

    def create_transfer(self, battery_id, from_uid, to_uid, props, carrier_uid=None):
        uid = new_uid("TO")
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (dest:Actor {uid: $to_uid})
            CREATE (t:TransferOrder {uid: $uid, createdAt: $at})
            SET t += $props
            CREATE (t)-[:FOR]->(b)
            CREATE (t)-[:TO]->(dest)
            WITH t
            OPTIONAL MATCH (f:Actor {uid: $from_uid})
            OPTIONAL MATCH (c:Actor {uid: $carrier_uid})
            FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | CREATE (t)-[:FROM]->(f))
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | CREATE (t)-[:ASSIGNED_TO]->(c))
            """, bid=battery_id, to_uid=to_uid, uid=uid, at=now(), props=props,
            from_uid=from_uid, carrier_uid=carrier_uid)
        return uid

    def update_transfer(self, order_uid, props, carrier_uid=None, location_uid=None):
        """Met à jour l'ordre ; change le transporteur affecté et/ou la localisation de la batterie."""
        self._write("MATCH (t:TransferOrder {uid: $uid}) SET t += $props", uid=order_uid, props=props)
        if carrier_uid:
            self._write("""
                MATCH (t:TransferOrder {uid: $uid})
                MATCH (c:Actor {uid: $cuid})
                OPTIONAL MATCH (t)-[old:ASSIGNED_TO]->()
                DELETE old
                WITH DISTINCT t, c
                CREATE (t)-[:ASSIGNED_TO]->(c)""", uid=order_uid, cuid=carrier_uid)
        if location_uid:
            self._write("""
                MATCH (t:TransferOrder {uid: $uid})-[:FOR]->(b:BatteryInstance)
                MATCH (loc:Actor {uid: $luid})
                OPTIONAL MATCH (b)-[old:LOCATED_AT]->()
                DELETE old
                WITH DISTINCT b, loc
                CREATE (b)-[:LOCATED_AT]->(loc)""", uid=order_uid, luid=location_uid)

    def add_transfer_step(self, order_uid, actor_uid, step):
        uid = new_uid("STEP")
        self._write("""
            MATCH (t:TransferOrder {uid: $order_uid})
            MATCH (actor:Actor {uid: $actor_uid})
            CREATE (s:LogisticsStep {uid: $uid})
            SET s += $step
            CREATE (t)-[:HAS_STEP]->(s)
            CREATE (actor)-[:PERFORMED]->(s)""",
            order_uid=order_uid, actor_uid=actor_uid, uid=uid, step=step)
        return uid

    def get_transfer_steps(self, order_uid):
        return [r["s"] for r in self._read(
            "MATCH (:TransferOrder {uid: $uid})-[:HAS_STEP]->(s:LogisticsStep) "
            "RETURN s{.*} AS s ORDER BY s.seq", uid=order_uid)]

    def add_message(self, to_uid, props):
        uid = new_uid("MSG")
        self._write("""
            MATCH (a:Actor {uid: $to_uid})
            CREATE (m:Message {uid: $uid, read: false, at: $at})
            SET m += $props
            CREATE (m)-[:SENT_TO]->(a)""", to_uid=to_uid, uid=uid, at=now(), props=props)
        return uid

    def list_messages(self, actor_uid):
        return [r["m"] for r in self._read(
            "MATCH (m:Message)-[:SENT_TO]->(:Actor {uid: $uid}) RETURN m{.*} AS m ORDER BY m.at DESC",
            uid=actor_uid)]

    def mark_messages_read(self, actor_uid):
        self._write("MATCH (m:Message {read: false})-[:SENT_TO]->(:Actor {uid: $uid}) SET m.read = true",
                    uid=actor_uid)

    # --- Défi 1 : télémétrie BMS -------------------------------------------------
    def _write_tx(self, statements):
        """Plusieurs requêtes dans une seule transaction (tout ou rien)."""
        def work(tx):
            for query, params in statements:
                tx.run(query, params).consume()
        with self.driver.session(database=self.database) as s:
            s.execute_write(work)

    def record_telemetry(self, frame, update_current=True):
        uid = new_uid("TEL")
        props = dict(uid=uid, at=frame["at"], source=frame["source"],
                     moduleIndexes=[m["index"] for m in frame["modules"]],
                     resistances=[m["r"] for m in frame["modules"]])
        if frame["modules"] and all(m["t"] is not None for m in frame["modules"]):
            props["temperatures"] = [m["t"] for m in frame["modules"]]
        dp_props = {k: frame[k] for k in ("soh", "soc") if frame[k] is not None}
        props.update(dp_props)
        bid = frame["batteryId"]
        stmts = [("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            CREATE (r:TelemetryReading)
            SET r = $props
            CREATE (b)-[:HAS_TELEMETRY]->(r)""", dict(bid=bid, props=props))]
        if update_current:
            stmts.append(("""
                UNWIND $mods AS mod
                MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m:Module {index: mod.index})
                SET m.internalResistance_mOhm = mod.r, m.measuredAt = $at,
                    m.temperature_C = coalesce(mod.t, m.temperature_C)""",
                dict(bid=bid, at=frame["at"],
                     mods=[dict(index=m["index"], r=m["r"], t=m["t"]) for m in frame["modules"]])))
            if dp_props:
                stmts.append(("""
                    MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
                    SET dp += $dp, dp.measuredAt = $at""", dict(bid=bid, dp=dp_props, at=frame["at"])))
        self._write_tx(stmts)
        return uid

    def get_telemetry(self, battery_id, limit=50):
        """Relevés BMS du plus ancien au plus récent (les `limit` derniers)."""
        rows = [r["r"] for r in self._read(
            "MATCH (:BatteryInstance {batteryId: $id})-[:HAS_TELEMETRY]->(r:TelemetryReading) "
            "RETURN r{.*} AS r ORDER BY r.at DESC LIMIT $limit", id=battery_id, limit=limit)]
        return rows[::-1]

    def add_event(self, battery_id, etype, actor_uid, details):
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $actor_uid})
            """ + EVENT_CREATE,
            bid=battery_id, actor_uid=actor_uid, evt_uid=new_uid("EVT"), etype=etype,
            at=now(), details=details)

    # --- Défi 3 : orientation de fin de vie ----------------------------------------
    def record_orientation(self, battery_id, actor_uid, choice, recommended, comment):
        uid = new_uid("ORI")
        details = f"Orientation : {choice}" + (f" (recommandé : {recommended})"
                                                if choice != recommended else " (conforme à la recommandation)")
        self._write("""
            MATCH (b:BatteryInstance {batteryId: $bid})
            MATCH (actor:Actor {uid: $actor_uid})
            CREATE (d:OrientationDecision {uid: $uid, choice: $choice, recommended: $recommended,
                    comment: $comment, at: $at, decidedBy: actor.name})
            CREATE (b)-[:HAS_ORIENTATION]->(d)
            CREATE (actor)-[:DECIDED]->(d)
            """ + EVENT_CREATE,
            bid=battery_id, actor_uid=actor_uid, uid=uid, choice=choice, recommended=recommended,
            comment=comment, at=now(), evt_uid=new_uid("EVT"), etype="ORIENTATION_DECIDED",
            details=details + (f". {comment}" if comment else ""))
        return uid

    def get_orientation(self, battery_id):
        rows = self._read(
            "MATCH (:BatteryInstance {batteryId: $id})-[:HAS_ORIENTATION]->(d:OrientationDecision) "
            "RETURN d{.*} AS d ORDER BY d.at DESC LIMIT 1", id=battery_id)
        return rows[0]["d"] if rows else None
