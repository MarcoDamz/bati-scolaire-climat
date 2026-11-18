# Phase 1 — Climat par niveau de réchauffement (TRACC)

## Ce qui est en place

| Brique | Fichier | État |
|---|---|---|
| Fenêtres TRACC par simulation (17 chaînes Explore2 RCP8.5 ADAMONT, années pivots officielles), agrégation et synthèse d'ensemble (médiane, 10e–90e centiles, écart à 1976-2005) | `src/adaptation/tracc.py` | ✅ testé |
| Extrêmes : maxima annuels (cumuls sur N jours), loi GEV en super-ensemble (~340 années par niveau) et par chaîne, niveaux de retour 10/30/100/200 ans, fréquence future de l'événement de référence | `src/adaptation/extremes.py` | ✅ testé |
| Crues : variation du débit journalier maximal annuel et de la crue décennale par niveau, aux stations des pilotes | `src/adaptation/hydro.py` → Drive `donnees/phase1/crues_explore2_tracc.csv` | ✅ calculé |
| Extraction des projections journalières Explore2-ADAMONT aux mailles des bâtiments pilotes | `phase1/telecharger_explore2.py`, notebook Colab `notebooks/01_extraction_explore2.ipynb` | ✅ testé sur un serveur simulé ; **à lancer dans Colab** |
| Tempêtes : rafales maximales des tempêtes 1979-2025 aux bâtiments, rafales de retour 10/50/100 ans | `src/adaptation/tempetes.py` → Drive `donnees/phase1/tempetes_*.csv` | ✅ calculé (1 095 tempêtes, 47 ans) |

Années d'atteinte des niveaux (médiane des 17 simulations) : +2 °C → 2035, +2,7 °C → 2049, +4 °C → 2074.

## Premiers résultats : crues (Explore2-Hydro, référence 1991-2020)

Variation médiane de la crue décennale journalière (QJXA-10), 67 à 82 simulations par station :

| Pilote | Station | Représentativité | +2 °C | +2,7 °C | +4 °C | Fourchette à +4 °C |
|---|---|---|---|---|---|---|
| Carcassonne | Aude à Limoux | bonne | +11 % | +15 % | +8 % | −25 % à +40 % |
| Carcassonne | Fresquel à Carcassonne | bonne | +4 % | +10 % | −4 % | −34 % à +58 % |
| Gonfaron | Aille au Cannet-des-Maures | bonne | +7 % | −1 % | −7 % | −40 % à +43 % |
| L'Aiguillon | Lay à La Bretonnière | moyenne | +7 % | +6 % | +10 % | −23 % à +52 % |
| Lacanau | Canal des Étangs au Porge | moyenne | +9 % | +20 % | +22 % | −25 % à +68 % |
| Landiras | Petite Leyre à Belhade | faible | +7 % | 0 % | +5 % | −29 % à +45 % |

