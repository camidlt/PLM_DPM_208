"""Défi 1 : télémétrie BMS (ESP32, Wokwi ou émulateur Python).

Règles de santé d'un module, identiques en mode mémoire et en mode Neo4j :
  - CRITICAL : résistance interne > max constructeur sur 3 mesures consécutives
  - WARNING  : résistance >= 80 % du max constructeur (ou au-dessus, pas encore confirmé)
  - OK       : sinon
Une alerte (et un événement dans l'historique) est créée quand un module devient CRITICAL.
"""
CONSECUTIVE_FOR_CRITICAL = 3
WARNING_RATIO = 0.8
HISTORY_POINTS = 120  # mesures gardées par module en mode mémoire
READINGS_KEPT = 500   # nœuds (:TelemetryReading) gardés par batterie en mode mémoire
MAX_BATCH = 200       # trames acceptées par requête

# Anciens identifiants de la batterie de Doc (firmware ESP32 déjà flashé)
ALIASES = {"DLR-1985": "BAT-DOC-001", "DLR1985": "BAT-DOC-001", "DELOREAN": "BAT-DOC-001"}


class TelemetryError(ValueError):
    """Message de télémétrie invalide (renvoyé en 400 à l'appareil)."""


def normalize_id(battery_id):
    bid = str(battery_id or "").strip().upper()
    return ALIASES.get(bid, bid)


def _percent(value, name):
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise TelemetryError(f"« {name} » doit être un nombre.") from None
    if not 0 <= v <= 100:
        raise TelemetryError(f"« {name} » hors plage (0 à 100 %).")
    return int(v) if v.is_integer() else round(v, 1)


def health_from_value(r, rmax):
    """Santé d'un module sans historique (données du seed)."""
    if r is None or rmax is None:
        return "OK"
    if r > rmax:
        return "CRITICAL"
    if r >= WARNING_RATIO * rmax:
        return "WARNING"
    return "OK"


def next_health(r, rmax, consecutive_over):
    """Applique une nouvelle mesure. Renvoie (santé, nb de dépassements consécutifs)."""
    over = consecutive_over + 1 if r > rmax else 0
    if over >= CONSECUTIVE_FOR_CRITICAL:
        return "CRITICAL", over
    if r >= WARNING_RATIO * rmax:
        return "WARNING", over
    return "OK", over


def parse_frame(payload):
    """Normalise une trame BMS (ESP32, Wokwi, émulateur ou passerelle).

    Format : {"batteryId": "BAT-DOC-001", "ts": "...", "soh": 71, "soc": 38,
              "modules": [{"id": 1, "r_mohm": 1.2, "v": 3.69, "i": 12.0, "t": 25.1}, ...]}
    SOH et SOC sont facultatifs. Si r_mohm est absent, R = (V_ocv - V) / I.
    Renvoie un dict : batteryId, ts, readings, soh, soc.
    """
    if not isinstance(payload, dict):
        raise TelemetryError("Chaque trame doit être un objet JSON.")
    bid = normalize_id(payload.get("batteryId") or payload.get("battery_id"))
    if not bid:
        raise TelemetryError("Champ batteryId manquant.")
    soh, soc = _percent(payload.get("soh"), "soh"), _percent(payload.get("soc"), "soc")
    modules = payload.get("modules")
    if modules is None:
        modules = []
    if not isinstance(modules, list):
        raise TelemetryError("Champ modules : liste attendue.")
    if not modules and soh is None and soc is None:
        raise TelemetryError("Trame vide : ni modules, ni SOH, ni SOC.")
    readings = []
    for m in modules:
        try:
            index = int(m["id"] if "id" in m else m["index"])
            v = float(m.get("v", 0) or 0)
            i = float(m.get("i", 0) or 0)
            r = m.get("r_mohm", m.get("resistance_mohm", m.get("internalResistance_mOhm")))
            if r is None and "v_ocv" in m and i:
                r = (float(m["v_ocv"]) - v) / i * 1000
            if r is None:
                raise TelemetryError(f"Module {index} : r_mohm manquant.")
            r = round(float(r), 2)
            if not 0 <= r <= 1000:
                raise TelemetryError(f"Module {index} : résistance hors plage ({r} mΩ).")
            readings.append(dict(index=index, r=r, v=v, i=i,
                                 t=float(m.get("t", m.get("temperature_C", 25)) or 25)))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            if isinstance(e, TelemetryError):
                raise
            raise TelemetryError(f"Module mal formé : {m!r}") from None
    if len({rd["index"] for rd in readings}) != len(readings):
        raise TelemetryError("Module en double dans la trame.")
    return dict(batteryId=bid, ts=payload.get("ts") or payload.get("at"), readings=readings,
                soh=soh, soc=soc)


def parse_payload(payload):
    """Corps d'une requête : une trame (objet) ou un lot de trames (liste)."""
    frames = payload if isinstance(payload, list) else [payload]
    if not frames:
        raise TelemetryError("Lot de trames vide.")
    if len(frames) > MAX_BATCH:
        raise TelemetryError(f"Lot trop grand : {len(frames)} trames (maximum {MAX_BATCH}).")
    return frames


def alert_message(index, r, rmax):
    return (f"Module {index} : résistance interne {r} mΩ au-delà du maximum constructeur "
            f"{rmax} mΩ sur {CONSECUTIVE_FOR_CRITICAL} mesures consécutives")
