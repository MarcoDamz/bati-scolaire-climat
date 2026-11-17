# Phase 0 — Faisabilité des données du démonstrateur

*Sondes du 17/11/2026, reproductibles avec `python3 phase0/sondes.py` (résultats bruts : `phase0/sondes_resultats.json`).*

## Décisions prises

| Sujet | Décision |
|---|---|
| Scénario | **Explore2-ADAMONT RCP8.5, par niveaux de réchauffement** (+2 / +2,7 / +4 °C), comme la TRACC |
| Interface | **marimo** (tableau de bord GitHub Pages + exploration molab), comme aujourd'hui |
| Coût | Uniquement des données et logiciels gratuits (physrisk-lib, Apache 2.0) |

## Pilotes retenus (proposition)

| Pilote | Type | Pop. | Bâtiments BDNB (propriétaire) | Aléas dominants | Reconnaissances CatNat |
|---|---|---|---|---|---|
| L'Aiguillon-la-Presqu'île (85001) | côtier | 2 845 | 32 | Submersion (TRI), argiles forte, inondation | 12 (+8 sous La Faute-sur-Mer) |
| Lacanau (33214) | côtier | 5 739 | 35 | Trait de côte, avancée dunaire, feu, tempête | 17 |
| Landiras (33225) | rural | 2 310 | 8 | Feu (2022), argiles moyenne | 15 |
| Gonfaron (83067) | rural | 4 496 | 22 | Feu, crue torrentielle, argiles moyenne | 16 |
| Carcassonne (11069) | ville moyenne | 46 080 | 132 | Crue de l'Aude (TRI), argiles forte, chaleur | 28 |

229 bâtiments au total. Carcassonne est la ville-centre de l'instance « Carcassonne Agglo » (T07).

## Climat

| Source | Accès | Résultat |
|---|---|---|
| Années pivots TRACC (Explore2, DOI 10.57745/DCOQM6) | ✅ libre | 17 simulations RCP8.5 ADAMONT. Année médiane d'atteinte : **+2 °C → 2035, +2,7 °C → 2049, +4 °C → 2074** (fourchettes 2020–2048, 2035–2064, 2059–2091). Fenêtres de 20 ans fournies par simulation. |
| Projections hydrologiques Explore2 (débits, indicateurs TRACC) | ✅ libre (Recherche Data Gouv) | Plus de 200 jeux, dont les changements par niveau de réchauffement → débits de crue pour l'inondation future |
| **Projections climatiques journalières Explore2-ADAMONT** (Tmax, pluie, vent, humidité des sols…) | ❌ **bloqué** | Diffusées sur le serveur public du CNRM (`climatedata.umr-cnrm.fr`, sans compte), mais ce serveur coupe les connexions venant de l'environnement cloud. Le portail DRIAS (accès personnalisé) exige un compte. |
| Réanalyse CERRA (5,5 km, 1984→) | ✅ catalogue ; téléchargement avec **clé CDS gratuite** | Pour le vent et les pluies extrêmes actuels |
| Empreintes de tempêtes C3S (1940→) | ✅ catalogue ; **clé CDS gratuite** | Rafales maximales par tempête, grille jusqu'à ~1,6 km |

## Aléas (situation actuelle)

| Source | Accès | Couverture des pilotes |
|---|---|---|
| Hauteurs d'eau TRI (WFS Géorisques, classes 0–0,5 / 0,5–1 / 1–2 / >2 m) | ✅ libre | **Carcassonne** (débordement : fréquent, moyen, extrême) ; **L'Aiguillon** (submersion : fréquent, moyen, extrême). Aucune carte pour les 3 autres pilotes. Pas de scénario « avec changement climatique » (MCC) sur ces deux TRI. |
| Atlas des zones inondables (API Géorisques) | ✅ libre | Carcassonne (3 atlas), L'Aiguillon (ASM) |
| Argiles BRGM (API Géorisques, au point) | ✅ libre | Forte : L'Aiguillon, Carcassonne. Moyenne : Landiras, Gonfaron. Lacanau : hors zone (sables) |
| Risques recensés, CatNat (API Géorisques) | ✅ libre | Tous |
| Indicateur national d'érosion côtière (Cerema, 2026) | ✅ libre (Géolittoral, shapefile) | Lacanau, L'Aiguillon |
| Projection du trait de côte 2050/2100 (Cerema 2024) | ⚠️ cartes publiées ; fichier vectoriel national non trouvé | Ordres de grandeur uniquement selon le Cerema |
| Forêts (masque forêt IGN, BD Forêt) | ✅ libre (WFS Géoplateforme) | Tous, pour l'interface forêt-habitat |
| EAIP (enveloppes d'inondation potentielle) | ⚠️ publiées par département (DDT) | À rechercher pour l'Hérault/Var/Gironde |

## Bâtiments

| Source | Accès | Résultat |
|---|---|---|
| BDNB (bâtiments par SIREN propriétaire + fiche complète ~150 champs) | ✅ libre, 10 lignes par appel sans clé | 8 à 132 bâtiments par pilote |
| RNB (identifiant national, liens BDNB et BD TOPO) | ✅ libre | Tous ; sert de clé de jointure |
| BD TOPO (WFS) : hauteur, étages, altitude au sol, matériaux, usage | ✅ libre | Tous ; matériaux et étages souvent vides |
| **LiDAR HD** (API altimétrie, pas de 50 cm) | ✅ libre | Tous. Ex. : sol à 0,34 m NGF au port de L'Aiguillon (au lieu de 0,87 m avec le RGE ALTI) → hauteur d'eau au plancher précise |
| DPE ADEME (logements et tertiaire, depuis 2021) | ✅ libre | 310 à 14 206 DPE par commune |
| DVF 2024 (valeurs foncières géolocalisées) | ✅ libre | 217 à 2 260 mutations par commune |
| Inventaire ADEME des bâtiments publics (321 074 lignes) | ✅ libre, **anonymisé** | Pas localisable : sert seulement à caler les hypothèses (usage, surface, DPE par usage) |

## Blocages et actions

1. **Projections climatiques journalières (bloquant pour la phase 1).** Options, par ordre de préférence :
   - a. télécharger les fichiers Explore2-ADAMONT RCP8.5 depuis un poste où le serveur CNRM répond (ou depuis DRIAS avec un compte gratuit), puis les déposer dans un stockage accessible (Drive, bucket) ;
   - b. relier votre ordinateur à cette session pour lancer le téléchargement depuis chez vous ;
   - c. demander à Météo-France (support DRIAS) l'accès au serveur depuis un environnement cloud.
2. **Clé Copernicus CDS** (gratuite, compte sur cds.climate.copernicus.eu) pour CERRA et les tempêtes : à saisir au moment de la phase 1 via le formulaire sécurisé de la session.
3. **Inondation hors TRI** (Lacanau, Landiras, Gonfaron) : pas de hauteurs d'eau publiques. On utilisera les enveloppes EAIP / atlas + LiDAR HD, et les débits Explore2 pour l'évolution ; cela sera signalé comme moins précis dans la démo.
4. **Trait de côte futur** : localiser le fichier vectoriel du Cerema (2024) ou demander au Cerema ; à défaut, projeter l'INEC 2026 (taux × durée), comme le fait le Cerema.

## Accès réseau ajoutés à l'environnement

DRIAS, DRIAS-Eau, entrepôt Explore2 et son stockage INRAE, serveur CNRM, CDS Copernicus, Géoplateforme IGN, Géolittoral, ADEME, RNB, SHOM, files.data.gouv.fr et son stockage DVF (OVH), zenodo.
