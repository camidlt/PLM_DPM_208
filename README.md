# Battery Passport : tronc commun (PoC)

Hackathon ESILV × Capgemini Engineering, « Battery to the Future ».

L'application déroule le parcours obligatoire du sujet : **diagnostic → mise à jour du statut → transfert → réception**. Elle propose trois interfaces, une par rôle :

| Rôle | Appareil visé | Ce qu'il fait |
|---|---|---|
| **Garagiste** | Tablette | Scanne le QR code, consulte le passeport (identification, statut, SOH/SOC, résistance des 5 modules, historique), signale la batterie hors d'usage |
| **Propriétaire Battery Passport** (constructeur) | Desktop | Reçoit la notification, passe le statut **Original → Waste**, choisit un centre de tri **agréé** (ordre de transfert créé) |
| **Centre de tri** | Mobile | Scanne le QR code, vérifie que le statut est bien **Waste**, accuse réception |

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

## 4. Scénario de démo (environ 2 min)

1. **Garagiste**, sur tablette : scanner `BAT-DOC-001`, la batterie de Doc.
   - Le statut affiché est **Original** et le SOH est de 71 %.
   - L'alerte rouge indique que le **module 3** est à 6,8 mΩ, alors que le maximum constructeur est de 2,0 mΩ.
   - Cliquer sur **Signaler hors d'usage**. Le formulaire est prérempli à partir de l'alerte.
2. *(Optionnel, pour montrer le contrôle)* **Centre de tri** : scanner `BAT-DOC-001`. L'écran affiche **⛔ ORIGINAL : statut NON à jour**, et la réception est refusée.
3. **Propriétaire**, sur desktop : la cloche 🔔 affiche 1.
   - Ouvrir la demande et choisir **Centre de tri Recyclo Nanterre**. Le dépôt non agréé n'est pas sélectionnable.
   - Cliquer sur **Valider**. Le statut passe à **Waste** et l'ordre de transfert est créé.
4. **Centre de tri**, sur mobile : scanner `BAT-DOC-001`.
   - L'écran affiche **✅ WASTE : le statut est à jour**.
   - Cliquer sur **Confirmer la réception**. La batterie est désormais localisée au centre de tri.
5. Montrer l'**historique** de la batterie : chaque étape est horodatée avec son acteur. Le même historique est visible dans Neo4j.

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
(:Notification)-[:TRIGGERED]->(:TransferOrder {state: ORDERED|RECEIVED})
      (:TransferOrder)-[:FOR]->(:BatteryInstance)  -[:FROM]->(:Actor)  -[:TO]->(:Actor)
```

### Règles métier (fichier `bp/workflow.py`)

- Seul le **propriétaire** du passeport, c'est-à-dire l'opérateur économique qui a construit la batterie, peut changer le statut.
- Transitions autorisées : `Original → Waste | Reused | Remanufactured | Repurposed`, et `Waste` est un statut final.
- Il ne peut y avoir qu'une demande en attente par batterie.
- Le transfert ne peut se faire que vers un centre de tri **agréé**.
- Le centre de tri ne peut réceptionner la batterie que si son statut est `Waste` **et** si l'ordre de transfert lui est destiné.

## 7. Brancher les défis

- **Défi 1 (télémétrie)** : écrire les mesures du BMS dans les nœuds `Module` (propriété `internalResistance_mOhm` et `measuredAt`). L'écran garagiste et l'alerte se mettent à jour automatiquement, grâce à `workflow.module_alerts`.
- **Défi 3 (aide à la décision)** : un emplacement est réservé sur l'écran centre de tri, dans `templates/tri_battery.html`. Toutes les données de la batterie sont disponibles en JSON via `GET /api/battery/<id>`, après connexion.

## 8. Si le dump officiel a d'autres noms

Toutes les requêtes Cypher se trouvent dans `bp/neo4j_repo.py`. Si le dump fourni par les organisateurs utilise d'autres noms de propriétés ou de relations, c'est le seul fichier à adapter. `scripts/seed_neo4j.py` ne modifie que les nœuds de démo et laisse le reste de la base intact.

## 9. Structure

```
app.py                  routes Flask (3 rôles, scan QR, API JSON)
bp/workflow.py          règles métier du parcours
bp/neo4j_repo.py        accès Neo4j (Cypher)
bp/memory_repo.py       même chose en mémoire (démo sans Neo4j)
bp/seed_data.py         jeu de données de démo, source unique
bp/config.py            configuration et comptes de test
templates/, static/     interfaces
scripts/                seed Neo4j, export Cypher, génération des QR codes
data/seed.cypher        script Cypher généré
qr/                     QR codes des batteries de démo
tests/test_parcours.py  test du parcours complet (python -m pytest -q)
```
