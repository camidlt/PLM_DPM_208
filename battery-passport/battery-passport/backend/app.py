"""
Battery Passport – PoC Hackathon ESILV x Capgemini (Défi #1 Télémétrie)

Lancer :  uvicorn app:app --host 0.0.0.0 --port 8000 --reload   (depuis le dossier backend/)
"""
import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase
from pydantic import BaseModel

log = logging.getLogger("bp")
logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------ config
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "hackathon2026")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")
# URL publique du PC qui fait tourner le backend (IP Wi-Fi pour que le téléphone puisse scanner)
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
MQTT_HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")   # vide = MQTT désactivé
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "esilv-hack-2026/equipe-XX")

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
SEED = ROOT / "neo4j" / "seed.cypher"

STATUSES = ["Original", "Reused", "Repurposed", "Remanufactured", "Waste"]

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def run(query: str, **params):
    with driver.session(database=NEO4J_DB) as s:
        return [r.data() for r in s.run(query, **params)]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def require_role(x_role: str | None, *allowed: str):
    if x_role not in allowed:
        raise HTTPException(403, f"Action réservée au rôle : {', '.join(allowed)} (rôle reçu : {x_role})")


def seed():
    statements = [s.strip() for s in SEED.read_text(encoding="utf-8").split(";")]
    for st in statements:
        body = "\n".join(l for l in st.splitlines() if not l.strip().startswith("//")).strip()
        if body:
            run(body)
    log.info("Seed Neo4j OK")


# ------------------------------------------------------------------ ingestion télémétrie
INGEST_Q = """
MATCH (b:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m:Module {position: $pos})
OPTIONAL MATCH (mo:Model)-[:HAS_BATTERY_INSTANCE]->(b)
OPTIONAL MATCH (mo)-[:HAS_STATIC_PERFORMANCE]->(sp:StaticPerformance)
WITH b, m, coalesce(sp.maxInternalResistance, 25.0) AS rmax
CREATE (m)-[:HAS_MEASUREMENT]->(x:Measurement {ts: $ts, voltage: $v, current: $i,
        internalResistance: $r, temperature: $t})
WITH b, m, x, rmax
OPTIONAL MATCH (m)-[old:LATEST]->()
DELETE old
WITH DISTINCT b, m, x, rmax
CREATE (m)-[:LATEST]->(x)
SET m.consecutiveOver = CASE WHEN $r > rmax THEN coalesce(m.consecutiveOver, 0) + 1 ELSE 0 END,
    m.lastResistance = $r, m.lastTemperature = $t, m.lastVoltage = $v, m.lastCurrent = $i,
    m.lastTs = $ts, m.maxResistance = rmax
WITH b, m, rmax
SET m.health = CASE
      WHEN m.consecutiveOver >= 3 THEN 'CRITICAL'      // > max sur 3 mesures consécutives
      WHEN $r >= 0.8 * rmax THEN 'WARNING'             // >= 80 % du max constructeur
      ELSE 'OK' END
WITH b, m, rmax
WHERE m.health = 'CRITICAL' AND NOT EXISTS { MATCH (m)-[:RAISED]->(a:Alert) WHERE a.open }
CREATE (m)-[:RAISED]->(:Alert {alertId: randomUUID(), level: 'CRITICAL', ts: $ts, value: $r,
       threshold: rmax, open: true,
       message: 'Module ' + toString(m.position) + ' : résistance interne ' + toString(round($r, 1))
                + ' mΩ > max constructeur ' + toString(rmax) + ' mΩ'})
"""


def ingest(payload: dict):
    bid = payload["batteryId"]
    ts = payload.get("ts") or now()
    for m in payload["modules"]:
        i = float(m.get("i", 0))
        v = float(m.get("v", 0))
        r = m.get("r_mohm")
        if r is None and "v_ocv" in m and i:
            r = (float(m["v_ocv"]) - v) / i * 1000  # R = ΔV / I  (mΩ)
        run(INGEST_Q, bid=bid, pos=int(m["id"]), v=v, i=i, r=float(r or 0),
            t=float(m.get("t", 25)), ts=ts)


