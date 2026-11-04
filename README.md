# Battery Passport (PoC)

Hackathon ESILV x Capgemini Engineering, « Battery to the Future ».

Un seul site FastAPI réunit tout le travail des branches : le tronc commun (diagnostic, mise à jour du statut, transfert, réception), le défi 1 (télémétrie BMS en direct depuis un ESP32) et le défi 3 (aide à la décision du centre de tri).

| Page | Appareil visé | Rôle |
|---|---|---|
| `/` | Projecteur, ordinateur | Présentation pour le jury, modules de DLR-1985 en direct |
| `/garage` | Tablette | Garagiste : scan QR, passeport, télémétrie live, signalement hors d'usage |
| `/owner` | Desktop | Propriétaire du passeport : statut Original vers Waste, ordre de transfert vers un centre agréé |
| `/tri` | Mobile | Centre de tri : contrôle du statut, réception, recommandation Reuse / Remanufacture / Repurpose / Recycle |
| `/public/b/<id>` | Tout téléphone | Passeport public (Annexe XIII), sans connexion |

## 1. Lancer le site

Python 3.10 ou plus.

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Ouvrir http://localhost:8000. Sans Neo4j, les données sont en mémoire (partagées par tous les navigateurs, remises à zéro au redémarrage ou avec « Réinitialiser la démo »).

### Avec Neo4j

```bash
docker compose up -d                      # ou une base Neo4j Desktop 5.x
export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=hackathon2026
python scripts/seed_neo4j.py              # charge le jeu de démo
uvicorn app:app --host 0.0.0.0 --port 8000
```

Le pied de page affiche alors « Base : neo4j ». `data/seed.cypher` contient le même jeu de données à coller dans Neo4j Browser.

### Sur tablette et téléphone

Lancer le site avec l'IP Wi-Fi du PC pour que les QR codes pointent au bon endroit :

```bash
BP_BASE_URL=http://192.168.1.20:8000 uvicorn app:app --host 0.0.0.0 --port 8000
```

Le QR code de chaque batterie est servi sur `/qr/<id>.png` (et `scripts/make_qr.py` régénère les PNG imprimables de `qr/`). Le scanner intégré utilise la caméra, que les navigateurs n'autorisent qu'en `https://` ou sur `localhost` : en Wi-Fi local, scanner avec l'appareil photo natif ou saisir l'identifiant.

## 2. L'ESP32 : comment ça marche

```
ESP32 (5 entrées analogiques)  --Wi-Fi, HTTP POST toutes les 3 s-->  /api/telemetry
        |                                                                  |
   Bluetooth série (débogage)                          graphe : Module, Measurement, Alert
                                                                           |
                                         écrans garagiste, propriétaire, accueil (rafraîchis toutes les 2 s)
```

1. **Mesure.** Le firmware (`esp32/firmware`, PlatformIO) lit 5 broches analogiques (GPIO 34, 35, 32, 33, 25), une par module, et les convertit en résistance interne : entre 1,0 et 1,5 mΩ pour un module sain du FC-85.
2. **Défaut à la demande.** Un appui sur le bouton **BOOT** de la carte lance la dérive du module 3 : sa résistance monte à chaque mesure jusqu'à 6,8 mΩ. Un second appui le remet à l'état sain. Pratique pour déclencher la panne devant le jury.
3. **Envoi.** Toutes les 3 s, l'ESP32 envoie en Wi-Fi ce JSON au PC :
   ```json
   {"batteryId": "DLR-1985", "source": "ESP32",
    "modules": [{"id": 1, "r_mohm": 1.23, "t": 24.6}, {"id": 3, "r_mohm": 6.8, "t": 24.6}]}
   ```
   Le même message part en Bluetooth série (« BMS-DeLorean-ESP32 ») et sur le moniteur série. La LED de la carte clignote à chaque envoi.
4. **Décision côté serveur.** L'ESP32 n'applique aucune règle métier. Le site calcule la santé de chaque module à partir du maximum constructeur (2,0 mΩ pour le FC-85) :
   - nominal : sous 80 % du maximum ;
   - surveillance : au moins 80 % du maximum, ou dépassement pas encore confirmé ;
   - critique : au-delà du maximum sur 3 mesures consécutives. Une `Alert` et un événement « Alerte BMS » sont alors écrits dans le graphe.
5. **Affichage.** La baie de cellules du garagiste, du propriétaire et de la page d'accueil se met à jour toutes les 2 s, avec l'état de l'appareil (en ligne si vu il y a moins de 10 s, nombre de paquets). Le formulaire de signalement se préremplit à partir de l'alerte.

### Mettre l'ESP32 en route

