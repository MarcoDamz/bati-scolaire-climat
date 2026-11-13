---
title: Bâti scolaire et risques climatiques
emoji: 🏫
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Exposition des collèges et lycées publics aux aléas climatiques
---

# Bâti scolaire et risques climatiques

Croise l'exposition des collèges et lycées publics français aux aléas climatiques
(chaleur chronique, inondation fluviale), calculée avec
[physrisk-lib](https://github.com/os-climate/physrisk) (OS-Climate / FINOS), avec
l'historique connu des rénovations, pour repérer les établissements où le changement
climatique va aggraver un bâti peu ou pas rénové.

> ⚠️ Ce projet mesure une **exposition climatique pondérée par l'ancienneté des travaux**.
> Il ne mesure pas l'état réel des bâtiments (sanitaires, toitures, moisissures…), qui
> n'est pas disponible en données ouvertes.

## Architecture

```
Pipeline Dagster (local ou GitHub Actions)              Space Hugging Face (Docker)
etablissements ─┐                                        demo.py (marimo run)
renovations ────┴─ etablissements_enrichis ─ aleas ─ scores ─ resultats_parquet ─ publication_hf ─▶ Dataset HF ─▶ lu par la démo
                                              └ check : aleas_completes
```

| Asset Dagster | Rôle | Source |
|---|---|---|
| `etablissements` | Collèges et lycées publics géolocalisés | Annuaire de l'éducation (data.education.gouv.fr) |
| `renovations` | Dernière opération de travaux par UAI (optionnel) | Opérations de construction/rénovation des lycées franciliens (data.gouv.fr) — pilote IDF |
| `aleas` | Jours de forte chaleur, crue centennale | physrisk-lib : `days_tas/above/{25,30}c` (OSC, CMIP6 0,25°) et profondeur de crue TU Delft (Europe, 100 m) |
| `scores` | Indice transparent et paramétrable | `batiscol.scoring` |
| `resultats_parquet` / `publication_hf` | Fichier lu par la démo, publié sur un dataset HF | |

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

Dans GitHub (Settings → Secrets and variables → Actions) : secret `HF_TOKEN` (jeton en
écriture), variables `HF_SPACE_REPO` (ex. `utilisateur/bati-scolaire-climat`) et
`HF_DATASET_REPO` (ex. `utilisateur/bati-scolaire-climat-data`). Dans le Space : variable
`HF_DATASET_REPO`.

- `ci.yml` : tests, validation des définitions Dagster, `marimo check`.
- `sync-hf-space.yml` : pousse le dépôt sur le Space (SDK Docker) à chaque push sur `main`.
- `pipeline.yml` : matérialisation Dagster à la demande, publication sur le dataset.

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
