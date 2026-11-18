# Bâti scolaire et risques climatiques

[![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/MarcoDamz/bati-scolaire-climat/blob/main/demo.py)

Tableau de bord : https://marcodamz.github.io/bati-scolaire-climat/

Croise l'exposition des collèges et lycées publics français aux aléas climatiques
(chaleur chronique, inondation fluviale), calculée avec
[physrisk-lib](https://github.com/os-climate/physrisk) (OS-Climate / FINOS), avec
l'historique connu des rénovations, pour repérer les établissements où le changement
climatique va aggraver un bâti peu ou pas rénové.

> ⚠️ Ce projet mesure une **exposition climatique pondérée par l'ancienneté des travaux**.
> Il ne mesure pas l'état réel des bâtiments (sanitaires, toitures, moisissures…), qui
> n'est pas disponible en données ouvertes.

## Démonstrateur « adaptation climatique des collectivités » (en cours)

Impacts du changement climatique sur le patrimoine bâti de 5 communes pilotes (L'Aiguillon-la-Presqu'île,
Lacanau, Landiras, Gonfaron, Carcassonne), selon la TRACC (Explore2 RCP8.5 par niveaux de réchauffement).

| Où | Quoi |
|---|---|
| **GitHub** (ce dépôt) | Tout le code : `src/adaptation/` (TRACC, extrêmes, crues, tempêtes), `phase0/`, `phase1/`, `notebooks/`, la démo marimo |
| **Google Drive** `SaaS adaptation climatique/demo/donnees/` | Toutes les données récupérées et calculées (`instances_demo/`, `phase0/`, `phase1/`, `explore2/`) |
| **Google Colab** | Exécution des scripts longs, qui écrivent directement dans le Drive |
| **molab** | Démo marimo interactive, ouverte depuis le bouton du README |

Notebooks Colab :

| Notebook | Rôle |
|---|---|
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/MarcoDamz/bati-scolaire-climat/blob/claude/enrich-demo-instances-oncka4/notebooks/01_extraction_explore2.ipynb) `notebooks/01_extraction_explore2.ipynb` | Projections climatiques journalières Explore2-ADAMONT aux bâtiments pilotes → `donnees/explore2/` |

Notes de travail : `docs/phase0_faisabilite.md`, `docs/phase1_climat.md`.

## Architecture

```
GitHub Actions (workflow « pipeline »)
  Dagster : etablissements ─┐
            renovations ────┴─ etablissements_enrichis ─ aleas ─ scores ─ resultats_parquet
                                                          └ check : aleas_completes
  marimo export html demo.py ─▶ GitHub Pages : index.html (tableau de bord figé) + resultats.parquet
                                                   │
molab (« Open in molab ») : demo.py interactif ◀──┘ lit resultats.parquet publié
```

Deux niveaux de lecture, sans serveur à payer :

- **Tableau de bord** (GitHub Pages) : page statique aux paramètres par défaut. La carte
  reste interactive (zoom, survol) ; les réglages sont figés.
- **Exploration** (molab) : le même notebook, exécuté dans le cloud gratuit de marimo, avec
  les curseurs actifs et le code visible. `demo.py` déclare ses dépendances en en-tête
  (PEP 723), dont `batiscol` installé depuis ce dépôt.

| Asset Dagster | Rôle | Source |
|---|---|---|
| `etablissements` | Collèges et lycées publics géolocalisés | Annuaire de l'éducation (data.education.gouv.fr) |
| `renovations` | Dernière opération de travaux par UAI (optionnel) | Opérations de construction/rénovation des lycées franciliens (data.gouv.fr) — pilote IDF |
| `aleas` | Jours de forte chaleur, crue centennale | physrisk-lib : `days_tas/above/{25,30}c` (OSC, CMIP6 0,25°) et profondeur de crue TU Delft (Europe, 100 m) |
| `scores` | Indice transparent et paramétrable | `batiscol.scoring` |
| `resultats_parquet` | Fichier lu par le tableau de bord | |
| `publication_hf` | Copie optionnelle sur un dataset Hugging Face (ignorée sans `HF_DATASET_REPO`) | |

La logique métier vit dans des fonctions pures (`batiscol.etablissements`, `renovations`,
`hazards`, `scoring`) ; `batiscol.definitions` ne fait que les orchestrer. La démo marimo
réutilise `batiscol.scoring` pour recalculer le score en direct quand on change les poids.

## Démarrage

```bash
pip install -e ".[pipeline,demo,dev]"
pytest

# Interface Dagster : matérialiser le groupe « bati_scolaire » (paramètres au lancement)
dagster dev -m batiscol.definitions

# Ou en ligne de commande, pilote Île-de-France limité à 50 établissements
dagster asset materialize -m batiscol.definitions --select '*' \
  --config-json '{"resources": {"parametres": {"config": {"region": "11", "limit": 50}}}}'

# Démo
RESULTS_PATH=data/resultats.parquet marimo run demo.py   # ou « marimo edit demo.py »
```

Paramètres de la ressource `parametres` : `region`, `limit`, `scenario_chaleur`
(ssp126/245/585), `annee_chaleur` (2030/2040/2050), `etablissements_csv`, `renovations_csv`
(fichiers locaux si une API est inaccessible), `sortie`.

Les données d'aléas sont lues anonymement sur le bucket S3 public `os-climate-physical-risk`.

## Déploiement

1. Dépôt **public** (requis pour GitHub Pages gratuit et pour l'ouverture dans molab).
2. Settings → Pages → Source : **GitHub Actions**.
3. Actions → **pipeline** → Run workflow.

- `ci.yml` : tests, validation des définitions Dagster, `marimo check`.
- `pipeline.yml` : matérialisation Dagster, export statique du notebook, déploiement Pages.

Optionnel : secret `HF_TOKEN` et variable `HF_DATASET_REPO` pour publier aussi les résultats
sur un dataset Hugging Face.

## Méthode du score (v0)

`score = 100 × vulnérabilité × (w_chaleur × exposition_chaleur + w_inondation × exposition_inondation)`

- **exposition_chaleur** : rang centile, au sein du périmètre, du nombre de jours par an où la
  température moyenne journalière dépasse 25 °C (ou 30 °C).
- **exposition_inondation** : profondeur de crue fluviale non protégée de période de retour
  100 ans, plafonnée à 1 m puis ramenée sur [0, 1].
- **vulnérabilité** : 0,3 si dernière opération ≥ 2010, 0,6 si entre 1990 et 2009, 1,0 si
  antérieure ou inconnue. Les établissements sans donnée de rénovation sont signalés.

Limites : résolution de 0,25° et un seul modèle climatique (ACCESS-CM2) pour la chaleur, pas
d'effet îlot de chaleur, inondation sans prise en compte des protections, données de
rénovation limitées au pilote IDF. Pistes : BDNB (année de construction, DPE), Géorisques
(retrait-gonflement des argiles), DRIAS, marchés publics (DECP) pour étendre l'historique des
travaux aux autres régions, plusieurs modèles climatiques.
