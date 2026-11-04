"""Défi 3 : aide à la décision de fin de vie (Reuse / Remanufacture / Repurpose / Recycle).

Principe, volontairement explicable devant un jury :
  1. Chaque option a une liste de critères mesurables (SOH, modules hors seuil,
     accidents, cycles, défauts de sécurité signalés, dérive BMS).
  2. On suit la hiérarchie européenne des déchets : on recommande la PREMIÈRE
     option éligible dans l'ordre Reuse → Remanufacture → Repurpose → Recycle.
     Le recyclage est toujours possible, c'est la solution de repli.
  3. Chaque critère est affiché avec sa valeur, son seuil et ✓/✗ : l'opérateur
     du centre de tri voit pourquoi, et peut choisir une autre option en le
     justifiant (décision enregistrée dans le passeport).

Les seuils sont regroupés dans THRESHOLDS pour être ajustés facilement.
"""
from datetime import date

from .workflow import WorkflowError, module_alerts

ORDER = ["Reuse", "Remanufacture", "Repurpose", "Recycle"]

OPTIONS = {
    "Reuse": dict(label="Réemploi", status="Reused", icon="🚗",
                  summary="Remise en service telle quelle dans un véhicule."),
    "Remanufacture": dict(label="Remanufacturing", status="Remanufactured", icon="🔧",
                          summary="Remplacement des modules défaillants, puis retour dans un véhicule."),
    "Repurpose": dict(label="Seconde vie", status="Repurposed", icon="🔋",
                      summary="Stockage stationnaire d'énergie, moins exigeant qu'un véhicule."),
    "Recycle": dict(label="Recyclage", status="Waste", icon="♻️",
                    summary="Démantèlement et récupération des matériaux."),
}

THRESHOLDS = dict(
    reuse_min_soh=80,              # % : en dessous, autonomie VE insuffisante
    reuse_max_cycle_ratio=0.8,     # cycles effectués / cycles prévus par le constructeur
    reuse_max_drift=0.5,           # +50 % de résistance sur la période BMS = vieillissement rapide
    reman_min_soh=70,
    reman_max_bad_module_ratio=0.4,  # au-delà de 40 % de modules à changer, pas rentable
    reman_max_cycle_ratio=0.9,
    repurpose_min_soh=60,          # seuil usuel de seconde vie stationnaire
    max_accidents_reuse=0,
    max_accidents_other=1,         # 2 accidents ou plus : recyclage (sécurité)
)

SAFETY_FAULTS = ("Dommage physique / gonflement", "Surchauffe")

# Matières premières critiques (liste UE) présentes dans les batteries Li-ion
CRITICAL_MATERIALS = {"Lithium", "Cobalt", "Nickel", "Manganese", "Graphite", "Phosphate"}

# Règlement (UE) 2023/1542, annexe XII : taux de valorisation des matériaux à atteindre
RECOVERY_TARGETS = [("Cobalt", 90, 95), ("Nickel", 90, 95), ("Cuivre", 90, 95), ("Lithium", 50, 80)]


def _crit(label, value, rule, ok):
    return dict(label=label, value=value, rule=rule, ok=bool(ok))


def _max_drift(readings):
    """Plus forte hausse relative de résistance d'un module sur l'historique BMS."""
    if not readings or len(readings) < 2:
        return None, None
    first, last = readings[0], readings[-1]
    a = dict(zip(first.get("moduleIndexes") or [], first.get("resistances") or []))
    b = dict(zip(last.get("moduleIndexes") or [], last.get("resistances") or []))
    drifts = [((b[i] - a[i]) / a[i], i) for i in a if i in b and a[i]]
    return max(drifts) if drifts else (None, None)