def start_mqtt():
    if not MQTT_HOST:
        log.info("MQTT désactivé (MQTT_HOST vide)")
        return
    import paho.mqtt.client as mqtt

    topic = f"{TOPIC_PREFIX}/battery/+/telemetry"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bp-backend-{uuid.uuid4().hex[:6]}")

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("MQTT connecté à %s, abonnement %s", MQTT_HOST, topic)
        c.subscribe(topic)

    def on_message(c, userdata, msg):
        try:
            ingest(json.loads(msg.payload))
        except Exception as e:  # ne jamais tuer la boucle MQTT
            log.warning("Message MQTT ignoré : %s", e)

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        client.loop_start()
    except Exception as e:
        log.warning("Connexion MQTT impossible (%s) – l'ingestion HTTP reste disponible", e)


# ------------------------------------------------------------------ app
app = FastAPI(title="Battery Passport PoC")


@app.on_event("startup")
def startup():
    try:
        seed()
    except Exception as e:
        log.error("Neo4j indisponible au démarrage : %s", e)
    start_mqtt()


class Telemetry(BaseModel):
    batteryId: str
    ts: str | None = None
    modules: list[dict]


class Report(BaseModel):
    by: str = "Garage Hill Valley"
    comment: str = ""


class StatusChange(BaseModel):
    newStatus: str
    by: str = "Responsable Battery Passport"
    comment: str = ""


class Actor(BaseModel):
    by: str = "Centre de tri agréé"


@app.post("/api/telemetry")
def post_telemetry(t: Telemetry):
    """Ingestion HTTP (plan B si MQTT bloque)."""
    ingest(t.model_dump())
    return {"ok": True}


@app.get("/api/batteries")
def list_batteries():
    return run("""
        MATCH (mo:Model)-[:HAS_BATTERY_INSTANCE]->(b:BatteryInstance)
        OPTIONAL MATCH (t:Type)-[:HAS_MODEL]->(mo)
        OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
        OPTIONAL MATCH (b)-[:HAS_MODULE]->(m:Module {health: 'CRITICAL'})
        RETURN b.batteryId AS batteryId, b.status AS status, mo.name AS model, t.name AS type,
               dp.soce AS soce, b.currentHolder AS holder, count(m) AS criticalModules
        ORDER BY batteryId
    """)


