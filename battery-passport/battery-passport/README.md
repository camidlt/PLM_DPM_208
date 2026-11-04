# ⚡ Battery Passport – Battery to the Future (Projet 2, Défi #1)

PoC Battery Passport : Neo4j + 3 interfaces par rôle + QR code + **télémétrie BMS émulée** (résistance interne des 5 modules, alerte critique).

```
Wokwi ESP32 (ou émulateur Python) ──MQTT/HTTP──► Backend FastAPI ──► Neo4j
                                                     │
              QR code ──► /passport/DLR-1985 ──► Garagiste · Propriétaire · Centre de tri
```

---

## 🧭 LE PLAN, ÉTAPE PAR ÉTAPE

### Étape 0 – Organisation (10 min)
- [ ] Choisir un **préfixe MQTT unique** pour l'équipe, ex. `esilv-hack-2026/equipe-07`.
      Il faut le mettre à 2 endroits : `wokwi/sketch.ino` (`TOPIC_PREFIX`) et la variable `TOPIC_PREFIX` du backend.
- [ ] Répartir : **A** Wokwi/BMS · **B** Neo4j + backend · **C** interfaces + QR · **D** slides, maquettes, README, vidéo.
- [ ] **Données** : aucun dump n'est fourni. Le jeu de données de démo (`neo4j/seed.cypher`) respecte le modèle Capgemini et se charge automatiquement. Le détail est dans `docs/DONNEES.md`.

### Étape 1 – Lancer Neo4j (15 min) – personne B
Option Docker :
```bash
docker compose up -d          # Neo4j Browser : http://localhost:7474  (neo4j / hackathon2026)
```
Option Neo4j Desktop : créer une base locale, mot de passe `hackathon2026`.

Rien à importer : le backend charge le jeu de données au démarrage. Il contient 4 modèles et 7 batteries, avec tous les nœuds du modèle Capgemini (voir `docs/DONNEES.md`).
Pour vérifier, ouvrez le Neo4j Browser une fois le backend lancé :
```cypher
CALL db.schema.visualization();                       // doit ressembler à la Figure 1 du sujet
MATCH p=(:Model {modelId:'FC-88'})-[*1..2]->() RETURN p;  // tout le passeport du modèle FC-88
```

### Étape 2 – Lancer le backend (15 min) – personne B
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
# Windows PowerShell : $env:TOPIC_PREFIX="esilv-hack-2026/equipe-07"
export TOPIC_PREFIX="esilv-hack-2026/equipe-07"
export PUBLIC_URL="http://<IP-WIFI-DU-PC>:8000"         # pour que le QR marche sur téléphone
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
Au démarrage, le backend exécute `neo4j/seed.cypher` : il crée 3 fabricants, 4 modèles et 7 batteries (dont **DLR-1985**, la batterie de Doc), avec **5 modules** chacune et un seuil constructeur de résistance interne. Le script est rejouable sans créer de doublons.

Ouvrir **http://localhost:8000** → la page passeport avec le QR code et le choix du rôle.

> Variables disponibles : `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `PUBLIC_URL`, `MQTT_HOST` (vide = MQTT désactivé), `TOPIC_PREFIX`.

### Étape 3 – Premier test sans matériel (5 min) – personne B
```bash
cd emulator
python bms_emulator.py                 # envoie la télémétrie en HTTP au backend
```
Ouvrez la page Garagiste : les 5 modules sont verts. Au bout d'environ 20 s, le **module 3** monte, passe orange puis rouge, et l'alerte critique apparaît. **Si ça marche, le cœur du défi est fait.**

### Étape 4 – Le BMS sur Wokwi (1 à 2 h) – personne A
1. Aller sur https://wokwi.com, puis *New project* → **ESP32**.
2. Copier dans le projet : `wokwi/sketch.ino`, `wokwi/diagram.json` et `wokwi/libraries.txt` (onglet *Library Manager* : PubSubClient et ArduinoJson).
3. Changer `TOPIC_PREFIX` dans le sketch, puis lancer la simulation ▶.
4. Le moniteur série affiche les trames JSON envoyées toutes les 2 s.
5. **Tourner le potentiomètre** : la résistance du module 3 monte, la LED rouge s'allume, et l'alerte apparaît sur l'écran du garagiste.

Si le câblage du `diagram.json` ne s'affiche pas correctement, recâblez à la main : potentiomètre SIG → GPIO34, LED → GPIO2 (avec une résistance de 220 Ω vers GND).
**Plan B** : si Wokwi ou MQTT bloque, `python bms_emulator.py --mode mqtt --topic-prefix <votre préfixe>` fait exactement la même chose.

### Étape 5 – Dérouler le workflow complet (30 min) – tous
| # | Rôle | Écran | Action |
|---|---|---|---|
| 1 | Garagiste | `/app/garagiste.html` (tablette) | Voit les 5 modules en temps réel ; le module 3 dépasse le max → **ALERTE** |
| 2 | Garagiste | | Clique **« Signaler au propriétaire »** (le bouton n'est actif qu'en cas de défaut critique) |
| 3 | Propriétaire | `/app/owner.html` (desktop) | Reçoit la notification, voit les preuves de télémétrie, passe **Original → Waste** |
| 4 | Centre de tri | `/app/recycler.html` (mobile, via le QR) | Constate le statut **Waste**, accuse réception, **lance le recyclage** (bloqué si ≠ Waste) |

Remise à zéro entre deux répétitions : `curl -X POST http://localhost:8000/api/demo/reset/DLR-1985`

