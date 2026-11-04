// =====================================================================
// Battery Passport – jeu de données de démo (aucun dump fourni : données construites par l'équipe)
// Respecte le modèle Capgemini (Figure 1 du sujet). Les EXTENSIONS de l'équipe sont marquées ★.
// Idempotent : MERGE + ON CREATE pour les données qui évoluent (statut, SOC…), on peut relancer.
//
// Sources des ordres de grandeur : Règlement (UE) 2023/1542 Annexe XIII (contenu du passeport),
// fiches techniques publiques de cellules NMC/LFP. Les entreprises et personnes sont FICTIVES.
// =====================================================================

CREATE CONSTRAINT battery_id IF NOT EXISTS FOR (b:BatteryInstance) REQUIRE b.batteryId IS UNIQUE;
CREATE CONSTRAINT model_id IF NOT EXISTS FOR (m:Model) REQUIRE m.modelId IS UNIQUE;
CREATE CONSTRAINT module_id IF NOT EXISTS FOR (m:Module) REQUIRE m.moduleId IS UNIQUE;
CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE;
CREATE CONSTRAINT operator_name IF NOT EXISTS FOR (o:EconomicOperator) REQUIRE o.name IS UNIQUE;

// ---------------------------------------------------------------------
// 1) Fabricants, opérateurs économiques, types
// ---------------------------------------------------------------------
UNWIND [
  {company: 'Doc Brown Industries', operator: 'DeLorean Motor Company',
   address: '1640 Riverside Drive, Hill Valley', country: 'FR', email: 'passport@dmc.example',
   phone: '+33 1 85 19 85 00', weblink: 'https://dmc.example'},
  {company: 'Hill Valley Energy', operator: 'HVE Manufacturing Europe',
   address: 'ZI des Lumières, 59000 Lille', country: 'FR', email: 'compliance@hve.example',
   phone: '+33 3 20 20 15 00', weblink: 'https://hve.example'},
  {company: 'Mr. Fusion Mobility', operator: 'Mr. Fusion GmbH',
   address: 'Energiestraße 12, 70173 Stuttgart', country: 'DE', email: 'bp@mrfusion.example',
   phone: '+49 711 1955 000', weblink: 'https://mrfusion.example'}
] AS d
MERGE (c:Company {name: d.company})
MERGE (o:EconomicOperator {name: d.operator})
SET o.address = d.address, o.country = d.country, o.email = d.email, o.phone = d.phone, o.weblink = d.weblink
MERGE (c)-[:HAS_ECONOMIC_OPERATOR]->(o);

// ---------------------------------------------------------------------
// 2) Modèles de batterie + toutes leurs données statiques
// ---------------------------------------------------------------------
UNWIND [
  {modelId: 'FC-88', name: 'Flux Capacitor Pack FC-88 (75 kWh)', company: 'Doc Brown Industries',
   operator: 'DeLorean Motor Company', type: 'Electric Vehicle Battery',
   chemistry: 'NMC 811 / Graphite-Si', minV: 280.0, nomV: 355.0, maxV: 403.0, maxIR: 25.0,
   cycles: 2000, cRate: 1.0, cf: 61.5, cfClass: 'B', extinguish: 'Water (large quantities) – Class D not required',
   anode: ['Graphite', 'Silicon oxide', 'Copper foil', 'Binder (SBR/CMC)'], anodePct: [86, 6, 6, 2], anodeRen: [false, false, false, false],
   cathode: ['LiNi0.8Mn0.1Co0.1O2', 'Aluminium foil', 'Carbon black', 'PVDF binder'], cathodePct: [90, 5, 3, 2], cathodeRen: [false, false, false, false],
   electrolyte: ['LiPF6', 'Ethylene carbonate', 'Ethyl methyl carbonate', 'Additives (VC/FEC)'], electrolytePct: [13, 30, 52, 5], electrolyteRen: [false, false, false, false]},
  {modelId: 'HV-LFP-60', name: 'Hoverboard LFP Pack HV-60 (60 kWh)', company: 'Hill Valley Energy',
   operator: 'HVE Manufacturing Europe', type: 'Electric Vehicle Battery',
   chemistry: 'LFP / Graphite', minV: 250.0, nomV: 320.0, maxV: 365.0, maxIR: 20.0,
   cycles: 3500, cRate: 1.0, cf: 48.2, cfClass: 'A', extinguish: 'Water / foam',
   anode: ['Graphite', 'Copper foil', 'Binder (SBR/CMC)'], anodePct: [91, 7, 2], anodeRen: [false, false, false],
   cathode: ['LiFePO4', 'Aluminium foil', 'Carbon black', 'PVDF binder'], cathodePct: [88, 6, 4, 2], cathodeRen: [false, false, false, false],
   electrolyte: ['LiPF6', 'Ethylene carbonate', 'Dimethyl carbonate'], electrolytePct: [12, 44, 44], electrolyteRen: [false, false, false]},
  {modelId: 'MF-48', name: 'Mr. Fusion e-Bike Pack MF-48 (0,75 kWh)', company: 'Mr. Fusion Mobility',
   operator: 'Mr. Fusion GmbH', type: 'Light Means of Transport Battery',
   chemistry: 'NMC 622 / Graphite', minV: 39.0, nomV: 48.0, maxV: 54.6, maxIR: 60.0,
   cycles: 1000, cRate: 0.5, cf: 72.0, cfClass: 'C', extinguish: 'Water / sand',
   anode: ['Graphite', 'Copper foil', 'Binder'], anodePct: [90, 8, 2], anodeRen: [false, false, false],
   cathode: ['LiNi0.6Mn0.2Co0.2O2', 'Aluminium foil', 'Carbon black', 'PVDF binder'], cathodePct: [89, 6, 3, 2], cathodeRen: [false, false, false, false],
   electrolyte: ['LiPF6', 'Ethylene carbonate', 'Diethyl carbonate'], electrolytePct: [12, 40, 48], electrolyteRen: [false, false, false]},
  {modelId: 'CT-200', name: 'Clocktower Storage Unit CT-200 (200 kWh)', company: 'Hill Valley Energy',
   operator: 'HVE Manufacturing Europe', type: 'Industrial Battery',
   chemistry: 'LFP / Graphite', minV: 672.0, nomV: 768.0, maxV: 876.0, maxIR: 18.0,
   cycles: 6000, cRate: 0.5, cf: 45.0, cfClass: 'A', extinguish: 'Water / aerosol system',
   anode: ['Graphite', 'Copper foil', 'Binder (SBR/CMC)'], anodePct: [91, 7, 2], anodeRen: [false, false, false],
   cathode: ['LiFePO4', 'Aluminium foil', 'Carbon black', 'PVDF binder'], cathodePct: [88, 6, 4, 2], cathodeRen: [false, false, false, false],
   electrolyte: ['LiPF6', 'Ethylene carbonate', 'Dimethyl carbonate'], electrolytePct: [12, 44, 44], electrolyteRen: [false, false, false]}
] AS d
MATCH (c:Company {name: d.company}), (o:EconomicOperator {name: d.operator})
MERGE (t:Type {name: d.type})
MERGE (c)-[:HAS_TYPE]->(t)
MERGE (m:Model {modelId: d.modelId}) SET m.name = d.name
MERGE (t)-[:HAS_MODEL]->(m)