def recommend(p, history=(), readings=()):
    """Calcule la recommandation pour un passeport (dict renvoyé par repo.get_passport)."""
    t = THRESHOLDS
    dp, dd = p.get("dynamic_performance") or {}, p.get("dynamic_durability") or {}
    soh = dp.get("soh")
    soh = 0 if soh is None else soh
    modules = p.get("modules") or []
    bad = module_alerts(p)
    n_bad, n_mod = len(bad), len(modules)
    bad_ratio = n_bad / n_mod if n_mod else 0
    accidents = dd.get("accidents") or 0
    cycles = dd.get("cycleCount")
    expected = (p.get("static_durability") or {}).get("expectedBatteryLifetimeCycles")
    cycle_ratio = cycles / expected if cycles is not None and expected else None
    safety = sorted({f for e in history if e.get("type") == "FAULT_REPORTED"
                     for f in SAFETY_FAULTS if f in (e.get("details") or "")})
    chemistry = (p.get("composition") or {}).get("batteryChemistry") or ""
    drift, drift_module = _max_drift(list(readings))

    cyc_txt = f"{cycles} / {expected} ({cycle_ratio:.0%})" if cycle_ratio is not None else "inconnu"
    bad_txt = (f"{n_bad} / {n_mod} (" + ", ".join(f"n°{m['index']}" for m in bad) + ")") if n_bad else f"0 / {n_mod}"
    safety_crit = _crit("Aucun défaut de sécurité signalé", ", ".join(safety) or "aucun",
                        "gonflement, surchauffe : exclus", not safety)

    criteria = {
        "Reuse": [
            _crit("SOH", f"{soh} %", f"≥ {t['reuse_min_soh']} %", soh >= t["reuse_min_soh"]),
            _crit("Modules hors seuil", bad_txt, "aucun", n_bad == 0),
            _crit("Accidents", accidents, f"≤ {t['max_accidents_reuse']}", accidents <= t["max_accidents_reuse"]),
            _crit("Cycles consommés", cyc_txt, f"≤ {t['reuse_max_cycle_ratio']:.0%}",
                  cycle_ratio is not None and cycle_ratio <= t["reuse_max_cycle_ratio"]),
            safety_crit,
        ],
        "Remanufacture": [
            _crit("SOH", f"{soh} %", f"≥ {t['reman_min_soh']} %", soh >= t["reman_min_soh"]),
            _crit("Modules à remplacer", bad_txt, f"1 à {t['reman_max_bad_module_ratio']:.0%} des modules",
                  0 < bad_ratio <= t["reman_max_bad_module_ratio"]),
            _crit("Accidents", accidents, f"≤ {t['max_accidents_other']}", accidents <= t["max_accidents_other"]),
            _crit("Cycles consommés", cyc_txt, f"≤ {t['reman_max_cycle_ratio']:.0%}",
                  cycle_ratio is not None and cycle_ratio <= t["reman_max_cycle_ratio"]),
            safety_crit,
        ],
        "Repurpose": [
            _crit("SOH", f"{soh} %", f"≥ {t['repurpose_min_soh']} %", soh >= t["repurpose_min_soh"]),
            _crit("Modules hors seuil", bad_txt, "aucun", n_bad == 0),
            _crit("Accidents", accidents, f"≤ {t['max_accidents_other']}", accidents <= t["max_accidents_other"]),
            safety_crit,
        ],
        "Recycle": [_crit("Toujours possible", "—", "solution de repli", True)],
    }
    if drift is not None:
        criteria["Reuse"].insert(2, _crit(
            "Dérive de résistance (BMS)", f"{drift:+.0%} (module {drift_module})",
            f"≤ +{t['reuse_max_drift']:.0%} sur {len(readings)} relevés", drift <= t["reuse_max_drift"]))

    options = []
    for key in ORDER:
        crits = criteria[key]
        options.append(dict(key=key, **OPTIONS[key], criteria=crits,
                            eligible=all(c["ok"] for c in crits),
                            passed=sum(c["ok"] for c in crits), total=len(crits)))
    best = next(o for o in options if o["eligible"])

    notes = []
    if best["key"] == "Remanufacture":
        notes.append("Modules à remplacer : " + ", ".join(
            f"n°{m['index']} ({m['internalResistance_mOhm']} mΩ, max {m['maxInternalResistance_mOhm']})"
            for m in bad) + ".")
    if best["key"] == "Repurpose" and "LFP" in chemistry.upper():
        notes.append("Chimie LFP : très bonne tenue en cyclage, adaptée au stockage stationnaire.")
    if best["key"] == "Recycle":
        reasons = {}   # une seule fois chaque valeur (« modules hors seuil » = « à remplacer »)
        for o in options[:3]:
            for c in o["criteria"]:
                if not c["ok"]:
                    reasons.setdefault(str(c["value"]), f"{c['label']} : {c['value']}")
        if reasons:
            notes.append("Écarté des autres options : " + " ; ".join(reasons.values()) + ".")
    if drift is not None and drift > t["reuse_max_drift"]:
        notes.append(f"BMS : la résistance du module {drift_module} a évolué de {drift:+.0%} "
                     f"sur les {len(readings)} derniers relevés.")

    built = (p.get("battery") or {}).get("manufacturingDate")
    age = None
    if built:
        try:
            age = round((date.today() - date.fromisoformat(built)).days / 365.25, 1)
        except ValueError:
            pass

    return dict(recommended=best["key"], label=best["label"], status=best["status"],
                icon=best["icon"], summary=best["summary"], options=options, notes=notes,
                inputs=dict(soh=soh, badModules=n_bad, modules=n_mod, accidents=accidents,
                            cycleRatio=cycle_ratio, chemistry=chemistry, ageYears=age,
                            resistanceDrift=drift),
                materials=recoverable_materials(p))


def recoverable_materials(p):
    """Matériaux de la composition, avec repérage des matières critiques."""
    out = []
    for part_name, key in (("Cathode", "cathode"), ("Anode", "anode")):
        part = p.get(key) or {}
        for mat, pct in zip(part.get("materialsList") or [], part.get("percentageList") or []):
            out.append(dict(part=part_name, material=mat, percentage=pct,
                            critical=mat in CRITICAL_MATERIALS))
    return out


def record_orientation(repo, battery_id, center, choice, comment, reco):
    """Le centre de tri enregistre l'orientation retenue pour une batterie réceptionnée."""
    p = repo.get_passport(battery_id)
    if p is None:
        raise WorkflowError(f"Batterie {battery_id} introuvable.")
    if p["battery"]["status"] != "Waste":
        raise WorkflowError("Orientation impossible : le statut n'est pas « Waste ».")
    if not p.get("location") or p["location"].get("uid") != center["actor_uid"]:
        raise WorkflowError("Orientation impossible : la batterie n'a pas été réceptionnée par votre centre.")
    if repo.get_orientation(battery_id):
        raise WorkflowError("Une orientation a déjà été enregistrée pour cette batterie.")
    if choice not in OPTIONS:
        raise WorkflowError("Option d'orientation inconnue.")
    option = next(o for o in reco["options"] if o["key"] == choice)
    if not option["eligible"]:
        failed = ", ".join(c["label"] for c in option["criteria"] if not c["ok"])
        raise WorkflowError(f"« {option['label']} » n'est pas possible pour cette batterie "
                            f"(critères non remplis : {failed}).")
    comment = (comment or "").strip()
    if choice != reco["recommended"] and not comment:
        raise WorkflowError("Vous vous écartez de la recommandation : une justification est obligatoire.")
    repo.record_orientation(battery_id, center["actor_uid"], choice, reco["recommended"], comment)
