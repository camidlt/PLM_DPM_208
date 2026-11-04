"""Jeu de données de démo du Battery Passport.

Source unique des données : utilisé à la fois par le mode mémoire et pour
générer le script Cypher (data/seed.cypher) qui remplit Neo4j.

Le graphe suit le modèle de la Figure 1 du sujet (Company, Type, Model,
EconomicOperator, BatteryInstance, Composition, Anode/Cathode/Electrolyte,
StaticPerformance, StaticDurability, CarbonFootprint, Certification,
Circularity, DynamicPerformance, DynamicDurability), avec ces extensions :

  (:Actor)            garage, propriétaire, centres de tri
  (:Module)           5 modules par batterie, résistance interne (défi 1)
  (:TelemetryReading) relevés BMS horodatés (défi 1)
  (:Event)            historique de la batterie
  (:Notification)     demande du garagiste vers le propriétaire
  (:TransferOrder)    ordre de transfert vers un centre de tri
  (:LogisticsStep)    étapes signées du transfert (défi 2)
  (:Message)          notifications in-app / mail (défi 2)

Chaque nœud porte une propriété technique `uid` unique.
"""

NODES = []  # (label, uid, props)
RELS = []   # (from_uid, REL_TYPE, to_uid)


def node(label, uid, **props):
    NODES.append((label, uid, {"uid": uid, **props}))
    return uid


def rel(a, rel_type, b):
    RELS.append((a, rel_type, b))


# --- Acteurs -----------------------------------------------------------------
node("Company", "CMP-FLUX", name="Flux Motors")
node("Type", "TYPE-EV", name="Batterie de traction VE")
rel("CMP-FLUX", "HAS_TYPE", "TYPE-EV")

node("EconomicOperator", "EO-FLUX",
     name="Flux Motors SAS", address="1 avenue du Temps, 92000 Nanterre",
     country="FR", email="passport@fluxmotors.example",
     phone="+33 1 00 00 00 00", website="https://fluxmotors.example")
rel("CMP-FLUX", "HAS_ECONOMIC_OPERATOR", "EO-FLUX")

node("Actor", "OWNER-FLUX", name="Responsable Battery Passport - Flux Motors",
     role="proprietaire", city="Nanterre", email="passport@fluxmotors.example")
rel("OWNER-FLUX", "REPRESENTS", "EO-FLUX")

node("Actor", "GARAGE-HV", name="Garage Hill Valley", role="garagiste",
     city="Nanterre", address="12 rue de l'Horloge, 92000 Nanterre",
     email="atelier@garage-hv.example", siret="000 000 001 00011")
# Défi 2 : un agrément a une date de fin de validité ; acceptsDamaged = installation
# équipée pour stocker des batteries endommagées (ADR DS 376)
node("Actor", "CT-NANTERRE", name="Centre de tri Recyclo Nanterre",
     role="centre_tri", city="Nanterre", agreed=True,
     agreementNumber="AGR-92-2025-014", agreementValidUntil="2030-12-31", acceptsDamaged=True,
     address="5 rue des Recycleurs, 92000 Nanterre", email="reception@recyclo.example")
node("Actor", "CT-LYON", name="Centre de tri Rhône Batteries",
     role="centre_tri", city="Lyon", agreed=True,
     agreementNumber="AGR-69-2024-087", agreementValidUntil="2029-06-30", acceptsDamaged=False,
     address="40 quai du Rhône, 69007 Lyon", email="quai@rhone-batteries.example")
node("Actor", "BMS-GATEWAY", name="Passerelle BMS (télémétrie)", role="bms")
node("Actor", "CT-EXPRESS", name="Dépôt Batteries Express", role="centre_tri",
     city="Créteil", agreed=False, agreementNumber="")

# Défi 2 : transporteurs. Agréé = habilité ADR (classe 9) + déclaré transporteur de déchets.
node("Actor", "TR-TRANSBAT", name="TransBat Logistique", role="transporteur",
     city="Gennevilliers", agreed=True, adr=True, damagedCapable=True,
     agreementNumber="Récépissé transport déchets 92-2024-T-0412", agreementValidUntil="2028-06-30",
     email="exploitation@transbat.example")
node("Actor", "TR-VOLTEXPRESS", name="Volt Express", role="transporteur",
     city="Lyon", agreed=True, adr=True, damagedCapable=False,
     agreementNumber="Récépissé transport déchets 69-2023-T-0187", agreementValidUntil="2027-03-31",
     email="dispatch@voltexpress.example")
node("Actor", "TR-RAPIDFRET", name="Rapid Fret", role="transporteur",
     city="Créteil", agreed=False, adr=False, damagedCapable=False, agreementNumber="",
     email="contact@rapidfret.example")