MERGE (sp:StaticPerformance {modelId: d.modelId})
SET sp.minimalVoltage = d.minV, sp.nominalVoltage = d.nomV, sp.maximalVoltage = d.maxV, sp.voltageUnit = 'V',
    sp.maxInternalResistance = d.maxIR, sp.internalResistanceUnit = 'mOhm'          // ★ seuil constructeur par module
MERGE (m)-[:HAS_STATIC_PERFORMANCE]->(sp)

MERGE (sd:StaticDurability {modelId: d.modelId})
SET sd.expectedBatteryLifetimeCycles = d.cycles, sd.cRateRelevantCycleLifeTest = d.cRate, sd.cRateUnit = 'A/Ah'
MERGE (m)-[:HAS_STATIC_DURABILITY]->(sd)

MERGE (cert:Certification {modelId: d.modelId})
SET cert.EUDeclarationOfConformityId = 'EU-DoC-' + d.modelId + '-2026',
    cert.EUDeclarationOfConformity = 'https://docs.example/' + d.modelId + '/eu-declaration-of-conformity.pdf',
    cert.separateCollectionSymbol = 'Crossed-out wheeled bin (EN IEC 62902)'
MERGE (m)-[:HAS_CERTIFICATION]->(cert)

MERGE (circ:Circularity {modelId: d.modelId})
SET circ.extinguishAgent = d.extinguish,
    circ.partNumbers = 'https://docs.example/' + d.modelId + '/spare-parts'
MERGE (m)-[:HAS_CIRCULARITY]->(circ)

MERGE (cf:CarbonFootprint {modelId: d.modelId})
SET cf.carbonFootprintDeclared = d.cf, cf.unit = 'kg CO2e / kWh', cf.performanceClass = d.cfClass,
    cf.linkStudy = 'https://docs.example/' + d.modelId + '/carbon-footprint-study.pdf'
MERGE (m)-[:HAS_CARBON_FOOTPRINT]->(cf)
MERGE (o)-[:HAS_CARBON_FOOTPRINT]->(cf)

MERGE (comp:Composition {composition_id: d.modelId + '-COMP'}) SET comp.batteryChemistry = d.chemistry
MERGE (m)-[:HAS_COMPOSITION]->(comp)
MERGE (an:Anode {anodeId: d.modelId + '-AN'})
SET an.anodeMaterialsList = d.anode, an.percentageList = d.anodePct, an.isRenewable = d.anodeRen
MERGE (comp)-[:HAS_ANODE]->(an)
MERGE (ca:Cathode {cathodeId: d.modelId + '-CA'})
SET ca.cathodeMaterialsList = d.cathode, ca.percentageList = d.cathodePct, ca.isRenewable = d.cathodeRen
MERGE (comp)-[:HAS_CATHODE]->(ca)
MERGE (el:Electrolyte {electrolyteId: d.modelId + '-EL'})
SET el.electrolyteMaterialsList = d.electrolyte, el.percentageList = d.electrolytePct, el.isRenewable = d.electrolyteRen
MERGE (comp)-[:HAS_ELECTROLYTE]->(el);

