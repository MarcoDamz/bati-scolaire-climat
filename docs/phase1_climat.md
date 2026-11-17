# Phase 1 — Climat par niveau de réchauffement (TRACC)

## Ce qui est en place

| Brique | Fichier | État |
|---|---|---|
| Fenêtres TRACC par simulation (17 chaînes Explore2 RCP8.5 ADAMONT, années pivots officielles), agrégation et synthèse d'ensemble (médiane, 10e–90e centiles, écart à 1976-2005) | `src/adaptation/tracc.py` | ✅ testé |
| Extrêmes : maxima annuels (cumuls sur N jours), loi GEV en super-ensemble (~340 années par niveau) et par chaîne, niveaux de retour 10/30/100/200 ans, fréquence future de l'événement de référence | `src/adaptation/extremes.py` | ✅ testé |
| Crues : variation du débit journalier maximal annuel et de la crue décennale par niveau, aux stations des pilotes | `src/adaptation/hydro.py` → `resultats/phase1/crues_explore2_tracc.csv` | ✅ calculé |
| Extraction des projections journalières Explore2-ADAMONT aux mailles des bâtiments pilotes | `phase1/telecharger_explore2.py` | ✅ testé sur un serveur simulé ; **à lancer sur votre poste** |
| Tempêtes (empreintes C3S) et réanalyse CERRA | — | ⏸ clé Copernicus refusée (voir plus bas) |

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

## À faire de votre côté : extraire les projections journalières (option a)

Le serveur public du CNRM ne répond pas depuis l'environnement cloud, mais il est ouvert sans compte depuis un
poste classique.

1. Installer Python 3.10+ puis :
   `pip install xarray h5netcdf h5py netCDF4 fsspec aiohttp requests pandas pyarrow`
2. Récupérer `phase1/telecharger_explore2.py` (branche `claude/enrich-demo-instances-oncka4`).
3. Vérifier ce qui sera extrait (quelques minutes) :
   `python3 telecharger_explore2.py --lister`
   → affiche le nombre de fichiers par variable et écrit `explore2_fichiers_retenus.csv`.
   Si aucun fichier n'est reconnu, envoyez ce CSV et la sortie du script : l'arborescence du serveur
   aura changé et j'adapterai le filtre.
4. Lancer l'extraction : `python3 telecharger_explore2.py`
   Durée : plusieurs heures. Le script reprend où il s'est arrêté si on le relance.
5. Déposer `explore2_pilotes.parquet` sur Google Drive et me donner son nom : je le lis directement.

Ce que le script extrait : 17 simulations × (historique 1976-2005 + RCP8.5 2006-2100) × variables journalières
corrigées (températures max/min/moyenne, précipitations, vent moyen, humidité relative, humidité des sols SIM2),
uniquement aux mailles de 8 km qui contiennent les 228 bâtiments des pilotes. Les fichiers nationaux ne sont
lus qu'à distance (ou en fichier temporaire supprimé aussitôt).

## Clé Copernicus

La clé saisie est refusée par le Climate Data Store (« Authentication failed »). Vérifier :
- que c'est bien le *Personal Access Token* affiché sur la page de profil de cds.climate.copernicus.eu ;
- que les licences des jeux « Windstorm tracks and footprints » et « CERRA » ont été acceptées
  (onglet *Download* de chaque jeu, en bas de page).

La clé se remplace dans les réglages de l'environnement `bati-scolaire-climat` (secrets réseau,
hôte `cds.climate.copernicus.eu`, en-tête `PRIVATE-TOKEN`).

## Suite de la phase 1, dès réception des données

- Conversion des unités, puis indicateurs par niveau TRACC et par bâtiment : jours > 30/35 °C, nuits tropicales,
  degrés-jours de climatisation, cumuls de pluie 1 j / 5 j et leurs niveaux de retour, sécheresse des sols
  (SWI, pour les argiles), Indice Forêt Météo (feux).
- Tempêtes : rafales de retour 50 ans actuelles (C3S), évolution du vent moyen extrême d'Explore2 affichée
  avec sa faible fiabilité.
- Intégration dans le pipeline Dagster et premières vues marimo.
