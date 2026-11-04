"""Défi 3 - Aide à la décision pour le centre de tri.

Recommande Reuse / Remanufacture / Repurpose / Recycle pour une batterie « Waste »
à partir des attributs officiels du Battery Pass (liste v1.2) et des demandes du marché.

Algorithme en deux étages :

  1. Faisabilité : règles éliminatoires (sécurité) et conditions de chaque option.
     Une option non faisable est exclue, avec sa raison.
  2. Score des options faisables (en points) :
         score = 100 × Σ(poids_c × adéquation_c(option)) / Σ poids        (score technique)
               + bonus de hiérarchie (économie circulaire : Reuse > Remanufacture > Repurpose > Recycle)
               + bonus marché (demandes actives compatibles × urgence × poids marché)
     La recommandation est l'option faisable au score le plus élevé.

Toutes les valeurs ci-dessous sont des HYPOTHÈSES PARAMÉTRABLES (pas des seuils réglementaires).
"""
from datetime import date

OPTIONS = ["Reuse", "Remanufacture", "Repurpose", "Recycle"]
OPTION_FR = {"Reuse": "Réutilisation (Reuse)", "Remanufacture": "Reconditionnement (Remanufacture)",
             "Repurpose": "Seconde vie, autre usage (Repurpose)", "Recycle": "Recyclage (Recycle)"}

# Critères et poids : CONFIGURATION du centre de tri (modifiable ici par le responsable, pas sur l'écran)
CRITERIA = {
    "sante": "Santé : SOCE vs seuil d'épuisement (#57, #83)",
    "modules": "Homogénéité des modules : résistance interne (#74, #75)",
    "usure": "Usure : cycles et âge (#6, #77, #78)",
    "stress": "Stress subi : températures extrêmes, décharges, surcharges (#87, #88, #91, #92)",
    "chimie": "Chimie et valeur des matériaux (#31, #32)",
}
DEFAULT_WEIGHTS = {"sante": 35, "modules": 25, "usure": 15, "stress": 15, "chimie": 10, "marche": 1.0}

DEFAULT_PARAMS = {
    "max_accidents": 2,          # accidents ≥ → Recycle obligatoire (#93)
    "max_deep_discharge": 5,     # décharges profondes ≥ → Recycle obligatoire (#91)
    "max_overcharge": 3,         # surcharges ≥ → Recycle obligatoire (#92)
    "min_soce_repurpose": 60,    # SOCE minimum pour une seconde vie stationnaire / légère
    "reman_margin": 15,          # Remanufacture si SOCE ≥ seuil d'épuisement - marge
    "max_modules_replaced": 2,   # Remanufacture : nb max de modules à remplacer
    "reman_health_gain": 0.25,   # gain de santé attendu après remplacement des modules (fraction de la marge)
    "temp_minutes_ref": 6000,    # minutes en températures extrêmes considérées comme « stress maximal »
    "events_ref": 5,             # nb d'événements (décharges + surcharges) = stress maximal
    "default_lifetime_years": 12,
    # Priorités du centre de tri (cases à cocher sur l'écran, stockées sur le centre dans le graphe)
    "use_market": True,          # tenir compte des demandes du marché
    "use_hierarchy": True,       # privilégier le réemploi avant le recyclage (hiérarchie UE des déchets)
}
HIERARCHY_BONUS = {"Reuse": 5, "Remanufacture": 3, "Repurpose": 2, "Recycle": 0}
URGENCY_BONUS = {"urgente": 20, "normale": 10, "faible": 5}

