# Battery Passport

Preuve de concept du hackathon ESILV x Capgemini Engineering, « Battery to the Future ».

Un passeport numérique de batterie de véhicule électrique, conforme dans l'esprit au règlement européen 2023/1542 : il suit une batterie du diagnostic au garage jusqu'à sa fin de vie au centre de tri, avec un accès différent pour chaque acteur. Un vrai microcontrôleur ESP32 joue le rôle du BMS (Battery Management System) et alimente le passeport en direct.

Ce dépôt réunit en un seul site le travail de toutes les branches de l'équipe :

| Branche d'origine | Apport | Où le trouver maintenant |
|---|---|---|
| `main` | Tronc commun : 3 rôles, workflow, graphe, tests | `app.py`, `bp/workflow.py`, `templates/` |
| `common-ground` | Jeu de données Neo4j Desktop | `data/archive/` |
| `defi-1` | Firmware ESP32 (Bluetooth, HTTP, MQTT), application FastAPI de télémétrie, Wokwi, émulateur | `esp32/`, `bp/telemetry.py` |
| `defi_3` | Aide à la décision du centre de tri, demandes du marché | `bp/decision.py`, `templates/_decision_panel.html` |
| `main` (dernier ajout) | Ajout et suppression de demandes du marché | `/tri/market`, onglet Marché du panneau de décision |

---

## Sommaire