@app.get("/api/batteries/{bid}")
def get_passport(bid: str):
    rows = run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        OPTIONAL MATCH (mo:Model)-[:HAS_BATTERY_INSTANCE]->(b)
        OPTIONAL MATCH (t:Type)-[:HAS_MODEL]->(mo)
        OPTIONAL MATCH (c:Company)-[:HAS_TYPE]->(t)
        OPTIONAL MATCH (eo:EconomicOperator)-[:BUILD]->(b)
        OPTIONAL MATCH (mo)-[:HAS_STATIC_PERFORMANCE]->(sp)
        OPTIONAL MATCH (mo)-[:HAS_STATIC_DURABILITY]->(sd)
        OPTIONAL MATCH (mo)-[:HAS_CERTIFICATION]->(cert)
        OPTIONAL MATCH (mo)-[:HAS_CIRCULARITY]->(circ)
        OPTIONAL MATCH (mo)-[:HAS_CARBON_FOOTPRINT]->(cf)
        OPTIONAL MATCH (mo)-[:HAS_COMPOSITION]->(comp)
        OPTIONAL MATCH (comp)-[:HAS_ANODE]->(an)
        OPTIONAL MATCH (comp)-[:HAS_CATHODE]->(ca)
        OPTIONAL MATCH (comp)-[:HAS_ELECTROLYTE]->(el)
        OPTIONAL MATCH (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
        OPTIONAL MATCH (b)-[:HAS_DYNAMIC_DURABILITY]->(dd)
        RETURN b{.*} AS battery, mo{.*} AS model, t{.*} AS type, c{.*} AS company, eo{.*} AS operator,
               sp{.*} AS staticPerformance, sd{.*} AS staticDurability, cert{.*} AS certification,
               circ{.*} AS circularity, cf{.*} AS carbonFootprint,
               comp{.*, anode: an{.*}, cathode: ca{.*}, electrolyte: el{.*}} AS composition,
               dp{.*} AS dynamicPerformance, dd{.*} AS dynamicDurability
        LIMIT 1
    """, bid=bid)
    if not rows:
        raise HTTPException(404, "Batterie inconnue")
    p = rows[0]
    p["modules"] = [r["m"] for r in run("""
        MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m:Module)
        RETURN m{.*} AS m ORDER BY m.position""", bid=bid)]
    p["alerts"] = [r["a"] for r in run("""
        MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m)-[:RAISED]->(a:Alert)
        RETURN a{.*, module: m.position} AS a ORDER BY a.ts DESC""", bid=bid)]
    p["events"] = [r["e"] for r in run("""
        MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_EVENT]->(e:Event)
        RETURN e{.*} AS e ORDER BY e.ts DESC""", bid=bid)]
    p["statuses"] = STATUSES
    return p


@app.get("/api/batteries/{bid}/history")
def get_history(bid: str, limit: int = 60):
    return run("""
        MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m:Module)-[:HAS_MEASUREMENT]->(x)
        WITH m, x ORDER BY x.ts DESC
        WITH m, collect(x{.*})[..$limit] AS xs
        RETURN m.position AS position, reverse(xs) AS points ORDER BY position
    """, bid=bid, limit=limit)


@app.post("/api/batteries/{bid}/report")
def report_to_owner(bid: str, body: Report, x_role: str | None = Header(None)):
    """Garagiste : remonte le diagnostic au propriétaire et demande le passage en Waste."""
    require_role(x_role, "garagiste")
    crit = run("""
        MATCH (:BatteryInstance {batteryId: $bid})-[:HAS_MODULE]->(m:Module {health: 'CRITICAL'})
        RETURN m.position AS pos, m.lastResistance AS r""", bid=bid)
    details = "; ".join(f"module {c['pos']} : {c['r']:.1f} mΩ" for c in crit) or "aucun module critique"
    msg = f"Défaut critique détecté par {body.by} ({details}). Demande de passage Original → Waste."
    if body.comment:
        msg += f" Commentaire : {body.comment}"
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        CREATE (b)-[:HAS_EVENT]->(:Event {eventId: randomUUID(), type: 'DIAGNOSIS_REPORTED', ts: $ts,
                role: 'garagiste', by: $by, details: $msg})
        CREATE (n:Notification {notificationId: randomUUID(), toRole: 'owner', ts: $ts, read: false,
                batteryId: $bid, requestedStatus: 'Waste', message: $msg})-[:ABOUT]->(b)
        WITH b
        OPTIONAL MATCH (b)-[:HAS_MODULE]->()-[:RAISED]->(a:Alert {open: true})
        SET a.reportedAt = $ts
    """, bid=bid, ts=now(), by=body.by, msg=msg)
    return {"ok": True, "message": msg}


@app.get("/api/notifications")
def notifications(role: str = "owner"):
    return [r["n"] for r in run("""
        MATCH (n:Notification {toRole: $role}) RETURN n{.*} AS n ORDER BY n.ts DESC LIMIT 20""", role=role)]


