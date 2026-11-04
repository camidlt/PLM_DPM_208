# Jeu de données – Battery Passport

Aucun dump n'a été fourni : l'équipe a construit un **jeu de données de démo** qui respecte **nœud par nœud le modèle Capgemini** (Figure 1 du sujet). Il est chargé automatiquement par `neo4j/seed.cypher` au démarrage du backend.
Les ajouts de l'équipe sont marqués ★. Les entreprises et les personnes sont fictives ; les ordres de grandeur techniques sont réalistes.

## Contenu

| Élément | Quantité | Détail |
|---|---|---|
| Company | 3 | Doc Brown Industries, Hill Valley Energy, Mr. Fusion Mobility |
| EconomicOperator | 3 | adresse, pays, email, téléphone, site web |
| Type | 3 | Electric Vehicle Battery, Light Means of Transport Battery, Industrial Battery : les 3 catégories visées par le passeport en 2027 |
| Model | 4 | FC-88 (NMC 811, 75 kWh), HV-LFP-60 (LFP, 60 kWh), MF-48 (vélo électrique, 0,75 kWh), CT-200 (stockage industriel, 200 kWh) |
| Données statiques du modèle | 4 × 7 nœuds | StaticPerformance, StaticDurability, Certification, Circularity, CarbonFootprint, Composition → Anode / Cathode / Electrolyte |
| BatteryInstance | 7 | tous les statuts représentés : Original, Waste, Repurposed, Reused |
| Données dynamiques | 7 × 2 | DynamicPerformance (soce, soc) et DynamicDurability (warranty, accidents) |
| ★ Module | 35 | 5 modules par batterie (défi 1) |
| ★ Event MANUFACTURED | 7 | point de départ de la traçabilité |

## Les batteries

| batteryId | Modèle | Statut | SOCE | Rôle dans la démo |
|---|---|---|---|---|
| **DLR-1985** | FC-88 | Original | 71 % | ⭐ La batterie de Doc : celle qui tombe en panne |
| DLR-2015 | FC-88 | Original | 94 % | Même modèle en bon état, pour comparer |
| DLR-1955 | FC-88 | Waste | 38 % | Déjà déclarée déchet |
| HVB-0001 | HV-LFP-60 | Original | 97 % | Batterie LFP neuve |
| HVB-0002 | HV-LFP-60 | Repurposed | 76 % | Seconde vie : stockage pour bornes de recharge (cf. défi 3) |
| MF-0042 | MF-48 | Reused | 82 % | Batterie de VTT électrique réemployée (cf. défi 3) |
| CTS-1885 | CT-200 | Original | 90 % | Batterie industrielle de plus de 2 kWh |

## Extensions de l'équipe (★)
- `StaticPerformance.maxInternalResistance` : seuil constructeur de résistance interne par module (défi 1).
- `BatteryInstance` : `serialNumber`, `manufacturingDate`, `manufacturingPlace`, `weightKg`, `currentHolder`, `installedIn`. Ces informations sont exigées par le règlement européen mais absentes du modèle simplifié.
- `Module`, `Measurement`, `Alert` : télémétrie du BMS (voir `DEFI1.md`).
- `Event`, `Notification` : traçabilité du workflow et communication entre les rôles.

## Pour le pitch
Le contenu du passeport est fixé par le **Règlement (UE) 2023/1542, Annexe XIII**. Le modèle Capgemini en couvre une partie : identification, opérateur, chimie et composition, empreinte carbone, performance et durabilité, déclaration UE de conformité.
On peut citer des attributs que l'on ajouterait ensuite : contenu recyclé (cobalt, lithium, nickel, plomb), substances dangereuses, et nombre de cycles réels.
