"""Défi 1 : télémétrie BMS.

Une trame BMS met à jour les nœuds `Module` (résistance interne, measuredAt) et
`DynamicPerformance` (SOH, SOC) du passeport, et garde un historique sous forme
de nœuds `TelemetryReading`. Quand une trame fait passer un module au-delà du
seuil constructeur, un événement BMS_ALERT est ajouté à l'historique : l'alerte
apparaît alors sur l'écran garagiste, via `workflow.module_alerts`.

Format d'une trame (JSON) :
    {
      "batteryId": "BAT-002",
      "measuredAt": "2026-11-04T10:15:00",   # optionnel, défaut : maintenant
      "source": "BMS",                        # optionnel
      "soh": 92.5, "soc": 74,                 # optionnels, en %
      "modules": [{"index": 1, "internalResistance_mOhm": 1.12,
                   "temperature_C": 24.5},    # temperature_C optionnelle
                  ...]
    }
"""
from datetime import datetime

from .workflow import WorkflowError, module_alerts

BMS_ACTOR_UID = "BMS-GATEWAY"


class TelemetryError(WorkflowError):
    """Trame BMS invalide (renvoyée en 400 par l'API)."""


def _number(value, name, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TelemetryError(f"« {name} » doit être un nombre.")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise TelemetryError(f"« {name} » hors plage ({lo} à {hi}) : {value}.")
    return value


def parse_frame(data):
    """Valide une trame et la normalise. Lève TelemetryError si elle est invalide."""
    if not isinstance(data, dict):
        raise TelemetryError("Une trame doit être un objet JSON.")
    battery_id = str(data.get("batteryId") or "").strip().upper()
    if not battery_id:
        raise TelemetryError("« batteryId » manquant.")

    at = data.get("measuredAt")
    if at:
        try:
            at = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        except ValueError:
            raise TelemetryError(f"« measuredAt » n'est pas une date ISO 8601 : {at}.")
        at = at.replace(tzinfo=None).isoformat(timespec="seconds")
    else:
        at = datetime.now().isoformat(timespec="seconds")

    modules = data.get("modules") or []
    if not isinstance(modules, list):
        raise TelemetryError("« modules » doit être une liste.")
    parsed, seen = [], set()
    for m in modules:
        if not isinstance(m, dict):
            raise TelemetryError("Chaque module doit être un objet JSON.")
        idx = m.get("index")
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise TelemetryError("« index » de module manquant ou non entier.")
        if idx in seen:
            raise TelemetryError(f"Module {idx} présent deux fois dans la trame.")
        seen.add(idx)
        r = _number(m.get("internalResistance_mOhm"), f"module {idx} : internalResistance_mOhm", 0, 1000)
        t = m.get("temperature_C")
        parsed.append(dict(index=idx, r=float(r),
                           t=None if t is None else float(_number(t, f"module {idx} : temperature_C", -60, 200))))

    soh = data.get("soh")
    soc = data.get("soc")
    soh = None if soh is None else _number(soh, "soh", 0, 100)
    soc = None if soc is None else _number(soc, "soc", 0, 100)
    if not parsed and soh is None and soc is None:
        raise TelemetryError("Trame vide : ni modules, ni SOH, ni SOC.")

    return dict(batteryId=battery_id, at=at, source=str(data.get("source") or "BMS")[:40],
                soh=soh, soc=soc, modules=sorted(parsed, key=lambda m: m["index"]))


def ingest(repo, data):
    """Enregistre une trame. Renvoie un résumé (dont les nouvelles alertes)."""
    frame = parse_frame(data)
    p = repo.get_passport(frame["batteryId"])
    if p is None:
        raise TelemetryError(f"Batterie {frame['batteryId']} introuvable.")
    known = {m["index"] for m in p["modules"]}
    unknown = [m["index"] for m in frame["modules"] if m["index"] not in known]
    if unknown:
        raise TelemetryError(f"Module(s) inconnu(s) sur {frame['batteryId']} : {unknown}.")

    # Une trame plus ancienne que la dernière mesure est archivée sans écraser l'état actuel.
    last = max([m.get("measuredAt") or "" for m in p["modules"]]
               + [p["dynamic_performance"].get("measuredAt") or ""])
    is_current = frame["at"] >= last

    before = {m["index"] for m in module_alerts(p)}
    repo.record_telemetry(frame, update_current=is_current)

    new_alerts = []
    if is_current:
        after = repo.get_passport(frame["batteryId"])
        new_alerts = [m for m in module_alerts(after) if m["index"] not in before]
        if new_alerts:
            details = " · ".join(f"Module {m['index']} : {m['internalResistance_mOhm']} mΩ > max "
                                 f"{m['maxInternalResistance_mOhm']} mΩ" for m in new_alerts)
            repo.add_event(frame["batteryId"], "BMS_ALERT", BMS_ACTOR_UID,
                           details + " (seuil constructeur dépassé)")
    return dict(batteryId=frame["batteryId"], measuredAt=frame["at"], current=is_current,
                newAlerts=[m["index"] for m in new_alerts])


# --- Affichage : courbe d'évolution de la résistance interne ------------------------
def resistance_chart(readings, modules, width=460, height=190, last=12):
    """Prépare une courbe SVG (sans librairie JS) : une ligne par module + le seuil.

    `readings` : relevés triés du plus ancien au plus récent. Renvoie None s'il y a
    moins de deux relevés.
    """
    readings = [r for r in readings if r.get("resistances")][-last:]
    if len(readings) < 2 or not modules:
        return None
    max_r = {m["index"]: m.get("maxInternalResistance_mOhm") for m in modules}
    threshold = max((v for v in max_r.values() if v), default=None)
    series = {}
    for k, r in enumerate(readings):
        for idx, val in zip(r.get("moduleIndexes") or [], r["resistances"]):
            series.setdefault(idx, []).append((k, val))
    top = max([v for pts in series.values() for _, v in pts] + [(threshold or 0) * 1.5]) * 1.1
    pad_l, pad_r, pad_t, pad_b = 36, 34, 10, 22
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    x = lambda k: round(pad_l + w * k / (len(readings) - 1), 1)  # noqa: E731
    y = lambda v: round(pad_t + h * (1 - v / top), 1)           # noqa: E731
    lines = []
    for idx in sorted(series):
        pts = series[idx]
        hot = bool(max_r.get(idx)) and pts[-1][1] > max_r[idx]
        lines.append(dict(index=idx, hot=hot, last=pts[-1][1],
                          points=" ".join(f"{x(k)},{y(v)}" for k, v in pts),
                          end_x=x(pts[-1][0]), end_y=y(pts[-1][1])))
    # Étiquettes « M1…M5 » en bout de ligne : on les écarte pour qu'elles ne se chevauchent pas
    gap, prev = 11, None
    for line in sorted(lines, key=lambda l: l["end_y"]):
        line["label_y"] = line["end_y"] if prev is None else max(line["end_y"], prev + gap)
        prev = line["label_y"]
    overflow = prev - (height - pad_b) if prev is not None else 0
    if overflow > 0:
        for line in lines:
            line["label_y"] -= overflow
    step = 1 if top <= 5 else (2 if top <= 10 else 5)
    ticks = [dict(v=v, y=y(v)) for v in range(0, int(top) + 1, step)]
    return dict(width=width, height=height, lines=lines, ticks=ticks,
                left=pad_l, right=width - pad_r, bottom=height - pad_b,
                threshold=threshold, threshold_y=y(threshold) if threshold else None,
                first_at=readings[0]["at"], last_at=readings[-1]["at"], count=len(readings))