1. [Ce que fait le site](#1-ce-que-fait-le-site)
2. [Démarrage rapide](#2-démarrage-rapide)
3. [Lancer avec Neo4j](#3-lancer-avec-neo4j)
4. [Démo sur tablette et téléphone](#4-démo-sur-tablette-et-téléphone)
5. [L'ESP32 : fonctionnement et installation](#5-lesp32--fonctionnement-et-installation)
6. [Sans ESP32 : émulateur et Wokwi](#6-sans-esp32--émulateur-et-wokwi)
7. [Comptes de test](#7-comptes-de-test)
8. [Scénario de démo](#8-scénario-de-démo-environ-2-minutes)
9. [Règles métier](#9-règles-métier)
10. [Défi 3 : l'algorithme de décision](#10-défi-3--lalgorithme-de-décision)
11. [Données de démo](#11-données-de-démo)
12. [Modèle de graphe](#12-modèle-de-graphe)
13. [API](#13-api)
14. [Configuration](#14-configuration)
15. [Tests](#15-tests)
16. [Structure du dépôt](#16-structure-du-dépôt)
17. [Design](#17-design)
18. [Dépannage](#18-dépannage)
19. [Limites de la preuve de concept](#19-limites-de-la-preuve-de-concept)
20. [Crédits](#20-crédits)

---

## 1. Ce que fait le site

| Page | Appareil visé | Qui | Ce qu'on y fait |
|---|---|---|---|
| `/` | Projecteur, ordinateur | Jury, visiteurs | Présentation du projet, les 5 modules de BAT-DOC-001 en direct, le parcours, le fonctionnement de l'ESP32, les recommandations réelles du défi 3, l'accès aux comptes de test |
| `/garage` | Tablette | Garagiste | Scanner le QR code, lire le passeport et la télémétrie en direct, signaler la batterie hors d'usage |
| `/owner` | Ordinateur | Propriétaire du passeport | Recevoir les demandes, passer le statut de Original à Waste, choisir un centre de tri agréé |
| `/tri` | Téléphone | Centre de tri | Vérifier le statut, accuser réception, obtenir et valider une recommandation de fin de vie |
| `/tri/market` | Téléphone | Centre de tri | Gérer les demandes du marché : activer, désactiver, ajouter, supprimer |
| `/transport` | Téléphone | Transporteur | Missions, enlèvement au garage : scellé, pesée, 4 contrôles ADR |
| `/transfers/<ordre>` | Tous | Acteurs du transfert | Suivi en 4 étapes, planification, preuves, étapes signées, documents |
| `/transfers/<ordre>/doc/etiquette` | Imprimante | Tous | Étiquette colis UN 3480 classe 9 ; aussi `ordre` et `manifeste` |
| `/messages` | Tous | Tous les rôles | Notifications de chaque étape (in-app et mail simulé) |
| `/public/b/<id>` | Tout téléphone | Grand public | Passeport public restreint (Annexe XIII), sans connexion |

Le parcours obligatoire du sujet est **diagnostic, mise à jour du statut, transfert, réception**. Les défis 1 (télémétrie), 2 (logistique du transfert) et 3 (aide à la décision) s'y greffent.

**Défi 2, logistique.** Le garagiste choisit le centre de tri agréé et peut demander la collecte automatique (date, créneau). À la validation du propriétaire, l'ordre passe par `ORDERED`, `SCHEDULED` (transporteur agréé ADR affecté), `PICKED_UP` (scellé, pesée, remise signée, 4 contrôles ADR) puis `RECEIVED` (le centre relit le scellé et pèse : un scellé différent est bloqué, un écart de pesée de plus de 5 % est signalé, un code de preuve de dépôt est émis). Le centre peut aussi refuser la réception : le propriétaire redirige alors la batterie vers un autre centre sans nouvel enlèvement. Chaque étape est un nœud `LogisticsStep` chaîné par empreinte SHA-256 et notifie les acteurs concernés. Règles dans `bp/logistics.py`.

---

## 2. Démarrage rapide

Prérequis : Python 3.10 ou plus récent.

```bash
git clone git@github.com:camidlt/PLM_DPM_208.git
cd PLM_DPM_208
git switch master-site
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Ouvrir http://localhost:8000.

Sans configuration, le site utilise une **base en mémoire** : rien à installer, toutes les fenêtres de navigateur voient les mêmes données, et tout revient à zéro au redémarrage ou avec le lien « Réinitialiser la démo » en pied de page (visible une fois connecté).

Pour voir la télémétrie bouger sans ESP32, lancer l'émulateur dans un second terminal :

```bash
python esp32/emulator/bms_emulator.py --url http://127.0.0.1:8000/api/telemetry
```

---

## 3. Lancer avec Neo4j

Le sujet demande une base graphe. Le site bascule sur Neo4j dès que `NEO4J_URI` est défini.

**Avec Docker** (fichier `docker-compose.yml` fourni, mot de passe `hackathon2026`) :

```bash
docker compose up -d
export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=hackathon2026
python scripts/seed_neo4j.py
uvicorn app:app --host 0.0.0.0 --port 8000
```

**Avec Neo4j Desktop 5.x** : créer une base, la démarrer, puis les mêmes commandes avec votre mot de passe. Sous Windows PowerShell :

```powershell
$env:NEO4J_URI="bolt://localhost:7687"; $env:NEO4J_USER="neo4j"; $env:NEO4J_PASSWORD="votre_mdp"
python scripts/seed_neo4j.py
uvicorn app:app --host 0.0.0.0 --port 8000
```

Le pied de page affiche alors « Base : Neo4j ». `scripts/seed_neo4j.py` ne touche qu'aux nœuds de démo : un dump officiel importé à côté reste intact. On peut aussi coller `data/seed.cypher` dans Neo4j Browser.

Pour explorer le graphe de la batterie de Doc dans Neo4j Browser (http://localhost:7474) :

```cypher
MATCH (b:BatteryInstance {batteryId: "BAT-DOC-001"})-[r]-(n) RETURN b, r, n
```

---

## 4. Démo sur tablette et téléphone

Tous les appareils doivent être sur le **même Wi-Fi** que le PC.

1. Trouver l'IP du PC : `ipconfig` (Windows) ou `ip a` / `ifconfig` (macOS, Linux). Exemple : `192.168.1.20`.
2. Lancer le site avec cette adresse, pour que les QR codes pointent vers le PC :
   ```bash
   BP_BASE_URL=http://192.168.1.20:8000 uvicorn app:app --host 0.0.0.0 --port 8000
   ```
3. Afficher ou imprimer le QR code de la batterie : http://192.168.1.20:8000/qr/BAT-DOC-001.png (ou `python scripts/make_qr.py` pour régénérer les PNG de `qr/`).
4. Le scanner avec l'appareil photo de la tablette ou du téléphone. Sans connexion, la vue publique s'ouvre ; une fois connecté, chaque rôle arrive sur sa propre vue.

Le bouton « Scanner le QR code » du site utilise la caméra du navigateur, que les navigateurs n'autorisent qu'en `https://` ou sur `localhost`. En Wi-Fi local en `http`, utiliser l'appareil photo natif ou la saisie de l'identifiant. Pour le scanner intégré, exposer le site en https (par exemple `ngrok http 8000`).

---

## 5. L'ESP32 : fonctionnement et installation

### Principe

```
 ESP32 : 5 entrées analogiques            PC : site Battery Passport
 GPIO 34, 35, 32, 33, 39                  FastAPI + graphe (mémoire ou Neo4j)
 une broche par module
        |                                          ^
        |  toutes les 3 s, JSON                    |
        +--- mode 2 : Wi-Fi, HTTP POST ------------+  /api/telemetry
        +--- mode 3 : Wi-Fi, MQTT --> broker ------+  abonnement <préfixe>/battery/+/telemetry
        +--- mode 1 : Bluetooth série (débogage, tablette appairée)
                                                   |
                                     Module, Measurement, Alert dans le graphe
                                                   |
                         écrans garagiste, propriétaire et accueil, rafraîchis toutes les 2 s
```

1. **Mesure.** Le firmware lit 5 broches analogiques, une par module, et convertit la lecture en résistance interne : de 1,0 à 1,5 mΩ pour un module sain du modèle FC-85.
2. **Défaut à la demande.** Un appui sur le bouton **BOOT** de la carte lance la dérive du module 3 : sa résistance monte de 0,9 mΩ par mesure jusqu'à 6,8 mΩ. Un second appui le remet à l'état sain. C'est le bouton à presser devant le jury.
3. **Envoi.** Toutes les 3 secondes, la carte envoie ce JSON (la LED intégrée clignote à chaque envoi) :
   ```json
   {"batteryId": "BAT-DOC-001", "source": "ESP32",
    "modules": [{"id": 1, "r_mohm": 1.23, "t": 24.6},
                {"id": 2, "r_mohm": 1.31, "t": 24.6},
                {"id": 3, "r_mohm": 6.80, "t": 24.6},
                {"id": 4, "r_mohm": 1.18, "t": 24.6},
                {"id": 5, "r_mohm": 1.42, "t": 24.6}]}
   ```
4. **Décision côté serveur.** Le firmware n'applique aucune règle métier : il mesure et envoie. Le site calcule la santé de chaque module (voir [Règles métier](#9-règles-métier)), crée l'alerte et l'événement dans le graphe.
5. **Affichage.** La baie de cellules (garagiste, propriétaire, accueil) se met à jour toutes les 2 secondes. La bande d'état indique « BMS ESP32 en ligne » si la carte a parlé il y a moins de 10 secondes, avec le nombre de paquets reçus. Le formulaire de signalement du garagiste se préremplit à partir de l'alerte.

### Choisir le mode de communication

Défini par `COMM_MODE` en haut de `esp32/firmware/src/main.cpp` (valeur par défaut : 2), ou dans `platformio.ini` avec `build_flags = -DCOMM_MODE=3`.

| Mode | Lien | Quand l'utiliser | Côté site |
|---|---|---|---|
| 1 | Bluetooth classique (« BMS-DeLorean-ESP32 ») | Débogage, tablette appairée | Rien n'arrive au site sans relais |
| **2** | **Wi-Fi, HTTP POST** | **Démo standard, recommandé** | Rien à configurer |
| 3 | Wi-Fi, MQTT | Carte et PC sur des réseaux différents | Lancer avec `MQTT_HOST` et `TOPIC_PREFIX` |

### Installation pas à pas

1. Installer [PlatformIO](https://platformio.org/) : l'extension VS Code, ou `pip install platformio`.
2. Copier `esp32/firmware/include/secrets.example.h` en `esp32/firmware/include/secrets.h` (ce fichier n'est pas versionné) et remplir :
   - `WIFI_SSID`, `WIFI_PASS` : le même Wi-Fi que le PC. L'ESP32 ne parle que le **2,4 GHz**.
   - `SERVER_URL` : `http://<IP du PC>:8000/api/telemetry`.
   - `DEVICE_TOKEN` : vide, ou la même valeur que `BP_DEVICE_TOKEN` côté serveur.
   - Mode 3 seulement : `MQTT_HOST`, `MQTT_PORT`, `TOPIC_PREFIX`.
3. Brancher la carte en USB, puis :
   ```bash
   cd esp32/firmware
   pio run -t upload
   pio device monitor
   ```
4. Le moniteur série affiche `Wi-Fi ... OK, IP ...` puis `POST ... -> 200` toutes les 3 secondes. Sur la page d'accueil, « BMS ESP32 en ligne » passe au bleu.

Le site doit écouter sur toutes les interfaces (`--host 0.0.0.0`) et le pare-feu du PC doit laisser entrer le port 8000.

Les trois modes compilent pour la carte `esp32dev` (environ 31 à 36 % de la flash avec la partition `huge_app`).

### Câblage (facultatif)

Sans rien brancher, les entrées analogiques « flottent » et donnent des valeurs saines aléatoires : c'est suffisant pour la démo. Pour piloter un module à la main, brancher un potentiomètre de 10 kΩ : extrémités sur 3V3 et GND, curseur sur la broche du module (par exemple GPIO 32 pour le module 3). Les broches 34 et 35 sont des entrées seules, ce qui convient ici.

---

## 6. Sans ESP32 : émulateur et Wokwi

### Émulateur Python

```bash
python esp32/emulator/bms_emulator.py                              # HTTP vers localhost:8000
python esp32/emulator/bms_emulator.py --normal 5 --step 0.6        # 5 mesures saines, puis dérive du module 3
python esp32/emulator/bms_emulator.py --mode mqtt --topic-prefix esilv-hack-2026/equipe-XX
```

Il envoie le même JSON que la carte, avec en plus tension, courant et température. Si `r_mohm` est absent, le serveur calcule R = (V_ocv - V) / I.

### Wokwi (simulateur en ligne)

`esp32/wokwi/` contient le croquis et le schéma (`sketch.ino`, `diagram.json`, `libraries.txt`), avec un potentiomètre sur le module 3 et une LED rouge. Wokwi n'atteint pas le PC local : il publie en MQTT sur `broker.hivemq.com`. Lancer le site avec :

```bash
MQTT_HOST=broker.hivemq.com TOPIC_PREFIX=esilv-hack-2026/<votre-équipe> uvicorn app:app --host 0.0.0.0 --port 8000
```

et mettre le même préfixe dans `sketch.ino`.

---

## 7. Comptes de test

| Rôle | Identifiant | Mot de passe | Appareil |
|---|---|---|---|
| Garagiste (Garage Hill Valley) | `garagiste` | `garage123` | Tablette |
| Propriétaire (Flux Motors) | `proprietaire` | `owner123` | Ordinateur |
| Centre de tri Recyclo Nanterre (agréé) | `centretri` | `tri123` | Téléphone |
| Centre de tri Rhône Batteries (agréé, sans batteries endommagées) | `centretri2` | `tri123` | Téléphone |
| Transporteur TransBat Logistique (agréé ADR) | `transporteur` | `trans123` | Téléphone |

Sur la page d'accueil, les boutons « Entrer comme ... » et « Utiliser » préremplissent le formulaire de connexion. Mots de passe en clair : preuve de concept uniquement.

---

## 8. Scénario de démo (environ 3 minutes)

1. **Accueil au projecteur**, ESP32 allumé : la bande d'état indique « BMS ESP32 en ligne ». Appuyer sur **BOOT** : le module 3 de BAT-DOC-001 passe en surveillance, puis en critique au troisième dépassement. La courbe de tendance montre la dérive au-dessus du seuil en pointillés.
2. **Garagiste** (tablette) : ouvrir `BAT-DOC-001`. Le panneau de diagnostic se met à jour seul : alerte module 3 en rouge, formulaire prérempli. Choisir Recyclo Nanterre, laisser « Planifier automatiquement la collecte » activé, cliquer sur « Signaler hors d'usage ».
3. **Propriétaire** (ordinateur) : la cloche affiche 1. Valider : le statut passe à Waste, l'ordre est créé et TransBat Logistique est affecté automatiquement.
4. **Transporteur** (téléphone) : la mission apparaît. Saisir le scellé (`SC-104522`), le poids, le nom de la personne du garage, cocher les 4 contrôles ADR. Montrer l'étiquette UN 3480.
5. **Centre de tri** (téléphone) : ouvrir `BAT-DOC-001`. Saisir d'abord un mauvais scellé : la réception est bloquée. Puis le bon scellé et le poids : preuve de dépôt émise. Valider la recommandation (Remanufacture : remplacer le module 3).
6. **Historique et notifications** : chaque étape est horodatée avec son acteur ; chaque acteur a reçu ses notifications. Le manifeste imprimable reprend les étapes signées.

Entre deux répétitions : appuyer sur BOOT pour remettre le module 3 à l'état sain, puis « Réinitialiser la démo » en pied de page.

## 9. Règles métier

**Workflow** (`bp/workflow.py`, identiques en mémoire et en Neo4j) :

- Seul le **propriétaire** du passeport, c'est-à-dire l'opérateur économique qui a construit la batterie, peut changer le statut.
- Transitions autorisées : `Original` vers `Waste`, `Reused`, `Remanufactured` ou `Repurposed` ; `Waste` est un statut final.
- Une seule demande en attente par batterie. Un refus exige un motif.
- Le transfert ne peut viser qu'un centre de tri **agréé**.
- Le centre de tri ne réceptionne que si le statut est `Waste` **et** que l'ordre de transfert lui est destiné.
- La décision de fin de vie n'est possible qu'une fois la batterie réceptionnée par ce centre. Choisir une autre option que la recommandation exige un commentaire.

**Télémétrie** (`bp/telemetry.py`) :

| Santé | Condition | Effet |
|---|---|---|
| Nominal | Résistance sous 80 % du maximum constructeur | Cellule neutre |
| Surveillance | Au moins 80 % du maximum, ou au-dessus mais pas encore 3 fois de suite | Cellule ambre |
| Critique | Au-dessus du maximum sur 3 mesures consécutives | Cellule rouge, `Alert` et événement « Alerte BMS » créés une seule fois |

Le maximum est porté par chaque module dans les données (2,0 mΩ pour le FC-85, 2,5 mΩ pour le FC-60 LFP). Le serveur accepte aussi les anciens noms de champs du premier firmware (`battery_id`, `resistance_mohm`).

**Accès** : la vue publique ne montre que les attributs publics (identification, fabricant, chimie, empreinte carbone). L'état de santé, l'historique et le statut sont réservés aux rôles connectés.

---

## 10. Défi 3 : l'algorithme de décision

`bp/decision.py` recommande **Reuse, Remanufacture, Repurpose ou Recycle** pour une batterie au statut Waste, à partir des attributs du Battery Pass (liste v1.2, numéros `#n` affichés à côté de chaque valeur).

1. **Faisabilité** : règles éliminatoires.
   - Sécurité : au moins 2 accidents, 5 décharges profondes ou 3 surcharges imposent le recyclage.
   - Reuse : SOCE au-dessus du seuil d'épuisement et aucun module hors tolérance.
   - Remanufacture : 1 ou 2 modules à remplacer, SOCE proche du seuil, manuel de démontage et pièces disponibles.
   - Repurpose : SOCE d'au moins 60 %, pack pas trop hétérogène.
2. **Score** des options faisables :
   ```
   score = 100 x somme(poids_c x adéquation_c) / somme(poids)      score technique
         + bonus de hiérarchie (Reuse 5, Remanufacture 3, Repurpose 2, Recycle 0)
         + bonus marché (demandes actives compatibles : urgente 20, normale 10, faible 5)
   ```
   Critères et poids : santé 35, homogénéité des modules 25, usure 15, stress subi 15, chimie 10.
3. **Explication** : l'écran donne l'action à mener, trois raisons clés, l'écart avec l'option suivante, la matrice critère par critère, l'effet du marché et les options exclues avec leur raison.

Le centre de tri peut, depuis l'écran :

- activer, désactiver, **ajouter** ou **supprimer** des demandes du marché (onglet Marché ou `/tri/market`) ;
- changer ses priorités : tenir compte du marché, privilégier le réemploi avant le recyclage.

Chaque décision est enregistrée dans le graphe avec les scores, les poids, la politique du centre et la demande servie. Tous les seuils sont des hypothèses paramétrables, pas des valeurs réglementaires.

---

## 11. Données de démo

| Batterie | Modèle | SOH | Statut | Particularité | Recommandation attendue |
|---|---|---|---|---|---|
| `BAT-DOC-001` | FluxCap 85 kWh, NMC 811 | 71 % | Original | La batterie de Doc, reliée à l'ESP32 : module 3 hors seuil | Remanufacture |
| `BAT-002` | FluxCap 85 kWh | 93 % | Original | Saine, pour montrer un refus du propriétaire | |
| `BAT-003` | FluxCap 60 kWh, LFP | 64 % | Original | Usée, 1 accident | |
| `BAT-004` | FluxCap 85 kWh | 48 % | Waste | Déjà au centre de tri | Recycle (sécurité) |
| `BAT-101` | FluxCap 85 kWh | 86 % | Waste | Modules sains | Reuse |
| `BAT-102` | FluxCap 60 kWh, LFP | 66 % | Waste | Modules homogènes | Repurpose |
| `BAT-103` | FluxCap 85 kWh | 55 % | Waste | 7 décharges profondes | Recycle (sécurité) |

Source unique : `bp/seed_data.py`, exportée dans `data/seed.cypher` par `python scripts/export_cypher.py`. Toutes les entreprises, personnes, adresses et VIN sont fictifs.

`data/archive/` garde les jeux Neo4j Desktop de la première version FastAPI (autre schéma, seuil 25 mΩ). Ils se chargent dans Neo4j Desktop pour explorer, mais le site ne les utilise pas.

---

## 12. Modèle de graphe

Socle : Figure 1 du sujet. `Company`, `Type`, `Model`, `EconomicOperator`, `BatteryInstance`, `Composition`, `Anode`, `Cathode`, `Electrolyte`, `StaticPerformance`, `StaticDurability`, `CarbonFootprint`, `Certification`, `Circularity`, `DynamicPerformance`, `DynamicDurability`, reliés par `HAS_MODEL`, `HAS_BATTERY_INSTANCE`, `BUILD`, `HAS_COMPOSITION`, etc.

Extensions :

```
(:Actor {role: garagiste | proprietaire | centre_tri, agreed})-[:REPRESENTS]->(:EconomicOperator)
(:BatteryInstance)-[:LOCATED_AT]->(:Actor)
(:BatteryInstance)-[:HAS_EVENT]->(:Event {type, at, actorName, details})<-[:PERFORMED]-(:Actor)

Défi 1
(:BatteryInstance)-[:HAS_MODULE]->(:Module {index, internalResistance_mOhm, maxInternalResistance_mOhm,
                                            health, consecutiveOver, lastTemperature, measuredAt})
(:Module)-[:HAS_MEASUREMENT]->(:Measurement {ts, internalResistance_mOhm, voltage, current, temperature})
(:Module)-[:RAISED]->(:Alert {level, at, value, threshold, message, open})

Tronc commun
(:Actor)-[:SENT]->(:Notification {state: PENDING | APPROVED | REJECTED, fromStatus, requestedStatus, reason})
(:Notification)-[:ABOUT]->(:BatteryInstance)
(:Notification)-[:ADDRESSED_TO]->(:EconomicOperator)
(:Notification)-[:TRIGGERED]->(:TransferOrder {state: ORDERED | RECEIVED})
(:TransferOrder)-[:FOR]->(:BatteryInstance)
(:TransferOrder)-[:FROM]->(:Actor)
(:TransferOrder)-[:TO]->(:Actor)

Défi 3
(:BatteryInstance)-[:HAS_DECISION]->(:Decision {recommendation, chosen, overridden, scores, weights, at})
(:Actor)-[:MADE]->(:Decision)-[:FULFILLS]->(:MarketDemand {title, option, chemistries, minSoce, urgency, active})
(:MarketDemand)-[:OFFERED_TO]->(:Actor)
```

Toutes les requêtes Cypher sont dans `bp/neo4j_repo.py` : c'est le seul fichier à adapter si le dump officiel utilise d'autres noms.

---

## 13. API

Documentation interactive générée par FastAPI : http://localhost:8000/api/docs.

| Méthode | Chemin | Accès | Rôle |
|---|---|---|---|
| POST | `/api/telemetry` | Appareil (clé machine) | Reçoit une trame BMS (objet) ou un lot de trames (liste, 200 au plus). Chaque trame met à jour les modules et, si présents, SOH et SOC, et crée un nœud `TelemetryReading`. 200 si tout est accepté, 207 si une partie du lot est rejetée, 400 si rien n'est valide, 401 sans clé valide |
| GET | `/api/transfers/<ordre>` | Acteurs du transfert | Manifeste JSON : parties, marchandise dangereuse, preuves, étapes signées, intégrité |
| GET | `/api/live` | Public | Télémétrie de la batterie de démonstration (page d'accueil) |
| GET | `/api/battery/<id>/live` | Connecté | Télémétrie d'une batterie : modules, historique, alertes, état de l'appareil |
| GET | `/api/devices` | Public | Appareils vus récemment |
| GET | `/api/battery/<id>` | Connecté | Passeport complet, historique, modules hors seuil |
| GET | `/api/battery/<id>/recommendation` | Connecté | Recommandation du défi 3 |
| GET | `/api/notifications/count` | Connecté | Demandes en attente du propriétaire |
| GET | `/qr/<id>.png` | Public | QR code du passeport |
| GET | `/b/<id>` | Public | Cible des QR codes : vue du rôle connecté, sinon vue publique |

En-têtes acceptés par `/api/telemetry` : `X-BMS-Key` (clé machine, `bms-demo-key` par défaut ; `X-Device-Token` reste accepté) et `X-Device-Id` (nom de l'appareil affiché). Un appareil qui envoie seulement `X-Device-Id` est accepté sans clé, pour le firmware ESP32 déjà flashé ; `BP_STRICT_KEY=1` impose la clé à tous. L'ancien identifiant `DLR-1985` est accepté et redirigé vers `BAT-DOC-001`.

---

## 14. Configuration

Toutes les options sont des variables d'environnement.

| Variable | Défaut | Effet |
|---|---|---|
| `BP_BACKEND` | `neo4j` si `NEO4J_URI` est défini, sinon `memory` | Base utilisée |
| `NEO4J_URI` | `bolt://localhost:7687` | Adresse Neo4j |
| `NEO4J_USER` | `neo4j` | Utilisateur Neo4j |
| `NEO4J_PASSWORD` | `password` | Mot de passe Neo4j (`hackathon2026` avec le docker-compose fourni) |
| `NEO4J_DATABASE` | `neo4j` | Base Neo4j |
| `BP_BASE_URL` | `http://localhost:8000` | URL encodée dans les QR codes |
| `BP_SECRET_KEY` | valeur de développement | Clé de signature des sessions |
| `BP_BMS_KEY` | `bms-demo-key` | Clé machine attendue dans `X-BMS-Key` |
| `BP_DEVICE_TOKEN` | vide | Remplace la clé machine si défini (compatibilité) |
| `BP_STRICT_KEY` | vide | `1` : la clé est exigée même des appareils identifiés par `X-Device-Id` |
| `BP_SMTP_HOST`, `BP_SMTP_PORT`, `BP_SMTP_USER`, `BP_SMTP_PASSWORD`, `BP_SMTP_FROM` | vide | Envoi réel des notifications par mail ; sans hôte, les mails sont simulés |
| `BP_WASTE_CODE` | `16 06 05` | Code déchet porté sur les documents de transport |
| `BP_DEMO_BATTERY` | `BAT-DOC-001` | Batterie affichée en direct sur l'accueil |
| `MQTT_HOST` | vide (MQTT désactivé) | Broker MQTT à écouter (Wokwi, mode 3) |
| `MQTT_PORT` | `1883` | Port MQTT |
| `TOPIC_PREFIX` | `esilv-hack-2026/equipe-XX` | Préfixe des sujets `<préfixe>/battery/<id>/telemetry` |
| `BP_HOST`, `BP_PORT` | `0.0.0.0`, `8000` | Utilisés par `python app.py` |

---

## 15. Tests

```bash
python -m pytest -q
```

30 tests, tous en mode mémoire :

- `tests/test_parcours.py` : connexion, isolation des rôles, parcours complet garage, propriétaire, transporteur, centre de tri (scellé, pesée, preuve de dépôt), refus du propriétaire, transitions interdites, rendu de toutes les pages.
- `tests/test_defi2_logistique.py` : collecte automatique, centres non agréés ou non équipés refusés, notifications de chaque acteur, écart de pesée, refus à réception puis redirection, annulation, chaîne d'étapes signées et détection d'altération, documents imprimables.
- `tests/test_defi3.py` : les 5 cas de l'algorithme, la règle de sécurité, l'effet du marché, les priorités du centre, l'intégration web, l'ajout et la suppression de demandes.
- `tests/test_telemetrie.py` : passage nominal, surveillance puis critique sur un vrai paquet ESP32, alerte unique, anciens noms de champs et loi d'Ohm, trames invalides rejetées sans rien écrire, clé machine, lots de trames, SOH/SOC et nœuds de relevé, données de la courbe, vue publique sans données de santé, et contrôle qu'aucune page ne contient d'emoji ni de tiret long.

---

## 16. Structure du dépôt

```
app.py                      FastAPI : pages, API JSON, ingestion de la télémétrie, QR codes, MQTT
bp/
  config.py                 configuration et comptes de test
  workflow.py               règles du parcours (statut, transfert, réception)
  telemetry.py              règles de santé des modules, lecture des paquets BMS
  decision.py               algorithme du défi 3
  memory_repo.py            base en mémoire (même modèle de graphe)
  neo4j_repo.py             accès Neo4j (toutes les requêtes Cypher)
  seed_data.py              jeu de données de démo, source unique
templates/                  pages Jinja (accueil, rôles, passeport public, panneau de décision)
static/
  style.css                 système visuel complet
  live.js                   baie de cellules en direct
  app.js                    scanner QR, compteur de notifications
  defi3.js                  onglets du panneau de décision
  icons.svg                 icônes Lucide
  fonts/                    Michroma et Archivo, auto-hébergées
  brand/                    logos ESILV et Capgemini
esp32/
  firmware/                 firmware PlatformIO (modes Bluetooth, HTTP, MQTT)
  wokwi/                    simulation en ligne (MQTT)
  emulator/                 émulateur Python
scripts/                    chargement Neo4j, export Cypher, génération des QR codes
data/                       seed.cypher généré, archives de la première version
qr/                         QR codes imprimables des batteries de démo
docs/                       notes du défi 1, propositions d'interface du défi 3
tests/                      tests pytest
PRODUCT.md, DESIGN.md       contexte produit et système de design
docker-compose.yml          Neo4j en conteneur
```

---

## 17. Design

Le site est pensé comme le boîtier usiné de la batterie elle-même : aluminium anodisé bleu nuit, plaque d'identification en titane gravée, cinq cellules sous verre qui chauffent en direct. Les règles complètes sont dans `DESIGN.md`. En résumé :

- **Couleurs** : les bleus Capgemini `#0070AD` (surfaces anodisées) et `#12ABDB` (réservé à ce qui est en direct ou actionnable), une rampe anodisée en 11 pas pour les neutres, ambre `#F2B33D` et rouge-orangé `#FF6A3D` pour la santé des modules. Pas de vert.
- **Typographie** : Michroma pour la gravure (titres de plaque, identifiants, lectures d'état), Archivo à largeur variable pour tout le texte. Les deux polices sont servies par le site, sans CDN.
- **Icônes** : Lucide, dessinées, jamais d'emoji. Aucun tiret long dans les textes.
- **Logos** : ESILV et Capgemini, versions officielles et versions inversées pour fond sombre.
- **Responsive** : accueil au projecteur, garagiste sur tablette, centre de tri sur téléphone ; cibles tactiles de 44 px minimum.

---

## 18. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| « BMS hors ligne » alors que la carte tourne | La carte n'atteint pas le PC | Vérifier `SERVER_URL` (IP du PC, port 8000), même Wi-Fi 2,4 GHz, site lancé avec `--host 0.0.0.0`, pare-feu ouvert sur le port 8000 |
| Le moniteur série affiche `POST erreur` | Mauvaise IP ou site arrêté | Tester `http://<IP>:8000/api/devices` depuis un téléphone sur le même Wi-Fi |
| `POST ... -> 401` | Jeton d'appareil différent | Même valeur dans `DEVICE_TOKEN` et `BP_DEVICE_TOKEN`, ou les deux vides |
| `POST ... -> 400` | Batterie inconnue ou JSON mal formé | `BATTERY_ID` doit exister dans les données (`BAT-DOC-001` par défaut) |
| La carte ne se connecte jamais au Wi-Fi | Réseau 5 GHz seul ou portail captif | Utiliser un partage de connexion 2,4 GHz |
| Le scanner caméra refuse de s'ouvrir | Page en `http` hors `localhost` | Appareil photo natif, saisie manuelle, ou https via ngrok |
| Les QR codes ouvrent `localhost` sur le téléphone | `BP_BASE_URL` non défini | Relancer avec `BP_BASE_URL=http://<IP>:8000` |
| Wokwi n'apparaît pas sur le site | MQTT désactivé côté site | Lancer avec `MQTT_HOST=broker.hivemq.com` et le même `TOPIC_PREFIX` |
| Erreur de connexion Neo4j au démarrage | Base arrêtée ou mauvais mot de passe | Démarrer la base, vérifier `NEO4J_PASSWORD`, ou retirer `NEO4J_URI` pour revenir en mémoire |

---

## 19. Limites de la preuve de concept

- Comptes de test avec mots de passe en clair, sessions signées par une clé de développement.
- Les séries temporelles vivent dans le graphe ; en production elles iraient dans une base dédiée (TimescaleDB, InfluxDB), Neo4j gardant les agrégats, les alertes et les liens.
- La résistance est simulée à partir des entrées analogiques ; un vrai BMS la calculerait par R = ΔV / I sur chaque module.
- L'état « en ligne » des appareils est gardé en mémoire et se perd au redémarrage.
- Les seuils du défi 3 sont des hypothèses de l'équipe, pas des valeurs réglementaires.

---

## 20. Crédits

Équipe du hackathon ESILV x Capgemini Engineering, branches `main`, `common-ground`, `defi-1`, `defi_3` et `visuel`.

- Logos ESILV et Capgemini : fichiers du domaine public sur Wikimedia Commons, versions inversées dérivées pour fond sombre (`static/brand/`).
- Icônes : [Lucide](https://lucide.dev), licence ISC.
- Polices : Michroma et Archivo, SIL Open Font License (`static/fonts/`).
- Scanner QR : html5-qrcode ; génération des QR codes : qrcode (Python).