// ---------------------------------------------------------------------
// 3) Batteries physiques (instances) + données dynamiques
//    soce = State of Certified Energy (≈ SOH en énergie), soc = State of Charge
// ---------------------------------------------------------------------
UNWIND [
  {id: 'DLR-1985', model: 'FC-88', status: 'Original', soce: 71, soc: 64, warranty: '2033-10-26',
   made: '2025-10-26', place: 'Hill Valley Gigafactory (FR)', serial: 'FC88-25-001985', weight: 478,
   owner: 'Dr. Emmett Brown', vehicle: 'DeLorean DMC-12 (VIN fictif 1985HV)'},
  {id: 'DLR-2015', model: 'FC-88', status: 'Original', soce: 94, soc: 80, warranty: '2034-10-21',
   made: '2026-02-11', place: 'Hill Valley Gigafactory (FR)', serial: 'FC88-26-002015', weight: 478,
   owner: 'Marty McFly', vehicle: 'DeLorean DMC-12 (VIN fictif 2015HV)'},
  {id: 'DLR-1955', model: 'FC-88', status: 'Waste', soce: 38, soc: 0, warranty: '2033-11-05',
   made: '2025-11-05', place: 'Hill Valley Gigafactory (FR)', serial: 'FC88-25-001955', weight: 478,
   owner: 'Biff Tannen', vehicle: 'Ford Super De Luxe (VIN fictif 1955HV)'},
  {id: 'HVB-0001', model: 'HV-LFP-60', status: 'Original', soce: 97, soc: 55, warranty: '2034-03-01',
   made: '2026-03-01', place: 'Lille (FR)', serial: 'HV60-26-000001', weight: 395,
   owner: 'Jennifer Parker', vehicle: 'Citadine électrique (VIN fictif)'},
  {id: 'HVB-0002', model: 'HV-LFP-60', status: 'Repurposed', soce: 76, soc: 90, warranty: '2033-06-15',
   made: '2025-06-15', place: 'Lille (FR)', serial: 'HV60-25-000002', weight: 395,
   owner: 'Station de recharge A6 (stockage stationnaire)', vehicle: '—'},
  {id: 'MF-0042', model: 'MF-48', status: 'Reused', soce: 82, soc: 70, warranty: '2028-04-20',
   made: '2026-04-20', place: 'Stuttgart (DE)', serial: 'MF48-26-000042', weight: 4.1,
   owner: 'Loueur de VTT Hill Valley', vehicle: 'VTT électrique'},
  {id: 'CTS-1885', model: 'CT-200', status: 'Original', soce: 90, soc: 48, warranty: '2036-01-01',
   made: '2026-01-01', place: 'Lille (FR)', serial: 'CT200-26-001885', weight: 1650,
   owner: 'Mairie de Hill Valley (stockage solaire)', vehicle: '—'}
] AS d
MATCH (m:Model {modelId: d.model})<-[:HAS_MODEL]-(:Type)<-[:HAS_TYPE]-(:Company)-[:HAS_ECONOMIC_OPERATOR]->(o:EconomicOperator)
MERGE (b:BatteryInstance {batteryId: d.id})
  ON CREATE SET b.status = d.status
SET b.batteryPassportId = 'BP-' + d.id,
    b.serialNumber = d.serial, b.manufacturingDate = d.made, b.manufacturingPlace = d.place,   // ★
    b.weightKg = d.weight, b.currentHolder = d.owner, b.installedIn = d.vehicle               // ★
MERGE (m)-[:HAS_BATTERY_INSTANCE]->(b)
MERGE (o)-[:BUILD]->(b)
MERGE (dd:DynamicDurability {batteryId: d.id})
SET dd.warranty = d.warranty, dd.accidents = 'Aucun accident déclaré'
MERGE (b)-[:HAS_DYNAMIC_DURABILITY]->(dd)
MERGE (dp:DynamicPerformance {batteryId: d.id})
  ON CREATE SET dp.soce = d.soce, dp.soc = d.soc, dp.unit = '%'
MERGE (b)-[:HAS_DYNAMIC_PERFORMANCE]->(dp)
MERGE (b)-[:HAS_EVENT]->(e:Event {eventId: d.id + '-MANUFACTURED'})
  ON CREATE SET e.type = 'MANUFACTURED', e.ts = d.made + 'T08:00:00Z', e.role = 'manufacturer',
                e.by = o.name, e.details = 'Fabrication – ' + d.place + ' – S/N ' + d.serial;

// ---------------------------------------------------------------------
// 4) ★ EXTENSION Défi 1 : 5 modules par batterie
// ---------------------------------------------------------------------
MATCH (b:BatteryInstance)
UNWIND range(1, 5) AS i
MERGE (mod:Module {moduleId: b.batteryId + '-M' + toString(i)})
  ON CREATE SET mod.position = i, mod.health = 'OK', mod.consecutiveOver = 0
MERGE (b)-[:HAS_MODULE]->(mod);