# --- Modèles -----------------------------------------------------------------
MODELS = {
    "MOD-FC85": dict(modelId="FC-85", name="FluxCap 85 kWh", chemistry="NMC 811",
                     cathode=(["Nickel", "Manganese", "Cobalt", "Lithium"], [56, 7, 7, 30], [False, False, False, False]),
                     anode=(["Graphite", "Silicium"], [92, 8], [False, False]),
                     electrolyte=(["LiPF6", "EC/DMC"], [15, 85], [False, False]),
                     volt=(280, 355, 403), capacity=85, cycles=1500, carbon=61.0, cls="B", weight=520),
    "MOD-FC60L": dict(modelId="FC-60L", name="FluxCap 60 kWh LFP", chemistry="LFP",
                      cathode=(["Fer", "Phosphate", "Lithium"], [35, 45, 20], [False, False, False]),
                      anode=(["Graphite"], [100], [False]),
                      electrolyte=(["LiPF6", "EC/DMC"], [15, 85], [False, False]),
                      volt=(260, 320, 365), capacity=60, cycles=3500, carbon=48.5, cls="A", weight=410),
}

for mid, m in MODELS.items():
    node("Model", mid, modelId=m["modelId"], name=m["name"], ratedCapacity_kWh=m["capacity"],
         weight_kg=m["weight"])
    rel("TYPE-EV", "HAS_MODEL", mid)
    comp = node("Composition", f"COMP-{mid}", batteryChemistry=m["chemistry"])
    rel(mid, "HAS_COMPOSITION", comp)
    for part, rel_type, key in (("Cathode", "HAS_CATHODE", "cathode"),
                                ("Anode", "HAS_ANODE", "anode"),
                                ("Electrolyte", "HAS_ELECTROLYTE", "electrolyte")):
        mats, pct, ren = m[key]
        rel(comp, rel_type, node(part, f"{part.upper()}-{mid}", materialsList=mats,
                                 percentageList=pct, isRenewable=ren))
    rel(mid, "HAS_STATIC_PERFORMANCE", node(
        "StaticPerformance", f"SP-{mid}", minimalVoltage=m["volt"][0],
        nominalVoltage=m["volt"][1], maximalVoltage=m["volt"][2]))
    rel(mid, "HAS_STATIC_DURABILITY", node(
        "StaticDurability", f"SD-{mid}", expectedBatteryLifetimeCycles=m["cycles"],
        cRateRelevantCycleLifeTest="C/3"))
    cf = node("CarbonFootprint", f"CF-{mid}", carbonFootprintDeclared=m["carbon"],
              unit="kg CO2e / kWh", performanceClass=m["cls"],
              link=f"https://fluxmotors.example/lca/{m['modelId']}")
    rel(mid, "HAS_CARBON_FOOTPRINT", cf)
    rel("EO-FLUX", "HAS_CARBON_FOOTPRINT", cf)
    rel(mid, "HAS_CERTIFICATION", node(
        "Certification", f"CERT-{mid}", separateCollectionSymbol=True,
        EUDeclarationOfConformityId=f"EU-DoC-{m['modelId']}-2024",
        EUDeclarationOfConformity=f"https://fluxmotors.example/doc/{m['modelId']}.pdf"))
    rel(mid, "HAS_CIRCULARITY", node(
        "Circularity", f"CIRC-{mid}", extinguishAgent="Eau (refroidissement massif)",
        dismantlingManual=f"https://fluxmotors.example/dismantling/{m['modelId']}",
        partNumbers=f"https://fluxmotors.example/parts/{m['modelId']}"))

# --- Batteries ---------------------------------------------------------------
# Résistance interne max par module définie par le constructeur (mΩ)
MAX_R = {"MOD-FC85": 2.0, "MOD-FC60L": 2.5}

BATTERIES = [
    # La batterie de Doc : un module (n°3) a une résistance interne anormale
    dict(id="BAT-DOC-001", model="MOD-FC85", serial="FC85-2019-004221", built="2019-03-12",
         vehicle="DeLorean EV - VIN fictif FLUXDMC1985", status="Original", soh=71, soc=38,
         cycles=1240, accidents=0, warranty="2027-03-12", location="GARAGE-HV",
         modules=[1.3, 1.4, 6.8, 1.2, 1.5]),
    dict(id="BAT-002", model="MOD-FC85", serial="FC85-2023-118734", built="2023-06-02",
         vehicle="Flux Roadster - VIN fictif FLUXRD2023", status="Original", soh=93, soc=76,
         cycles=310, accidents=0, warranty="2031-06-02", location="GARAGE-HV",
         modules=[1.1, 1.1, 1.2, 1.0, 1.1]),
    dict(id="BAT-003", model="MOD-FC60L", serial="FC60L-2020-052310", built="2020-10-20",
         vehicle="Flux City - VIN fictif FLUXCT2020", status="Original", soh=64, soc=52,
         cycles=2100, accidents=1, warranty="2028-10-20", location="GARAGE-HV",
         modules=[2.2, 2.1, 2.3, 2.2, 2.4]),
    dict(id="BAT-004", model="MOD-FC85", serial="FC85-2018-001876", built="2018-01-15",
         vehicle="Flux Roadster - VIN fictif FLUXRD2018", status="Waste", soh=48, soc=0,
         cycles=1980, accidents=2, warranty="2026-01-15", location="CT-NANTERRE",
         modules=[3.1, 2.9, 3.4, 3.0, 3.6]),
]

