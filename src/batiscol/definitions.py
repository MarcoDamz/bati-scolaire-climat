"""Pipeline Dagster : établissements -> rénovations -> aléas (physrisk-lib) -> score -> publication.

Lancer l'interface : `dagster dev -m batiscol.definitions`
En ligne de commande : `dagster asset materialize -m batiscol.definitions --select '*'`
"""


import os
from pathlib import Path
from typing import Optional

import dagster as dg
import pandas as pd

from .etablissements import charger_etablissements
from .hazards import Scenario, calculer_aleas
from .renovations import charger_renovations
from .scoring import calculer_score

GROUPE = "bati_scolaire"
COLONNES_ALEAS = [
    "jours_tmoy_sup_25c_futur",
    "jours_tmoy_sup_30c_futur",
    "inondation_m_rp100_futur",
]


# --- Ressources -------------------------------------------------------------------------


class Parametres(dg.ConfigurableResource):
    """Périmètre et scénario du calcul (modifiables au lancement)."""

    region: Optional[str] = "11"  # code région INSEE ; None = France entière
    limit: Optional[int] = None
    scenario_chaleur: str = "ssp245"  # ssp126, ssp245, ssp585
    annee_chaleur: int = 2050  # 2030, 2040, 2050
    etablissements_csv: Optional[str] = None  # fichier local au lieu de l'API
    renovations_csv: Optional[str] = None
    sortie: str = "data/resultats.parquet"

    def scenario(self) -> Scenario:
        inondation = "rcp8p5" if self.scenario_chaleur == "ssp585" else "rcp4p5"
        return Scenario(self.scenario_chaleur, self.annee_chaleur, inondation, 2085)


class ModeleAleas(dg.ConfigurableResource):
    """Modèle d'aléas physrisk-lib (Zarr sur le S3 public d'OS-Climate). Surchargé dans les tests."""

    def get(self):
        from physrisk.kernel.calculation import get_default_hazard_model

        return get_default_hazard_model()


class HuggingFace(dg.ConfigurableResource):
    """Dataset Hugging Face de publication. Le jeton est lu dans HF_TOKEN."""

    dataset_repo: Optional[str] = None


# --- Assets -----------------------------------------------------------------------------


@dg.asset(group_name=GROUPE, compute_kind="pandas")
def etablissements(context: dg.AssetExecutionContext, parametres: Parametres) -> pd.DataFrame:
    """Collèges et lycées publics géolocalisés (Annuaire de l'éducation)."""
    df = charger_etablissements(parametres.etablissements_csv, region_code=parametres.region)
    if parametres.limit:
        df = df.head(parametres.limit)
    context.add_output_metadata({"nb": len(df), "par_type": df["type"].value_counts().to_dict()})
    return df


@dg.asset(group_name=GROUPE, compute_kind="pandas")
def renovations(context: dg.AssetExecutionContext, parametres: Parametres) -> pd.DataFrame:
    """Dernière opération de travaux connue par établissement (pilote Île-de-France).

    Source optionnelle : en cas d'échec, table vide et vulnérabilité par défaut en aval.
    """
    try:
        df = charger_renovations(parametres.renovations_csv)
        statut = "ok"
    except Exception as err:  # noqa: BLE001
        context.log.warning(f"Rénovations non chargées : {err}")
        df = pd.DataFrame(columns=["uai", "derniere_operation_annee", "nb_operations", "derniere_operation_libelle"])
        statut = f"indisponible : {err}"[:200]
    context.add_output_metadata({"nb": len(df), "statut": statut})
    return df


@dg.asset(group_name=GROUPE, compute_kind="pandas")
def etablissements_enrichis(
    context: dg.AssetExecutionContext, etablissements: pd.DataFrame, renovations: pd.DataFrame
) -> pd.DataFrame:
    df = etablissements.merge(renovations, on="uai", how="left")
    context.add_output_metadata(
        {"nb": len(df), "avec_renovation": int(df["derniere_operation_annee"].notna().sum())}
    )
    return df