### Étape 6 – Peaufiner (jour 2)
- [ ] Imprimer le QR code (`/qr/DLR-1985.png`) et le coller sur une « batterie » pour la démo.
- [ ] Ajouter vos idées : export PDF du diagnostic, seuils modifiables dans l'UI, température comme 2ᵉ critère.
- [ ] Montrer le graphe dans Neo4j Browser pendant la démo (voir les requêtes ci-dessous). Ça marque des points.

### Étape 7 – Livrables (jour 2 soir → jour 3 matin) – personne D
- [ ] **Slides de synthèse (10 à 15)** : contexte réglementaire 2027, cas d'usage, architecture, défi 1, démo, suite.
- [ ] **Maquettes** (captures des 3 écrans) et **diagrammes** (architecture, BPMN du workflow, modèle de données).
- [ ] **Livrables du défi 1** : voir `docs/DEFI1.md` (schéma de données, table des seuils, scénario de test).
- [ ] **Démo** : une vidéo de 2 à 3 min (au cas où le Wi-Fi tombe le jour J) + ce dépôt.
- [ ] **README** : celui-ci, complété avec vos comptes de test et vos noms.

---

## 🔍 Requêtes utiles pour la démo (Neo4j Browser)
```cypher
// Toute la batterie et ses modules
MATCH (mo:Model)-[:HAS_BATTERY_INSTANCE]->(b:BatteryInstance {batteryId:'DLR-1985'})-[:HAS_MODULE]->(m)
RETURN mo, b, m;

// Le module en défaut, son alerte et ses 10 dernières mesures
MATCH (m:Module)-[:RAISED]->(a:Alert) WITH m, a
MATCH (m)-[:HAS_MEASUREMENT]->(x) RETURN m, a, x ORDER BY x.ts DESC LIMIT 10;

// La traçabilité complète du passeport
MATCH (b:BatteryInstance {batteryId:'DLR-1985'})-[:HAS_EVENT]->(e) RETURN b, e;
```

## 🌐 API
| Méthode | Route | Rôle (en-tête `X-Role`) |
|---|---|---|
| GET | `/api/batteries/{id}` | tous : passeport, modules, alertes, historique |
| GET | `/api/batteries/{id}/history?limit=60` | tous : séries de mesures |
| POST | `/api/telemetry` | BMS (ingestion HTTP) |
| POST | `/api/batteries/{id}/report` | `garagiste` |
| GET | `/api/notifications?role=owner` | propriétaire |
| POST | `/api/batteries/{id}/status` | `owner` uniquement |
| POST | `/api/batteries/{id}/reception` | `recycler` |
| POST | `/api/batteries/{id}/recycling/start` | `recycler` (refusé si ≠ Waste) |
| GET | `/qr/{id}.png` | QR code vers `/passport/{id}` |

Documentation interactive : http://localhost:8000/docs

> ⚠️ PoC : les rôles passent par un simple en-tête HTTP. En production, il faudrait une vraie authentification (OAuth/OIDC) et des droits par rôle. C'est à mentionner dans le pitch.