1. Installer [PlatformIO](https://platformio.org/) (extension VS Code ou `pip install platformio`).
2. Copier `esp32/firmware/include/secrets.example.h` en `esp32/firmware/include/secrets.h` et remplir :
   - `WIFI_SSID`, `WIFI_PASS` : le même Wi-Fi que le PC (pas de réseau 5 GHz seul, l'ESP32 ne parle que 2,4 GHz) ;
   - `SERVER_URL` : `http://<IP du PC>:8000/api/telemetry` (IP donnée par `ipconfig` ou `ip a`).
3. Brancher la carte en USB, puis `cd esp32/firmware && pio run -t upload && pio device monitor`.
4. Le moniteur affiche `POST ... -> 200` : la carte est reliée. Sur la page d'accueil, « BMS ESP32 en ligne » passe au bleu.

Le site doit écouter sur toutes les interfaces (`--host 0.0.0.0`) et le pare-feu du PC doit laisser passer le port 8000. Pour sécuriser un peu, lancer le site avec `BP_DEVICE_TOKEN=un-secret` et mettre la même valeur dans `DEVICE_TOKEN`.

### Sans ESP32

- **Émulateur Python** : `python esp32/emulator/bms_emulator.py` envoie le même JSON (5 mesures normales, puis le module 3 dérive).
- **Wokwi** : `esp32/wokwi/` simule la carte dans le navigateur avec un potentiomètre sur le module 3. Wokwi ne voit pas le PC local : il publie en MQTT, donc lancer le site avec `MQTT_HOST=broker.hivemq.com TOPIC_PREFIX=esilv-hack-2026/<équipe>` (même préfixe dans `sketch.ino`).

## 3. Comptes de test

| Rôle | Identifiant | Mot de passe |
|---|---|---|
| Garagiste (Garage Hill Valley) | `garagiste` | `garage123` |
| Propriétaire (Flux Motors) | `proprietaire` | `owner123` |
| Centre de tri Recyclo Nanterre (agréé) | `centretri` | `tri123` |
| Centre de tri Rhône Batteries (agréé) | `centretri2` | `tri123` |

Les boutons « Entrer comme ... » de la page d'accueil préremplissent le formulaire.

## 4. Scénario de démo (environ 2 min)

1. ESP32 allumé, page d'accueil au projecteur : appuyer sur BOOT, le module 3 de DLR-1985 chauffe jusqu'au critique.
2. **Garagiste** (tablette) : scanner `DLR-1985`, l'alerte module 3 est affichée, cliquer sur « Signaler hors d'usage » (formulaire prérempli).
3. *(Optionnel)* **Centre de tri** : scanner, l'écran indique « Statut NON à jour » et la réception est refusée.
4. **Propriétaire** (desktop) : la cloche affiche 1. Choisir Recyclo Nanterre (le dépôt non agréé n'est pas sélectionnable) et valider : statut Waste, ordre de transfert créé.
5. **Centre de tri** (mobile) : « WASTE, statut à jour », confirmer la réception, puis valider la recommandation (Remanufacture pour DLR-1985).
6. Montrer l'historique : chaque étape est horodatée avec son acteur, alerte BMS comprise.

## 5. Données de démo

| Batterie | Modèle | SOH | Statut | Particularité |
|---|---|---|---|---|
| `DLR-1985` | FluxCap 85 kWh (NMC 811) | 71 % | Original | La batterie de Doc, branchée sur l'ESP32 : module 3 hors seuil |
| `BAT-002` | FluxCap 85 kWh | 93 % | Original | Saine, pour montrer un refus du propriétaire |
| `BAT-003` | FluxCap 60 kWh (LFP) | 64 % | Original | Usée, 1 accident |
| `BAT-004` | FluxCap 85 kWh | 48 % | Waste | Au centre de tri, recyclage (sécurité) |
| `BAT-101`, `BAT-102`, `BAT-103` | | | Waste | Cas Reuse, Repurpose et Recycle du défi 3 |

Toutes les entreprises, adresses et numéros VIN sont fictifs. Source unique : `bp/seed_data.py`. Les jeux Neo4j Desktop de la première version FastAPI sont dans `data/archive/`.

## 6. Modèle de graphe

Base : Figure 1 du sujet (`Company`, `Type`, `Model`, `EconomicOperator`, `BatteryInstance`, `Composition`, `Anode`, `Cathode`, `Electrolyte`, `StaticPerformance`, `StaticDurability`, `CarbonFootprint`, `Certification`, `Circularity`, `DynamicPerformance`, `DynamicDurability`). Extensions :

```
(:BatteryInstance)-[:HAS_MODULE]->(:Module {index, internalResistance_mOhm, maxInternalResistance_mOhm, health, consecutiveOver})
(:Module)-[:HAS_MEASUREMENT]->(:Measurement {ts, internalResistance_mOhm, voltage, current, temperature})   défi 1
(:Module)-[:RAISED]->(:Alert {level, at, value, threshold, message, open})                                    défi 1
(:BatteryInstance)-[:HAS_EVENT]->(:Event {type, at, actorName, details})  <-[:PERFORMED]-(:Actor)
(:Actor)-[:SENT]->(:Notification {state, fromStatus, requestedStatus, reason})-[:ABOUT]->(:BatteryInstance)
(:Notification)-[:TRIGGERED]->(:TransferOrder {state})-[:TO]->(:Actor)
(:BatteryInstance)-[:HAS_DECISION]->(:Decision)-[:FULFILLS]->(:MarketDemand)                                 défi 3
```

Règles métier (`bp/workflow.py`) : seul le propriétaire change le statut ; transitions `Original -> Waste | Reused | Remanufactured | Repurposed`, `Waste` final ; une seule demande en attente par batterie ; transfert uniquement vers un centre agréé ; réception seulement si le statut est `Waste` et que l'ordre vise ce centre. Règles de télémétrie : `bp/telemetry.py`. Algorithme du défi 3 : `bp/decision.py`.

## 7. Structure

```
app.py               FastAPI : pages, API JSON, ingestion télémétrie, QR codes
bp/                  règles métier (workflow, telemetry, decision), accès Neo4j et mémoire, jeu de données
templates/, static/  interface (polices Michroma et Archivo auto-hébergées, icônes Lucide, logos)
esp32/firmware/      firmware ESP32 (PlatformIO)
esp32/wokwi/         simulation Wokwi (MQTT)
esp32/emulator/      émulateur Python
scripts/             chargement Neo4j, export Cypher, QR codes
data/                seed.cypher généré, archives
docs/                défi 1, propositions d'interface du défi 3
tests/               python -m pytest -q
```

## Crédits

Logos ESILV et Capgemini : fichiers du domaine public sur Wikimedia Commons, versions inversées pour fond sombre. Icônes : Lucide (licence ISC). Polices : Michroma et Archivo (SIL Open Font License, `static/fonts/`).
