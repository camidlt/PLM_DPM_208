# Battery Passport : tronc commun (PoC)

Hackathon ESILV × Capgemini Engineering, « Battery to the Future ».

L'application déroule le parcours obligatoire du sujet : **diagnostic → mise à jour du statut → transfert → réception**. Elle propose trois interfaces, une par rôle :

| Rôle | Appareil visé | Ce qu'il fait |
|---|---|---|
| **Garagiste** | Tablette | Scanne le QR code, consulte le passeport (identification, statut, SOH/SOC, résistance des 5 modules, historique), signale la batterie hors d'usage |
| **Propriétaire Battery Passport** (constructeur) | Desktop | Reçoit la notification, passe le statut **Original → Waste**, choisit un centre de tri **agréé** (ordre de transfert créé) |
| **Centre de tri** | Mobile | Scanne le QR code, vérifie que le statut est bien **Waste**, contrôle scellé et pesée, accuse réception |
| **Transporteur** (défi 2) | Mobile | Reçoit la mission, scanne le QR au garage, pose le scellé, pèse, enregistre l'enlèvement |

---

## 1. Prérequis

- Python 3.10 ou plus
- Optionnel : Neo4j Desktop 5.x (sinon l'appli tourne avec une base en mémoire, sans rien installer)
- Une connexion internet sur les appareils de démo : l'affichage des QR codes et le scanner caméra sont chargés depuis un CDN

```bash
pip install -r requirements.txt
```

## 2. Lancer la démo

### Option A : sans Neo4j (le plus rapide)

```bash
python app.py
```

Ouvrir http://localhost:5000. Les données sont en mémoire : tous les navigateurs connectés voient les mêmes données, qui reviennent à zéro au redémarrage ou via le lien « Réinitialiser la démo » en bas de page.

### Option B : avec Neo4j (ce que demande le sujet)

1. Dans Neo4j Desktop, créer et démarrer une base, puis noter le mot de passe.
2. Charger les données de démo :
   ```bash
   # macOS / Linux
   export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=votre_mdp
   # Windows PowerShell
   $env:NEO4J_URI="bolt://localhost:7687"; $env:NEO4J_USER="neo4j"; $env:NEO4J_PASSWORD="votre_mdp"

   python scripts/seed_neo4j.py
   ```
   Autre possibilité : coller `data/seed.cypher` dans Neo4j Browser.
3. Lancer l'appli dans le même terminal, avec `python app.py`. Le bas de page affiche alors « base : neo4j ».

Pour voir le graphe dans Neo4j Browser :
```cypher
MATCH (b:BatteryInstance {batteryId: "BAT-DOC-001"})-[r]-(n) RETURN b, r, n
```

### Démo sur tablette et téléphone (même Wi-Fi que le PC)

1. Trouver l'IP du PC : `ipconfig` sous Windows, `ifconfig` ou `ip a` sous macOS/Linux. Par exemple 192.168.1.20.
2. Lancer l'appli avec cette adresse, pour que les QR codes pointent vers le PC :
   ```bash
   BP_BASE_URL=http://192.168.1.20:5000 python app.py
   BP_BASE_URL=http://192.168.1.20:5000 python scripts/make_qr.py   # régénère qr/*.png
   ```
3. Imprimer ou afficher `qr/BAT-DOC-001.png`, puis le scanner avec **l'appareil photo** de la tablette ou du téléphone. Le passeport s'ouvre directement après connexion.

Le bouton « Scanner le QR code » intégré à l'appli utilise la caméra du navigateur. Les navigateurs ne l'autorisent que sur `https://` ou `http://localhost`. En Wi-Fi local en `http`, utilisez donc l'appareil photo natif, ou la saisie manuelle de l'identifiant. Pour le scanner intégré, exposez l'appli en https, par exemple avec `ngrok http 5000`.

## 3. Comptes de test

| Rôle | Identifiant | Mot de passe |
|---|---|---|
| Garagiste (Garage Hill Valley) | `garagiste` | `garage123` |
| Propriétaire (Flux Motors) | `proprietaire` | `owner123` |
| Centre de tri Recyclo Nanterre (agréé) | `centretri` | `tri123` |
| Centre de tri Rhône Batteries (agréé) | `centretri2` | `tri123` |
| Transporteur TransBat Logistique (agréé ADR) | `transporteur` | `trans123` |

## 4. Scénario de démo (environ 2 min)

1. **Garagiste**, sur tablette : scanner `BAT-DOC-001`, la batterie de Doc.
   - Le statut affiché est **Original** et le SOH est de 71 %.
   - L'alerte rouge indique que le **module 3** est à 6,8 mΩ, alors que le maximum constructeur est de 2,0 mΩ.
   - Cliquer sur **Signaler hors d'usage**. Le formulaire est prérempli à partir de l'alerte.
2. *(Optionnel, pour montrer le contrôle)* **Centre de tri** : scanner `BAT-DOC-001`. L'écran affiche **⛔ ORIGINAL : statut NON à jour**, et la réception est refusée.
3. **Propriétaire**, sur desktop : la cloche 🔔 affiche 1.
   - Ouvrir la demande et choisir **Centre de tri Recyclo Nanterre**. Le dépôt non agréé n'est pas sélectionnable.
   - Cliquer sur **Valider**. Le statut passe à **Waste** et l'ordre de transfert est créé.
   - Dans **Transferts**, ouvrir l'ordre : choisir **TransBat Logistique** (Rapid Fret, non agréé, est grisé), la date et le créneau, puis **Affecter et notifier**. Montrer l'**étiquette QR** et l'**ordre de transfert** (bouton Imprimer / PDF).
4. **Transporteur**, sur mobile : la mission est dans ✉️ et dans la liste. Scanner `BAT-DOC-001` au garage, saisir le scellé `SC-104522`, le poids `522`, le nom de la personne du garage, cocher les 4 contrôles ADR, **Confirmer l'enlèvement**. La batterie est localisée « chez TransBat ».
5. **Centre de tri**, sur mobile : scanner `BAT-DOC-001`.
   - L'écran affiche **✅ WASTE : le statut est à jour**.
   - Saisir le scellé lu (`SC-104522`) et le poids (`521`), cocher les 2 contrôles, **Confirmer la réception**. Un code de **preuve de dépôt** s'affiche et tous les acteurs sont notifiés.
   - *(Variante)* saisir un autre scellé : réception refusée. Ou **Refuser la batterie** : le propriétaire peut la **rediriger** vers Rhône Batteries, sans nouvel enlèvement.
6. *(Défi 3)* Une fois reçue, l'écran centre de tri recommande **Remanufacturing** (module 3) : enregistrer l'orientation.
7. Montrer l'**historique** de la batterie et le **manifeste** du transfert : chaque étape est horodatée, signée par son acteur et chaînée (SHA-256). Le même historique est visible dans Neo4j.

## 5. Données de démo

| Batterie | Modèle | SOH | Statut | Particularité |
|---|---|---|---|---|
| `BAT-DOC-001` | FluxCap 85 kWh (NMC 811) | 71 % | Original | La batterie de Doc : module 3 hors seuil |
| `BAT-002` | FluxCap 85 kWh (NMC 811) | 93 % | Original | Batterie saine (pour montrer un refus du propriétaire) |
| `BAT-003` | FluxCap 60 kWh (LFP) | 64 % | Original | Usée, 1 accident |
| `BAT-004` | FluxCap 85 kWh (NMC 811) | 48 % | Waste | Déjà au centre de tri |

Toutes les entreprises, adresses et numéros VIN sont fictifs.

## 6. Modèle de graphe

Le graphe reprend la Figure 1 du sujet : `Company`, `Type`, `Model`, `EconomicOperator`, `BatteryInstance`, `Composition`, `Anode`, `Cathode`, `Electrolyte`, `StaticPerformance`, `StaticDurability`, `CarbonFootprint`, `Certification`, `Circularity`, `DynamicPerformance` et `DynamicDurability`. Les relations sont `HAS_MODEL`, `HAS_BATTERY_INSTANCE`, `BUILD`, `HAS_COMPOSITION`, etc.

Il ajoute les extensions suivantes :

```
(:Actor {role: garagiste | proprietaire | centre_tri, agreed})   (:Actor)-[:REPRESENTS]->(:EconomicOperator)
(:BatteryInstance)-[:HAS_MODULE]->(:Module {index, internalResistance_mOhm, maxInternalResistance_mOhm})
(:BatteryInstance)-[:LOCATED_AT]->(:Actor)
(:BatteryInstance)-[:HAS_EVENT]->(:Event {type, at, actorName, details})  <-[:PERFORMED]-(:Actor)
(:Actor)-[:SENT]->(:Notification {state: PENDING|APPROVED|REJECTED, fromStatus, requestedStatus, reason})
      (:Notification)-[:ABOUT]->(:BatteryInstance)   (:Notification)-[:ADDRESSED_TO]->(:EconomicOperator)
(:Notification)-[:TRIGGERED]->(:TransferOrder {state: ORDERED|SCHEDULED|PICKED_UP|RECEIVED|REFUSED|CANCELLED})
      (:TransferOrder)-[:FOR]->(:BatteryInstance)  -[:FROM]->(:Actor)  -[:TO]->(:Actor)
      (:TransferOrder)-[:ASSIGNED_TO]->(:Actor {role: transporteur, agreed, adr, damagedCapable})   (défi 2)
      (:TransferOrder)-[:HAS_STEP]->(:LogisticsStep {seq, type, at, dataJson, prevHash, hash})  <-[:PERFORMED]-(:Actor)
(:Message {subject, body, channel, read})-[:SENT_TO]->(:Actor)                                    (défi 2)
(:BatteryInstance)-[:HAS_TELEMETRY]->(:TelemetryReading {at, source, soh, soc, moduleIndexes, resistances, temperatures})   (défi 1)
(:BatteryInstance)-[:HAS_ORIENTATION]->(:OrientationDecision {choice, recommended, comment, at})  <-[:DECIDED]-(:Actor)   (défi 3)
```

### Règles métier (fichier `bp/workflow.py`)

- Seul le **propriétaire** du passeport, c'est-à-dire l'opérateur économique qui a construit la batterie, peut changer le statut.
- Transitions autorisées : `Original → Waste | Reused | Remanufactured | Repurposed`, et `Waste` est un statut final.
- Il ne peut y avoir qu'une demande en attente par batterie.
- Le transfert ne peut se faire que vers un centre de tri **agréé**.
- Le centre de tri ne peut réceptionner la batterie que si son statut est `Waste` **et** si l'ordre de transfert lui est destiné.
- Défi 2 : la réception exige en plus que la batterie ait été **enlevée par le transporteur affecté** et que le **scellé** corresponde (règles détaillées en section 7).

## 7. Défis intégrés

### Défi 1 : télémétrie BMS

Une passerelle BMS envoie des trames JSON à l'appli. Chaque trame met à jour les nœuds `Module` (résistance interne, `measuredAt`, température) et `DynamicPerformance` (SOH, SOC), et laisse un relevé `TelemetryReading` dans l'historique. Si un module dépasse le seuil constructeur, un événement **Alerte BMS** est ajouté à l'historique, l'alerte rouge apparaît sur l'écran garagiste et le formulaire de signalement est prérempli.

Les écrans batterie (garagiste, propriétaire, centre de tri) affichent une **courbe d'évolution de la résistance par module** (SVG, sans librairie externe). Ils se rechargent seuls dès qu'une nouvelle trame arrive (vérification toutes les 5 s).

**API** (authentification machine par l'en-tête `X-BMS-Key`, défaut `bms-demo-key`, à changer avec `BP_BMS_KEY`) :

| Méthode | URL | Rôle |
|---|---|---|
| `POST` | `/api/telemetry` | Une trame (objet) ou un lot (liste). Réponse 201, 207 si lot partiellement valide, 400, 401 |
| `GET` | `/api/telemetry/<id>/latest` | État mesuré actuel, pour la passerelle |
| `GET` | `/api/battery/<id>/telemetry?limit=50` | Historique des relevés (session utilisateur) |

```json
{"batteryId": "BAT-002", "measuredAt": "2026-11-04T10:15:00", "soh": 92.5, "soc": 74,
 "modules": [{"index": 2, "internalResistance_mOhm": 2.71, "temperature_C": 31.0}]}
```

`measuredAt`, `soh`, `soc`, `source` et `temperature_C` sont optionnels ; on peut n'envoyer que certains modules. Une trame plus ancienne que la dernière mesure est archivée sans écraser l'état actuel.

**Simulateur** (bibliothèque standard uniquement), l'appli étant lancée :

```bash
python scripts/bms_simulator.py --battery BAT-002 --module 2      # le module 2 dérive jusqu'à l'alerte
python scripts/bms_simulator.py --battery BAT-002 --scenario healthy --steps 5
python scripts/bms_simulator.py --file trames.json                # rejouer de vraies trames
```

**Démo** : ouvrir l'écran garagiste de `BAT-002` (batterie saine), lancer le simulateur. Au bout de 3 trames, le module 2 passe en rouge, l'alerte apparaît et le signalement est prérempli.

### Défi 3 : aide à la décision de fin de vie

Sur l'écran **centre de tri** (et en lecture seule chez le propriétaire), une carte recommande **Réemploi, Remanufacturing, Seconde vie ou Recyclage**.

La logique (`bp/decision.py`) est volontairement explicable :

1. Chaque option a des critères mesurables tirés du passeport : SOH, modules hors seuil, accidents, cycles consommés / cycles prévus, défauts de sécurité signalés (gonflement, surchauffe), dérive de résistance mesurée par le BMS (lien avec le défi 1).
2. On suit la **hiérarchie européenne des déchets** : la première option éligible dans l'ordre Réemploi → Remanufacturing → Seconde vie → Recyclage est recommandée. Le recyclage est toujours possible.
3. Chaque critère s'affiche avec sa valeur, son seuil et ✓/✗. Les seuils sont regroupés dans `THRESHOLDS`.

| Option | Critères (tous requis) |
|---|---|
| Réemploi | SOH ≥ 80 %, aucun module hors seuil, 0 accident, cycles ≤ 80 %, dérive BMS ≤ +50 %, aucun défaut de sécurité |
| Remanufacturing | SOH ≥ 70 %, 1 à 40 % des modules à remplacer, ≤ 1 accident, cycles ≤ 90 %, aucun défaut de sécurité |
| Seconde vie | SOH ≥ 60 %, aucun module hors seuil, ≤ 1 accident, aucun défaut de sécurité |
| Recyclage | toujours possible |

Les 4 batteries de démo donnent chacune une réponse différente : `BAT-002` → Réemploi, `BAT-DOC-001` → Remanufacturing (module 3), `BAT-003` → Seconde vie (LFP), `BAT-004` → Recyclage (SOH 48 %, 2 accidents).

La carte liste aussi les **matériaux récupérables** (matières critiques en évidence) et les taux de valorisation du règlement (UE) 2023/1542.

**Orientation retenue** : une fois la batterie réceptionnée, le centre de tri enregistre l'option choisie (`(:OrientationDecision)` + événement dans l'historique). Une option exclue ne peut pas être choisie ; s'écarter de la recommandation exige une justification. Une seule orientation par batterie. Le statut reste `Waste` (statut final dans `workflow.py`) : la création d'un nouveau passeport pour une batterie remanufacturée ou en seconde vie, prévue par le règlement, n'est pas traitée.

API : `GET /api/battery/<id>/decision` (recommandation complète + orientation).

### Défi 2 : logistique et conformité du transfert (intégré)

Objectif : outiller le responsable du Battery Passport pour **planifier, exécuter et tracer** le transfert, de façon sécurisée, traçable et réaliste. Livrables dans `docs/defi2/` :

| Livrable demandé | Où |
|---|---|
| Processus par métier (couloirs façon BPMN) | `docs/defi2/processus_transfert.png` (source `.mmd`) |
| Modèle graphe des événements logistiques | `docs/defi2/modele_graphe.png` |
| Règles de changement d'état | `docs/defi2/etats_ordre.png` + tableau ci-dessous |
| Écrans propriétaire (création d'ordre, suivi, preuves) et recycleur (accusé de réception) | dans l'appli ; captures dans `docs/defi2/captures/` |
| Modèle de données des documents + exemples PDF/JSON | `bp/logistics.py` (`transfer_document`) ; `docs/defi2/exemples/` |

**Workflow** : demande (garagiste) → validation et ordre (propriétaire) → affectation du transporteur (propriétaire) → enlèvement (transporteur) → réception ou refus (centre de tri). Il s'appuie sur quatre principes.

- **Agréé ou non.** Le propriétaire ne peut choisir qu'un centre de tri **et** un transporteur agréés, dont l'agrément est **valide à la date d'enlèvement**. Pour un transporteur, agréé veut dire habilité ADR classe 9 et titulaire d'un récépissé de transport de déchets. Une batterie **endommagée** (défaut « dommage physique » ou « surchauffe ») exige un centre et un transporteur équipés. Les choix impossibles sont grisés à l'écran, avec la raison.
- **Conformité ADR** calculée à partir du défaut signalé :

  | Cas | Disposition | Emballage | Marquage |
  |---|---|---|---|
  | Non endommagée | DS 377 | P909 | BATTERIES LITHIUM-ION À RECYCLER |
  | Endommagée | DS 376 | P908 / LP904 | BATTERIE LITHIUM-ION ENDOMMAGÉE/DÉFECTUEUSE |
  | Surchauffe (critique) | DS 376 | P911 / LP906 | idem |

  Désignation : `UN 3480 DÉCHET BATTERIES LITHIUM-ION, 9, (E)`. Au-delà de 333 kg, un conducteur formé ADR et des consignes écrites sont obligatoires.
- **Chaîne de garde.** Le transporteur pose un **scellé** et pèse la batterie au garage, avec 4 contrôles ADR et le nom de la personne qui remet la batterie. Le centre de tri doit relire **le même scellé** : sinon, il refuse. Un écart de pesée de plus de 5 % est tracé comme anomalie. La batterie est localisée à chaque étape : garage, puis transporteur, puis centre de tri.
- **Preuves infalsifiables.** Chaque étape est un nœud `LogisticsStep` signé par l'acteur connecté. Son empreinte SHA-256 inclut l'empreinte de l'étape précédente : toute modification a posteriori est détectée, et l'écran comme le manifeste l'affichent. Le code de **preuve de dépôt** est le début de l'empreinte de l'étape de réception.

**Parcours opérationnel clair (Défi 2)**

1. **Le garagiste garde la batterie et signale le hors d'usage.**
2. **Le propriétaire du passeport valide et passe en Waste.**
3. **Le recyclage n'est pas fait par le garagiste : il est fait par le centre de tri après transfert.**
4. **Le garagiste remet la batterie au transporteur lors de l'enlèvement.**

Résumé : le garagiste déclenche et remet, le propriétaire autorise, le transporteur transfère, le centre de tri recycle.

**Logistique inspirée retail (type Zara / H&M)**

Pour rendre le transfert réaliste et industriel, le PoC suit une logique de collecte proche de la logistique retail :

- **Collectes planifiées** : enlèvements sur créneaux fixes (ex. matin/après-midi), comme des tournées magasin.
- **Routage standardisé** : flux garage -> transporteur -> centre agréé, avec destination décidée à la validation.
- **Scan à chaque rupture de charge** : enlèvement puis réception, pour tracer qui a la batterie et quand.
- **Preuve de remise** : scellé + pesée + signature de remise au garage, puis preuve de dépôt au centre.
- **Pilotage par exceptions** : si anomalie (scellé, état colis, écart), le centre refuse et le propriétaire redirige.

**Règles de changement d'état de l'ordre** (`bp/logistics.py`) :

| Transition | Qui | Conditions |
|---|---|---|
| → `ORDERED` | propriétaire | valide Original → Waste (tronc commun) ; centre agréé, agrément valide, accepte les batteries endommagées si besoin |
| `ORDERED`/`SCHEDULED` → `SCHEDULED` | propriétaire | transporteur agréé ADR, agrément valide à la date, équipé si batterie endommagée ; date ≥ aujourd'hui |
| `SCHEDULED` → `PICKED_UP` | transporteur **affecté** | batterie chez le détenteur ; scellé, pesée, remettant, 4 contrôles |
| `PICKED_UP` → `RECEIVED` | centre **destinataire** | statut passeport `Waste` ; même scellé ; pesée ; 2 contrôles |
| `PICKED_UP` → `REFUSED` | centre destinataire | motif obligatoire ; la batterie reste chez le transporteur |
| `ORDERED`/`SCHEDULED` → `CANCELLED` | propriétaire | motif obligatoire ; impossible après enlèvement |
| après `REFUSED` | propriétaire | **redirection** : nouvel ordre directement `PICKED_UP` vers un autre centre, même scellé |
| après `CANCELLED` | propriétaire | nouvel ordre `ORDERED` |

Le statut du passeport ne change qu'une fois, à la validation du propriétaire (Original → Waste). La logistique ne le modifie pas, mais la réception exige qu'il soit `Waste`.

**Documents** générés depuis le graphe, à imprimer ou enregistrer en PDF depuis le navigateur. Le QR code est généré côté serveur, il marche donc sans internet.

| URL | Document |
|---|---|
| `/transfers/<ordre>/ordre` | Ordre de transfert (parties, ADR, enlèvement, cases de remise) |
| `/transfers/<ordre>/etiquette` | Étiquette colis : UN 3480, losange classe 9, marquage, QR du passeport, scellé |
| `/transfers/<ordre>/manifeste` | Manifeste (inspiré du bordereau de suivi de déchets) : étapes, empreintes, preuve de dépôt |
| `/api/transfers/<ordre>` | Le même manifeste en JSON (`schema: battery-passport/transfer-manifest/1`), `?download=1` |

Accès : le propriétaire, ainsi que le garage, le transporteur et le centre concernés par l'ordre. Les autres reçoivent une 404.

**Notifications** : à chaque étape, les acteurs concernés reçoivent un message in-app (✉️ dans la barre du haut) et un mail. Les mails sont simulés tant que `BP_SMTP_HOST` n'est pas défini ; sinon ils partent par SMTP (`BP_SMTP_PORT`, `BP_SMTP_USER`, `BP_SMTP_PASSWORD`, `BP_SMTP_FROM`). Un échec d'envoi ne bloque jamais le transfert.

**À savoir / limites du PoC**
- Le code déchet (`BP_WASTE_CODE`, défaut `16 06 05`) est à confirmer avec le centre de tri.
- En France, le suivi des déchets dangereux passe par la plateforme Trackdéchets. Le manifeste JSON pourrait y être transmis : ce n'est pas fait ici.
- Les signatures sont des signatures de session (acteur connecté), pas des signatures électroniques qualifiées.
- En mode Neo4j, chaque étape fait plusieurs écritures successives, sans transaction unique.

## 8. Si le dump officiel a d'autres noms

Toutes les requêtes Cypher se trouvent dans `bp/neo4j_repo.py`. Si le dump fourni par les organisateurs utilise d'autres noms de propriétés ou de relations, c'est le seul fichier à adapter. `scripts/seed_neo4j.py` ne modifie que les nœuds de démo et laisse le reste de la base intact.

## 9. Structure

```
app.py                  routes Flask (3 rôles, scan QR, API JSON)
bp/workflow.py          règles métier du parcours
bp/telemetry.py         défi 1 : validation et ingestion des trames BMS, courbe
bp/decision.py          défi 3 : recommandation de fin de vie, orientation
bp/logistics.py         défi 2 : cycle de l'ordre, agréments, ADR, preuves chaînées, manifeste
bp/notify.py            défi 2 : notifications in-app et mail
bp/neo4j_repo.py        accès Neo4j (Cypher)
bp/memory_repo.py       même chose en mémoire (démo sans Neo4j)
bp/seed_data.py         jeu de données de démo, source unique
bp/config.py            configuration et comptes de test
templates/, static/     interfaces (templates/_defis.html : cartes des défis 1 et 3)
scripts/                seed Neo4j, export Cypher, QR codes, simulateur BMS
data/seed.cypher        script Cypher généré
qr/                     QR codes des batteries de démo
tests/                  parcours complet + défis 1, 2 et 3 (python -m pytest -q)
docs/defi2/             diagrammes, exemples PDF/JSON, captures du défi 2
```