@app.post("/api/batteries/{bid}/status")
def change_status(bid: str, body: StatusChange, x_role: str | None = Header(None)):
    """Propriétaire du Battery Passport : seul rôle autorisé à changer le statut."""
    require_role(x_role, "owner")
    if body.newStatus not in STATUSES:
        raise HTTPException(400, f"Statut invalide. Valeurs : {STATUSES}")
    cur = run("MATCH (b:BatteryInstance {batteryId: $bid}) RETURN b.status AS s", bid=bid)
    if not cur:
        raise HTTPException(404, "Batterie inconnue")
    if cur[0]["s"] == "Waste":
        raise HTTPException(409, "Une batterie au statut Waste ne peut plus changer de statut.")
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        WITH b, b.status AS old
        SET b.status = $new, b.statusUpdatedAt = $ts
        CREATE (b)-[:HAS_EVENT]->(:Event {eventId: randomUUID(), type: 'STATUS_CHANGED', ts: $ts,
                role: 'owner', by: $by, details: old + ' → ' + $new + CASE WHEN $comment <> '' THEN ' (' + $comment + ')' ELSE '' END})
        WITH b
        OPTIONAL MATCH (n:Notification)-[:ABOUT]->(b) WHERE n.read = false
        SET n.read = true
    """, bid=bid, new=body.newStatus, ts=now(), by=body.by, comment=body.comment)
    return {"ok": True}


@app.post("/api/batteries/{bid}/reception")
def confirm_reception(bid: str, body: Actor, x_role: str | None = Header(None)):
    """Centre de tri : accusé de réception + vérification du statut."""
    require_role(x_role, "recycler")
    st = run("MATCH (b:BatteryInstance {batteryId: $bid}) RETURN b.status AS s", bid=bid)[0]["s"]
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        SET b.receivedAt = $ts
        CREATE (b)-[:HAS_EVENT]->(:Event {eventId: randomUUID(), type: 'RECEIVED', ts: $ts,
                role: 'recycler', by: $by, details: 'Réception au centre de tri – statut constaté : ' + $st})
    """, bid=bid, ts=now(), by=body.by, st=st)
    return {"ok": True, "status": st, "statusIsWaste": st == "Waste"}


@app.post("/api/batteries/{bid}/recycling/start")
def start_recycling(bid: str, body: Actor, x_role: str | None = Header(None)):
    require_role(x_role, "recycler")
    st = run("MATCH (b:BatteryInstance {batteryId: $bid}) RETURN b.status AS s", bid=bid)[0]["s"]
    if st != "Waste":
        raise HTTPException(409, f"Recyclage refusé : le statut du passeport est « {st} », il doit être « Waste ».")
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        SET b.recyclingStatus = 'STARTED', b.recyclingStartedAt = $ts
        CREATE (b)-[:HAS_EVENT]->(:Event {eventId: randomUUID(), type: 'RECYCLING_STARTED', ts: $ts,
                role: 'recycler', by: $by, details: 'Statut Waste confirmé – recyclage lancé'})
    """, bid=bid, ts=now(), by=body.by)
    return {"ok": True}


@app.post("/api/demo/reset/{bid}")
def reset(bid: str):
    """Remet la démo à zéro (statut Original, efface mesures/alertes/événements)."""
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        OPTIONAL MATCH (b)-[:HAS_MODULE]->(m)-[:HAS_MEASUREMENT|RAISED]->(x)
        DETACH DELETE x
    """, bid=bid)
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        OPTIONAL MATCH (b)-[:HAS_EVENT]->(e) WHERE e.type <> 'MANUFACTURED'
        DETACH DELETE e
    """, bid=bid)
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        OPTIONAL MATCH (n:Notification)-[:ABOUT]->(b) DETACH DELETE n
    """, bid=bid)
    run("""
        MATCH (b:BatteryInstance {batteryId: $bid})
        SET b.status = 'Original', b.recyclingStatus = null, b.receivedAt = null,
            b.recyclingStartedAt = null, b.statusUpdatedAt = null
        WITH b MATCH (b)-[:HAS_MODULE]->(m)
        SET m.health = 'OK', m.consecutiveOver = 0, m.lastResistance = null, m.lastTemperature = null,
            m.lastTs = null, m.lastVoltage = null, m.lastCurrent = null
    """, bid=bid)
    return {"ok": True}


# ------------------------------------------------------------------ QR + pages
@app.get("/qr/{bid}.png")
def qr(bid: str):
    img = qrcode.make(f"{PUBLIC_URL}/passport/{bid}")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.get("/passport/{bid}")
def passport_page(bid: str):
    return FileResponse(FRONT / "passport.html")


@app.get("/")
def root():
    return RedirectResponse("/passport/DLR-1985")


app.mount("/app", StaticFiles(directory=FRONT, html=True), name="app")