# Adéquation chimie / option (valeur des matériaux au recyclage, aptitude au stationnaire)
CHEMISTRY_FIT = {
    "NMC": {"Reuse": 0.5, "Remanufacture": 0.5, "Repurpose": 0.7, "Recycle": 1.0},  # Ni, Co : forte valeur
    "LFP": {"Reuse": 0.5, "Remanufacture": 0.5, "Repurpose": 1.0, "Recycle": 0.4},  # durable, peu de valeur
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _chem_family(chem):
    chem = (chem or "").upper()
    return "LFP" if "LFP" in chem else "NMC"


def extract_inputs(p, params=None, today=None):
    """Paramètres d'entrée de la décision, lus dans le Battery Passport."""
    params = {**DEFAULT_PARAMS, **(params or {})}
    dp, dd = p.get("dynamic_performance") or {}, p.get("dynamic_durability") or {}
    sd = p.get("static_durability") or {}
    circ = p.get("circularity") or {}
    modules = []
    for m in p.get("modules", []):
        r, r0, rmax = (m.get("internalResistance_mOhm"), m.get("initialInternalResistance_mOhm"),
                       m.get("maxInternalResistance_mOhm"))
        modules.append(dict(index=m["index"], r=r, rmax=rmax,
                            increase_pct=round((r - r0) / r0 * 100) if r is not None and r0 else None,
                            bad=r is not None and rmax is not None and r > rmax))
    built = p["battery"].get("manufacturingDate")
    today = today or date.today()
    age = (today - date.fromisoformat(built)).days / 365.25 if built else None
    soce = dp.get("soce", dp.get("soh"))
    return dict(
        soce=soce,
        threshold=sd.get("capacityThresholdForExhaustion", 80),
        capacity_fade=dp.get("capacityFade"),
        power_fade=dp.get("powerFade"),
        cycles=dd.get("cycleCount") or 0,
        expected_cycles=sd.get("expectedBatteryLifetimeCycles") or 1,
        age_years=round(age, 1) if age is not None else None,
        expected_years=sd.get("expectedLifetimeYears") or params["default_lifetime_years"],
        accidents=dd.get("accidents") or 0,
        deep_discharge=dd.get("deepDischargeEvents") or 0,
        overcharge=dd.get("overchargeEvents") or 0,
        temp_minutes=(dd.get("timeAboveTempMax_min") or 0) + (dd.get("timeBelowTempMin_min") or 0),
        chemistry=(p.get("composition") or {}).get("batteryChemistry"),
        model_id=(p.get("model") or {}).get("modelId"),
        modules=modules,
        bad_modules=[m["index"] for m in modules if m["bad"]],
        dismantling_manual=bool(circ.get("dismantlingManual")),
        spare_parts=bool(circ.get("sparePartsSources") or circ.get("partNumbers")),
    )


def _feasibility(x, params):
    """Renvoie {option: [raisons d'exclusion]} (liste vide = faisable)."""
    excl = {o: [] for o in OPTIONS}
    safety = []
    if x["accidents"] >= params["max_accidents"]:
        safety.append(f"{x['accidents']} accidents (seuil {params['max_accidents']})")
    if x["deep_discharge"] >= params["max_deep_discharge"]:
        safety.append(f"{x['deep_discharge']} décharges profondes (seuil {params['max_deep_discharge']})")
    if x["overcharge"] >= params["max_overcharge"]:
        safety.append(f"{x['overcharge']} surcharges (seuil {params['max_overcharge']})")
    if safety:
        for o in ("Reuse", "Remanufacture", "Repurpose"):
            excl[o].append("Règle de sécurité : " + ", ".join(safety))
        return excl, safety

    n_bad, soce, thr = len(x["bad_modules"]), x["soce"], x["threshold"]
    # Reuse : encore apte à un usage VE, aucun module défaillant
    if soce is None or soce < thr:
        excl["Reuse"].append(f"SOCE {soce} % sous le seuil d'épuisement constructeur ({thr} %)")
    if n_bad:
        excl["Reuse"].append(f"{n_bad} module(s) hors tolérance")
    # Remanufacture : 1 à N modules à remplacer, le reste proche du seuil, démontage documenté
    if n_bad == 0:
        excl["Remanufacture"].append("Aucun module à remplacer")
    elif n_bad > params["max_modules_replaced"]:
        excl["Remanufacture"].append(f"{n_bad} modules à remplacer (max {params['max_modules_replaced']})")
    if soce is not None and soce < thr - params["reman_margin"]:
        excl["Remanufacture"].append(f"SOCE {soce} % trop bas (< {thr - params['reman_margin']} %)")
    if not (x["dismantling_manual"] and x["spare_parts"]):
        excl["Remanufacture"].append("Manuel de démontage ou pièces détachées indisponibles (#36, #38)")
    # Repurpose : énergie suffisante pour un usage moins exigeant, modules défaillants écartés
    if soce is None or soce < params["min_soce_repurpose"]:
        excl["Repurpose"].append(f"SOCE {soce} % < {params['min_soce_repurpose']} % requis pour une seconde vie")
    if n_bad > params["max_modules_replaced"]:
        excl["Repurpose"].append(f"{n_bad} modules défaillants : pack trop hétérogène")
    return excl, safety


def _fits(x, params):
    """Adéquation (0 à 1) de chaque option pour chaque critère."""
    soce, thr, n_bad = x["soce"] or 0, x["threshold"], len(x["bad_modules"])
    u = max(x["cycles"] / x["expected_cycles"],
            (x["age_years"] or 0) / x["expected_years"])
    u = _clamp(u)
    z = _clamp((x["deep_discharge"] + x["overcharge"]) / params["events_ref"]
               + x["temp_minutes"] / params["temp_minutes_ref"])
    chem = CHEMISTRY_FIT[_chem_family(x["chemistry"])]
    return {
        "Reuse": dict(sante=0.5 + 0.5 * _clamp((soce - thr) / 15), modules=1.0 if n_bad == 0 else 0.0,
                      usure=1 - u, stress=1 - z, chimie=chem["Reuse"]),
        "Remanufacture": dict(sante=_clamp((soce - (thr - params["reman_margin"])) / params["reman_margin"]
                                     + params["reman_health_gain"]),
                              modules=1.0 if 1 <= n_bad <= params["max_modules_replaced"] else 0.0,
                              usure=1 - 0.7 * u, stress=1 - z, chimie=chem["Remanufacture"]),
        "Repurpose": dict(sante=1.0 if params["min_soce_repurpose"] <= soce < thr else (0.6 if soce >= thr else 0.0),
                          modules=_clamp(1 - 0.3 * n_bad), usure=1 - 0.5 * u, stress=1 - 0.7 * z,
                          chimie=chem["Repurpose"]),
        "Recycle": dict(sante=_clamp((thr - soce) / 30), modules=_clamp(n_bad / 5), usure=u, stress=z,
                        chimie=chem["Recycle"]),
    }, dict(usure=round(u, 2), stress=round(z, 2))


def matching_demands(option, x, demands):
    """Demandes actives du marché compatibles avec l'option et la batterie."""
    out = []
    for d in demands:
        if not d.get("active") or d.get("option") != option:
            continue
        chems = d.get("chemistries") or []
        if chems and x["chemistry"] not in chems:
            continue
        if option != "Recycle" and (x["soce"] or 0) < (d.get("minSoce") or 0):
            continue
        out.append(d)
    return out


def recommend(passport, demands, weights=None, params=None, today=None):
    """Calcule la recommandation, les scores de chaque option et la justification."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    params = {**DEFAULT_PARAMS, **(params or {})}
    x = extract_inputs(passport, params, today)
    excl, safety = _feasibility(x, params)
    fits, indices = _fits(x, params)
    total_w = sum(w[c] for c in CRITERIA) or 1

    options = []
    for o in OPTIONS:
        technical = 100 * sum(w[c] * fits[o][c] for c in CRITERIA) / total_w
        matched = matching_demands(o, x, demands)
        market = (w["marche"] * sum(URGENCY_BONUS.get(d.get("urgency"), 10) for d in matched)
                  if params["use_market"] else 0.0)
        hierarchy = HIERARCHY_BONUS[o] if params["use_hierarchy"] else 0
        feasible = not excl[o]
        options.append(dict(
            option=o, label=OPTION_FR[o], feasible=feasible, excluded_because=excl[o],
            technical=round(technical, 1), hierarchy=hierarchy, market=round(market, 1),
            score=round(technical + hierarchy + market, 1) if feasible else None,
            criteria={c: round(fits[o][c], 2) for c in CRITERIA},
            demands=([dict(uid=d["uid"], title=d["title"], urgency=d.get("urgency")) for d in matched]
                     if params["use_market"] else []),
        ))
    ranked = sorted((o for o in options if o["feasible"]), key=lambda o: o["score"], reverse=True)
    best = ranked[0]
    # Option techniquement la meilleure (sans marché), pour montrer l'effet du marché
    tech_best = max((o for o in options if o["feasible"]),
                    key=lambda o: o["technical"] + o["hierarchy"])

    just = []
    if safety:
        just.append("⛔ Règle de sécurité : " + ", ".join(safety) + " → seul le recyclage est autorisé.")
    just.append(f"SOCE {x['soce']} % pour un seuil d'épuisement constructeur de {x['threshold']} % "
                + ("(encore apte à un usage VE)." if (x["soce"] or 0) >= x["threshold"] else "(plus apte à un usage VE)."))
    if x["bad_modules"]:
        details = ", ".join(f"module {m['index']} : {m['r']} mΩ (+{m['increase_pct']} %)"
                            for m in x["modules"] if m["bad"])
        just.append(f"{len(x['bad_modules'])} module(s) hors tolérance : {details}.")
    else:
        just.append("Tous les modules sont dans les tolérances constructeur.")
    just.append(f"Usure {round(indices['usure'] * 100)} % ({x['cycles']}/{x['expected_cycles']} cycles, "
                f"{x['age_years']} ans) · stress {round(indices['stress'] * 100)} % · chimie {x['chemistry']}.")
    for o in options:
        if not o["feasible"] and not safety:
            just.append(f"{o['option']} exclu : " + " ; ".join(o["excluded_because"]) + ".")
    if best["demands"]:
        just.append(f"Demande(s) du marché pour {best['option']} : "
                    + ", ".join(f"{d['title']} ({d['urgency']})" for d in best["demands"]) + ".")
    if not params["use_market"]:
        just.append("Priorité du centre : demandes du marché ignorées, chaque batterie va vers son usage idéal.")
    if not params["use_hierarchy"]:
        just.append("Priorité du centre : pas de préférence pour le réemploi avant le recyclage.")
    if tech_best["option"] != best["option"]:
        just.append(f"⚖️ Techniquement, {tech_best['option']} était préférable : la demande du marché "
                    f"fait basculer la recommandation vers {best['option']}.")
    if len(ranked) > 1:
        just.append(f"Écart avec l'option suivante ({ranked[1]['option']}) : "
                    f"{round(best['score'] - ranked[1]['score'], 1)} points.")

    # Résumé court pour l'écran : action à mener, 3 raisons clés, netteté de la décision
    bad = ", ".join(str(i) for i in x["bad_modules"])
    action = {
        "Reuse": "Remettre la batterie telle quelle dans un véhicule",
        "Remanufacture": f"Remplacer le{'s' if len(x['bad_modules']) > 1 else ''} module{'s' if len(x['bad_modules']) > 1 else ''} {bad} puis remettre sur le marché",
        "Repurpose": "Réaffecter à un usage moins exigeant",
        "Recycle": "Démonter et recycler les matériaux",
    }[best["option"]]
    highlights = []
    if safety:
        highlights.append("⛔ Sécurité : " + ", ".join(safety))
    else:
        soce, thr = x["soce"], x["threshold"]
        highlights.append(f"🔋 SOCE {soce} % {'≥' if (soce or 0) >= thr else '<'} seuil VE {thr} %")
        if x["bad_modules"]:
            worst = max((m for m in x["modules"] if m["bad"]), key=lambda m: m["increase_pct"] or 0)
            highlights.append(f"🔧 Module{'s' if len(x['bad_modules']) > 1 else ''} {bad} hors tolérance "
                              f"(jusqu'à +{worst['increase_pct']} % de résistance)")
        else:
            highlights.append("🔧 Modules homogènes, dans les tolérances")
    if best["demands"] and best["market"] > 0:
        highlights.append(f"🛒 {best['demands'][0]['title']} ({best['demands'][0]['urgency']})")
    elif not safety:
        highlights.append(f"⏳ Usure {round(indices['usure'] * 100)} % · {x['chemistry']}")
    gap = round(best["score"] - ranked[1]["score"], 1) if len(ranked) > 1 else None

    return dict(recommendation=best["option"], options=options, inputs=x, indices=indices,
                justification=just, weights=w, params=params,
                market_driven=tech_best["option"] != best["option"],
                action=action, highlights=highlights, gap=gap,
                priorities=dict(use_market=params["use_market"], use_hierarchy=params["use_hierarchy"]),
                runner_up=ranked[1]["option"] if len(ranked) > 1 else None)
