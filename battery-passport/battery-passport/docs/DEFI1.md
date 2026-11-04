# Défi #1 – Télémétrie & données dynamiques côté garagiste

## 1. Schéma de données (extension du modèle fourni)

Les nœuds ajoutés au modèle Capgemini sont marqués ★.

```
(:Model)-[:HAS_STATIC_PERFORMANCE]->(:StaticPerformance { …, ★maxInternalResistance: 25.0, ★internalResistanceUnit: 'mOhm' })
(:Model)-[:HAS_BATTERY_INSTANCE]->(:BatteryInstance { batteryId, batteryPassportId, status })
(:BatteryInstance)-[:HAS_MODULE]->(★:Module { moduleId, position, health, consecutiveOver,
                                              lastResistance, lastTemperature, lastVoltage, lastCurrent, lastTs })
(:Module)-[:HAS_MEASUREMENT]->(★:Measurement { ts, voltage, current, internalResistance, temperature })
(:Module)-[:LATEST]->(:Measurement)               // dernière mesure, accès rapide
(:Module)-[:RAISED]->(★:Alert { alertId, level, ts, value, threshold, message, open, reportedAt })
(:BatteryInstance)-[:HAS_EVENT]->(★:Event { type, ts, role, by, details })   // traçabilité du workflow
(★:Notification { toRole, requestedStatus, message, read })-[:ABOUT]->(:BatteryInstance)
```

**Choix de conception**
- Le **seuil est porté par le Model** (donnée constructeur), pas codé en dur : chaque modèle de batterie a sa propre limite.
- Les mesures sont des **nœuds horodatés** : l'historique sert de preuve au propriétaire puis au centre de tri.
- `health` et `last*` sont **dénormalisés sur le Module** : l'UI garagiste lit l'état courant en une seule requête.
- En production, les séries temporelles iraient dans une base dédiée (TimescaleDB, InfluxDB). Neo4j ne garderait que les agrégats, les alertes et les liens.

## 2. Calcul de la résistance interne

Le BMS mesure, pour chaque module, la tension à vide `V_ocv`, la tension sous charge `V_load` et le courant `I` :

> **R = (V_ocv − V_load) / I**   (×1000 pour obtenir des mΩ)

Ordres de grandeur : un module sain fait environ 8 mΩ ; le maximum constructeur est de 25 mΩ ; le module défectueux de la démo atteint 45 à 60 mΩ.
Une résistance interne élevée entraîne des pertes par effet Joule (P = R·I²) : la batterie consomme plus d'énergie et chauffe. C'est exactement le symptôme décrit par Doc.

## 3. Table des seuils et règles d'alerte

| Niveau | Condition | Effet UI | Effet métier |
|---|---|---|---|
| OK | R < 0,8 × Rmax | carte verte | — |
| WARNING | 0,8 × Rmax ≤ R ≤ Rmax, ou R > Rmax depuis moins de 3 mesures | carte orange | surveillance |
| **CRITICAL** | **R > Rmax sur 3 mesures consécutives** | carte rouge clignotante + bannière d'alerte | création d'une `Alert`, bouton « Signaler au propriétaire » activé |

La règle des 3 mesures consécutives sert d'anti-rebond : un pic isolé (bruit capteur, appel de courant) ne déclenche pas d'alerte.
Une seule alerte reste ouverte par module, pour éviter le spam.

## 4. Scénario de test (valeurs normales → critique)

| Étape | Entrée BMS (module 3) | Attendu |
|---|---|---|
| T1 | 5 modules à environ 8 mΩ | 5 cartes OK, aucune alerte |
| T2 | M3 = 21 mΩ | M3 en WARNING (≥ 20 mΩ = 80 % de 25) |
| T3 | M3 = 30 mΩ (1ʳᵉ et 2ᵉ mesures) | M3 en WARNING, pas encore d'alerte |
| T4 | M3 = 30 mΩ (3ᵉ mesure) | M3 en **CRITICAL**, une `Alert` créée, bouton garagiste actif |
| T5 | M3 reste haut | toujours une seule alerte ouverte |
| T6 | Garagiste → « Signaler » | `Event DIAGNOSIS_REPORTED` + `Notification` au propriétaire |
| T7 | Propriétaire → Waste | statut Waste, `Event STATUS_CHANGED`, notification lue |
| T8 | Centre de tri → « Lancer le recyclage » | autorisé (Waste) ; avant T7 → refus HTTP 409 |
| T9 | Mauvais rôle (ex. garagiste qui change le statut) | refus HTTP 403 |

Pour rejouer le scénario automatiquement : `python emulator/bms_emulator.py --normal 5 --step 4`