**À retenir pour la démo :** sur les bassins méditerranéens (Aude, Aille), les débits *journaliers* ne captent pas
les épisodes orageux de quelques heures, et l'incertitude dépasse le signal. L'évolution de l'aléa inondation y
sera donc pilotée aussi par les pluies extrêmes (cumul maximal sur 1 jour et sur 5 jours d'Explore2-ADAMONT).

## Source des projections journalières : Socle Métropole (Météo-France, 2025)

Le serveur public du CNRM qui diffusait Explore2-ADAMONT (`climatedata.umr-cnrm.fr` et son miroir
`climatedata.cnrm-game-meteo.fr`) est injoignable, depuis le cloud comme depuis un poste classique (18/11/2026).
Source retenue à la place :
[Projections climatiques Socle Métropole](https://www.data.gouv.fr/datasets/projections-climatiques-pour-le-hackathon-2025-socle-metropole)
(Météo-France, Licence Ouverte, stockage objet data.gouv, sans compte).

| | Explore2-ADAMONT (base TRACC 2023) | Socle Métropole (2025) |
|---|---|---|
| Génération de modèles | EURO-CORDEX CMIP5 | **EURO-CORDEX CMIP6** (plus récente) |
| Simulations | 17, RCP8.5 | **17** historiques + SSP3-7.0, dont 4 aussi en SSP5-8.5 |
| Résolution, correction | 8 km, ADAMONT | 8 km, CDF-t sur ANASTASIA (températures) / SAFRAN |
| Variables quotidiennes | T, pluie, vent, humidité… | tas, tasmax, tasmin, pr, rsds, rlds, huss, sfcWind |
| Orages | non résolus | **AROME 2,5 km à convection résolue, pluie horaire** (1 simulation) |
| Statut | publié | « en cours d'évaluation » selon Météo-France |

Conséquences :
- **Scénario** : le niveau de réchauffement ne dépend pas du scénario d'émissions ; SSP3-7.0 (17 simulations)
  remplace RCP8.5 et atteint +4 °C en France avant 2100. Les années TRACC ne sont pas encore fournies pour ce
  jeu : elles seront calculées par la méthode officielle (niveaux de réchauffement planétaire +1,5 / +2 / +3 °C
  du modèle global de chaque simulation ↔ +2 / +2,7 / +4 °C en France).
- **Pas d'humidité des sols ni d'indice feu fournis** : SWI (argiles) à reconstituer (bilan hydrique simplifié,
  calé sur le SWI observé ouvert de Météo-France « dispositif CatNat ») ; indice feu (IFM) calculé à partir de
  T, humidité, vent, pluie.
- Explore2 reste utilisé pour l'hydrologie (débits par niveau TRACC, déjà calculés) ; `phase1/telecharger_explore2.py`
  est conservé au cas où le serveur du CNRM revienne.

## À faire de votre côté : extraire le Socle Métropole

Ouvrir `notebooks/01_extraction_climat.ipynb` dans Google Colab (bouton dans le README) et exécuter les cellules.
L'inventaire (étape 3) doit trouver 17 simulations par variable ; sinon envoyer `socle_inventaire.csv`.
Sortie : `SaaS adaptation climatique/demo/donnees/climat_socle/`. Si Colab est refusé, lancer
`python3 phase1/telecharger_socle.py --cprcm --dossier "<Drive>/SaaS adaptation climatique/demo/donnees/climat_socle"`.

## Premiers résultats : tempêtes (C3S, ERA5, 1979-2025, maille 0,25°)

| Pilote | Rafale décennale | Cinquantennale | Centennale | Tempêtes les plus fortes |
|---|---|---|---|---|
| Lacanau | 119 km/h | 142 km/h | 153 km/h | Martin 27/12/1999 (152), 07/02/1996 (128), Klaus 23/01/2009 (127) |
| Carcassonne | 117 km/h | 137 km/h | 147 km/h | Klaus 23/01/2009 (150), 07/02/1996 (132), Martin 1999 (127) |
| L'Aiguillon-la-Presqu'île | 114 km/h | 128 km/h | 134 km/h | Martin 1999 (141), Xynthia 28/02/2010 (126) |
| Landiras | 106 km/h | 125 km/h | 133 km/h | Martin 1999 (126), Klaus 2009 (125) |
| Gonfaron | 92 km/h | 96 km/h | 97 km/h | 08/02/1984 (98), 05/03/2017 (95) |

Limites à afficher dans la démo :
- maille de ~25 km : les pointes locales sont lissées (Martin a dépassé 170 km/h sur le littoral girondin) ;
- le catalogue suit les tempêtes atlantiques hivernales : les coups de vent méditerranéens (Gonfaron) sont mal captés,
  d'où des valeurs de retour basses et peu fiables pour ce pilote ;
- climat actuel seulement : pas de variation avec le niveau TRACC (tendance future des tempêtes jugée peu fiable par le GIEC).

## Clé Copernicus

Clé valide et licences acceptées (tempêtes, CERRA) ; enregistrée dans les secrets réseau de l'environnement `bati-scolaire-climat`.

## Suite de la phase 1, dès réception des données

- Conversion des unités, puis indicateurs par niveau TRACC et par bâtiment : jours > 30/35 °C, nuits tropicales,
  degrés-jours de climatisation, cumuls de pluie 1 j / 5 j et leurs niveaux de retour, sécheresse des sols
  (SWI, pour les argiles), Indice Forêt Météo (feux).
- Vent : évolution du vent moyen extrême d'Explore2, affichée avec sa faible fiabilité.
- Intégration dans le pipeline Dagster et premières vues marimo.
