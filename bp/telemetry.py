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


class TelemetryError(ValueError):
    """Message de télémétrie invalide (renvoyé en 400 à l'appareil)."""


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


def parse_payload(payload):
    """Normalise le JSON envoyé par l'ESP32 / Wokwi / l'émulateur.

    Format : {"batteryId": "DLR-1985", "ts": "...", "modules": [{"id": 1, "r_mohm": 1.2,
              "v": 3.69, "i": 12.0, "t": 25.1}, ...]}
    Si r_mohm est absent, R est calculée par R = (V_ocv - V) / I.
    """
    if not isinstance(payload, dict):
        raise TelemetryError("Le corps doit être un objet JSON.")
    bid = payload.get("batteryId") or payload.get("battery_id")
    if not bid:
        raise TelemetryError("Champ batteryId manquant.")
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise TelemetryError("Champ modules manquant ou vide.")
    readings = []
    for m in modules:
        try:
            index = int(m["id"])
            v = float(m.get("v", 0) or 0)
            i = float(m.get("i", 0) or 0)
            r = m.get("r_mohm", m.get("resistance_mohm"))
            if r is None and "v_ocv" in m and i:
                r = (float(m["v_ocv"]) - v) / i * 1000
            if r is None:
                raise TelemetryError(f"Module {index} : r_mohm manquant.")
            readings.append(dict(index=index, r=round(float(r), 2), v=v, i=i,
                                 t=float(m.get("t", 25) or 25)))
        except (KeyError, TypeError, ValueError) as e:
            if isinstance(e, TelemetryError):
                raise
            raise TelemetryError(f"Module mal formé : {m!r}") from None
    return str(bid).strip().upper(), payload.get("ts"), readings


def alert_message(index, r, rmax):
    return (f"Module {index} : résistance interne {r} mΩ au-delà du maximum constructeur "
            f"{rmax} mΩ sur {CONSECUTIVE_FOR_CRITICAL} mesures consécutives")
