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
      "test_status": "RUNNING",               # optionnel : RUNNING, COMPLETED
      "test_remaining_sec": 12,               # optionnel
      "modules": [{"index": 1, "internalResistance_mOhm": 1.12,
                   "temperature_C": 24.5},    # temperature_C optionnelle
                  ...]
    }
"""
import time
from datetime import datetime

from .workflow import WorkflowError, module_alerts

BMS_ACTOR_UID = "BMS-GATEWAY"

# Suivi d'état du test de diagnostic actif / terminé (en mémoire)
_TEST_STATUS = {}


def _normalize_id(battery_id):
    bid = str(battery_id or "").strip().upper()
    if bid in ("DLR-1985", "DLR1985", "DELOREAN"):
        return "BAT-DOC-001"
    return bid


def update_test_status(battery_id, data):
    """Enregistre le statut de test envoyé par le simulateur / banc de diagnostic."""
    if not battery_id or not isinstance(data, dict):
        return
    bid = _normalize_id(battery_id)
    st = data.get("test_status")
    if st == "RESET":
        _TEST_STATUS.pop(bid, None)
        return
    rem = data.get("test_remaining_sec")
    dur = data.get("test_duration_sec") or 15
    if st in ("RUNNING", "COMPLETED", "ALERT"):
        _TEST_STATUS[bid] = {
            "state": st,
            "remaining": rem,
            "duration": dur,
            "updated_at": time.time(),
        }


def get_test_status(battery_id, p=None):
    """Calcule l'état actuel pour l'interface : en cours (avec chrono), terminé ou veille."""
    bid = _normalize_id(battery_id)
    info = _TEST_STATUS.get(bid)
    now = time.time()
    if info:
        elapsed = now - info.get("updated_at", 0)
        if info["state"] == "RUNNING":
            if elapsed > 16:  # Timeout si arrêt inopiné du script
                info["state"] = "COMPLETED"
            else:
                rem = info.get("remaining")
                return dict(state="RUNNING", label="⏱️ Diagnostic en cours...",
                            css_class="status-running", remaining=rem)

        if (info["state"] == "COMPLETED" or info["state"] == "ALERT") and elapsed < 240:
            has_alert = False
            if p:
                has_alert = bool(module_alerts(p))
            if has_alert:
                return dict(state="ALERT", label="⚠️ Diagnostic terminé · Anomalie détectée",
                            css_class="status-alert", remaining=0)
            return dict(state="COMPLETED", label="✅ Diagnostic terminé · Modules conformes",
                        css_class="status-ok", remaining=0)

    # Si aucune session de banc active, mais que la batterie porte une anomalie module
    if p and module_alerts(p):
        return dict(state="ALERT", label="⚠️ Anomalie BMS détectée sur un module",
                    css_class="status-alert", remaining=0)

    return dict(state="IDLE", label="⚪ Prêt · Aucun test en cours", css_class="status-idle", remaining=0)


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
    battery_id = str(data.get("batteryId") or data.get("battery_id") or "").strip().upper()
    if not battery_id:
        raise TelemetryError("« batteryId » manquant.")
    if battery_id in ("DLR-1985", "DLR1985", "DELOREAN"):
        battery_id = "BAT-DOC-001"

    at = data.get("measuredAt") or data.get("ts")
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
        idx = m.get("index") if m.get("index") is not None else m.get("id")
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise TelemetryError("« index » de module manquant ou non entier.")
        if idx in seen:
            raise TelemetryError(f"Module {idx} présent deux fois dans la trame.")
        seen.add(idx)

        r_val = m.get("internalResistance_mOhm")
        if r_val is None:
            r_val = m.get("r_mohm")
        if r_val is None:
            r_val = m.get("resistance_mohm")
        if r_val is None and "v_ocv" in m and m.get("i"):
            try:
                v = float(m.get("v", 0) or 0)
                i = float(m.get("i", 0) or 0)
                if i != 0:
                    r_val = (float(m["v_ocv"]) - v) / i * 1000
            except (ValueError, TypeError):
                pass

        r = _number(r_val, f"module {idx} : internalResistance_mOhm", 0, 1000)
        t = m.get("temperature_C") if m.get("temperature_C") is not None else m.get("t")
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

    # Met à jour le statut du test de diagnostic si transmis
    update_test_status(frame["batteryId"], data)

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

    `readings` : relevés triés du plus ancien au plus récent.
    Agrège au maximum une valeur par jour (la dernière mesure enregistrée à la journée)
    afin de conserver l'ensemble de la chronologie historique (plusieurs mois)
    même lors de tests intensifs réalisés le même jour.
    """
    valid = [r for r in readings if r.get("resistances")]
    if len(valid) < 2 or not modules:
        return None

    # Agrégation journalière : dernière mesure de chaque date distincte
    by_day = {}
    for r in valid:
        day = (r.get("at") or "")[:10]
        if day:
            by_day[day] = r

    if len(by_day) >= 2:
        chart_readings = list(by_day.values())[-last:]
        is_daily = True
        first_label = chart_readings[0]["at"][:10]
        last_label = chart_readings[-1]["at"][:10]
    else:
        # Relevés tous concentrés sur la même journée : on affiche les N derniers relevés avec l'heure
        chart_readings = valid[-last:]
        is_daily = False
        first_label = (chart_readings[0].get("at") or "")[11:16] or chart_readings[0]["at"][:10]
        last_label = (chart_readings[-1].get("at") or "")[11:16] or chart_readings[-1]["at"][:10]

    if len(chart_readings) < 2:
        return None

    max_r = {m["index"]: m.get("maxInternalResistance_mOhm") for m in modules}
    threshold = max((v for v in max_r.values() if v), default=None)
    series = {}
    for k, r in enumerate(chart_readings):
        for idx, val in zip(r.get("moduleIndexes") or [], r["resistances"]):
            series.setdefault(idx, []).append((k, val))
    top = max([v for pts in series.values() for _, v in pts] + [(threshold or 0) * 1.5]) * 1.1
    pad_l, pad_r, pad_t, pad_b = 36, 34, 10, 22
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    x = lambda k: round(pad_l + w * k / (len(chart_readings) - 1), 1)  # noqa: E731
    y = lambda v: round(pad_t + h * (1 - v / top), 1)                  # noqa: E731
    lines = []
    for idx in sorted(series):
        pts = series[idx]
        hot = bool(max_r.get(idx)) and pts[-1][1] > max_r[idx]
        lines.append(dict(index=idx, hot=hot, last=pts[-1][1],
                          points=" ".join(f"{x(k)},{y(v)}" for k, v in pts),
                          end_x=x(pts[-1][0]), end_y=y(pts[-1][1])))
    # Étiquettes « M1…M5 » en bout de ligne : espacement propre pour éviter tout chevauchement
    gap, prev = 13, None
    for line in sorted(lines, key=lambda l: l["end_y"]):
        line["label_y"] = line["end_y"] if prev is None else max(line["end_y"], prev + gap)
        prev = line["label_y"]
    overflow = prev - (height - pad_b) if prev is not None else 0
    if overflow > 0:
        for line in lines:
            if line["end_y"] > pad_t + h / 2:
                line["label_y"] -= overflow
    step = 1 if top <= 5 else (2 if top <= 10 else 5)
    ticks = [dict(v=v, y=y(v)) for v in range(0, int(top) + 1, step)]
    return dict(width=width, height=height, lines=lines, ticks=ticks,
                left=pad_l, right=width - pad_r, bottom=height - pad_b,
                threshold=threshold, threshold_y=y(threshold) if threshold else None,
                first_label=first_label, last_label=last_label,
                first_at=chart_readings[0]["at"], last_at=chart_readings[-1]["at"],
                count=len(chart_readings), is_daily=is_daily)