SEED_DATE = "2026-11-03"

# Défi 1 : relevés BMS mensuels. Facteur appliqué à la valeur actuelle de chaque module.
TELEMETRY_DATES = [f"2026-{m:02d}-03T09:00:00" for m in range(6, 12)]
TELEMETRY_AGING = [0.93, 0.94, 0.96, 0.97, 0.99, 1.0]            # vieillissement normal
TELEMETRY_DRIFT = {("BAT-DOC-001", 3): [0.22, 0.24, 0.28, 0.38, 0.6, 1.0]}  # module 3 de Doc

for b in BATTERIES:
    bid = b["id"]
    node("BatteryInstance", bid, batteryId=bid, batteryPassportId=f"BP-{bid}",
         serialNumber=b["serial"], manufacturingDate=b["built"], vehicle=b["vehicle"],
         status=b["status"])
    rel(b["model"], "HAS_BATTERY_INSTANCE", bid)
    rel("EO-FLUX", "BUILD", bid)
    rel(bid, "LOCATED_AT", b["location"])
    rel(bid, "HAS_DYNAMIC_PERFORMANCE", node(
        "DynamicPerformance", f"DP-{bid}", soh=b["soh"], soc=b["soc"],
        measuredAt=f"{SEED_DATE}T09:00:00"))
    rel(bid, "HAS_DYNAMIC_DURABILITY", node(
        "DynamicDurability", f"DD-{bid}", warranty=b["warranty"], accidents=b["accidents"],
        cycleCount=b["cycles"]))
    for i, r in enumerate(b["modules"], start=1):
        rel(bid, "HAS_MODULE", node(
            "Module", f"MODULE-{bid}-{i}", index=i, internalResistance_mOhm=r,
            maxInternalResistance_mOhm=MAX_R[b["model"]], measuredAt=f"{SEED_DATE}T09:00:00"))

    # Défi 1 : historique des relevés BMS (un par mois, le dernier = valeurs actuelles)
    for k, at in enumerate(TELEMETRY_DATES):
        res = [round(r * TELEMETRY_DRIFT.get((bid, i), TELEMETRY_AGING)[k], 2)
               for i, r in enumerate(b["modules"], start=1)]
        rel(bid, "HAS_TELEMETRY", node(
            "TelemetryReading", f"TEL-{bid}-{k + 1}", at=at, source="BMS",
            soh=b["soh"] + (len(TELEMETRY_DATES) - 1 - k), soc=b["soc"],
            moduleIndexes=list(range(1, len(res) + 1)), resistances=res))

    events = [("MANUFACTURED", b["built"] + "T08:00:00", "Flux Motors SAS", "Batterie produite et passeport créé"),
              ("PUT_ON_MARKET", b["built"][:4] + "-12-01T10:00:00", "Flux Motors SAS", "Mise sur le marché")]
    if b["id"] == "BAT-DOC-001":
        events.append(("MAINTENANCE", "2024-05-14T14:30:00", "Garage Hill Valley", "Contrôle annuel - RAS"))
        events.append(("BMS_ALERT", "2026-09-03T09:00:00", "Passerelle BMS (télémétrie)",
                       "Module 3 : 2.58 mΩ > max 2.0 mΩ (seuil constructeur dépassé)"))
    if b["status"] == "Waste":
        events += [("STATUS_CHANGED", "2026-09-02T11:00:00", "Responsable Battery Passport - Flux Motors", "Original → Waste"),
                   ("RECEIVED", "2026-09-10T15:20:00", "Centre de tri Recyclo Nanterre", "Batterie réceptionnée")]
    for k, (etype, at, actor, details) in enumerate(events, start=1):
        rel(bid, "HAS_EVENT", node("Event", f"EVT-{bid}-{k}", type=etype, at=at,
                                   actorName=actor, details=details))


# --- Export Cypher -----------------------------------------------------------
def _lit(v):
    import json
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    return json.dumps(v, ensure_ascii=False)


def cypher_statements():
    """Liste d'instructions Cypher (une par élément) qui recréent le jeu de démo."""
    labels = sorted({label for label, _, _ in NODES})
    out = [f"CREATE CONSTRAINT bp_{label.lower()}_uid IF NOT EXISTS "
           f"FOR (n:{label}) REQUIRE n.uid IS UNIQUE" for label in labels]
    out += [f"CREATE CONSTRAINT bp_{label.lower()}_uid IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.uid IS UNIQUE" for label in ("Notification", "TransferOrder", "OrientationDecision", "LogisticsStep", "Message")]
    label_of = {uid: label for label, uid, _ in NODES}
    for label, uid, props in NODES:
        body = ", ".join(f"{k}: {_lit(v)}" for k, v in props.items())
        out.append(f"MERGE (n:{label} {{uid: {_lit(uid)}}}) SET n += {{{body}}}")
    for a, rel_type, b in RELS:
        out.append(f"MATCH (a:{label_of[a]} {{uid: {_lit(a)}}}), (b:{label_of[b]} {{uid: {_lit(b)}}}) "
                   f"MERGE (a)-[:{rel_type}]->(b)")
    return out