@dg.asset(group_name=GROUPE, compute_kind="physrisk")
def aleas(
    context: dg.AssetExecutionContext,
    etablissements_enrichis: pd.DataFrame,
    parametres: Parametres,
    modele_aleas: ModeleAleas,
) -> pd.DataFrame:
    """Jours de forte chaleur et profondeur de crue centennale, historiques et futurs."""
    scen = parametres.scenario()
    df = calculer_aleas(etablissements_enrichis, scen, hazard_model=modele_aleas.get())
    df.attrs = {}
    context.add_output_metadata(
        {"scenario": str(scen), **{f"manquants_{c}": int(df[c].isna().sum()) for c in COLONNES_ALEAS}}
    )
    return df


@dg.asset_check(asset=aleas, description="Moins de 20 % de valeurs d'aléas manquantes")
def aleas_completes(aleas: pd.DataFrame) -> dg.AssetCheckResult:
    taux = {c: float(aleas[c].isna().mean()) for c in COLONNES_ALEAS}
    return dg.AssetCheckResult(passed=max(taux.values(), default=0) < 0.2, metadata=taux)


@dg.asset(group_name=GROUPE, compute_kind="pandas")
def scores(context: dg.AssetExecutionContext, aleas: pd.DataFrame) -> pd.DataFrame:
    df = calculer_score(aleas)
    df.attrs = {}
    lignes = "\n".join(f"| {r.nom} | {r.commune} | {r.score} |" for r in df.head(10).itertuples())
    context.add_output_metadata(
        {
            "score_median": float(df["score"].median()),
            "top10": dg.MetadataValue.md(f"| Établissement | Commune | Score |\n|---|---|---|\n{lignes}"),
        }
    )
    return df


@dg.asset(group_name=GROUPE, compute_kind="parquet")
def resultats_parquet(scores: pd.DataFrame, parametres: Parametres) -> dg.MaterializeResult:
    """Fichier lu par la démo marimo."""
    scen = parametres.scenario()
    sortie = Path(parametres.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    scores.assign(
        scenario_chaleur=f"{scen.chaleur_scenario} {scen.chaleur_annee}",
        scenario_inondation=f"{scen.inondation_scenario} {scen.inondation_annee}",
    ).to_parquet(sortie, index=False)
    return dg.MaterializeResult(metadata={"chemin": str(sortie.resolve()), "nb": len(scores)})


@dg.asset(group_name=GROUPE, deps=[resultats_parquet], compute_kind="huggingface")
def publication_hf(context: dg.AssetExecutionContext, parametres: Parametres, hf: HuggingFace) -> dg.MaterializeResult:
    """Publie resultats.parquet sur le dataset Hugging Face (ignoré si non configuré)."""
    if not hf.dataset_repo:
        context.log.info("HF_DATASET_REPO non défini : publication ignorée")
        return dg.MaterializeResult(metadata={"publie": False})
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(hf.dataset_repo, repo_type="dataset", exist_ok=True)
    api.upload_file(path_or_fileobj=parametres.sortie, path_in_repo="resultats.parquet",
                    repo_id=hf.dataset_repo, repo_type="dataset")
    return dg.MaterializeResult(metadata={"publie": True, "dataset": hf.dataset_repo})


ASSETS = [etablissements, renovations, etablissements_enrichis, aleas, scores, resultats_parquet, publication_hf]

pipeline_complet = dg.define_asset_job("pipeline_complet", selection=dg.AssetSelection.groups(GROUPE))

defs = dg.Definitions(
    assets=ASSETS,
    asset_checks=[aleas_completes],
    jobs=[pipeline_complet],
    resources={
        "parametres": Parametres.configure_at_launch(),
        "modele_aleas": ModeleAleas(),
        "hf": HuggingFace(dataset_repo=os.getenv("HF_DATASET_REPO")),
    },
)
