"""Indicateurs d'aléas aux points des établissements, via physrisk-lib.

On interroge directement le modèle d'aléas de physrisk-lib (indicateurs bruts) plutôt que
les modèles de dommage : pour des écoles, « combien de jours de forte chaleur » et
« quelle hauteur d'eau » sont plus parlants qu'un pourcentage de perte de valeur.

Indicateurs utilisés (inventaire physrisk-lib 1.11) :
- ChronicHeat `days_tas/above/{25,30}c` : jours/an où la température moyenne journalière
  dépasse le seuil (OSC, CMIP6, 0,25°). Historique 2005 ; SSP126/245/585 en 2030/2040/2050.
- RiverineInundation `flood_depth`, ressource TU Delft (Europe, 100 m, sans protection).
  Historique 1985 ; RCP4.5/8.5 en 2035/2085.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SEUILS_CHALEUR = (25, 30)
CHEMIN_INONDATION_TUDELFT = "inundation/river_tudelft/v2/flood_depth_unprot_{scenario}_{year}"
PERIODE_RETOUR_INONDATION = 100


@dataclass(frozen=True)
class Scenario:
    chaleur_scenario: str = "ssp245"
    chaleur_annee: int = 2050
    inondation_scenario: str = "rcp4p5"
    inondation_annee: int = 2085


def _profondeur_periode_retour(resp, periode: int) -> float:
    rp = np.asarray(getattr(resp, "return_periods", []), dtype=float)
    val = np.asarray(getattr(resp, "intensities", []), dtype=float)
    if rp.size == 0:
        return float("nan")
    ordre = np.argsort(rp)
    return float(np.interp(periode, rp[ordre], val[ordre]))


def _parametre(resp) -> float:
    params = np.asarray(getattr(resp, "parameters", []), dtype=float).ravel()
    return float(params[0]) if params.size else float("nan")


def calculer_aleas(
    etablissements: pd.DataFrame,
    scenario: Scenario = Scenario(),
    hazard_model=None,
) -> pd.DataFrame:
    """Ajoute aux établissements les colonnes d'aléas, historiques et futures.

    `hazard_model` permet d'injecter un modèle (tests, données locales). Par défaut :
    le modèle Zarr de physrisk-lib, qui lit le bucket S3 public d'OS-Climate.
    """
    from physrisk.data.hazard_data_provider import HazardDataHint
    from physrisk.kernel.hazard_model import HazardDataRequest
    from physrisk.kernel.hazards import ChronicHeat, RiverineInundation

    if hazard_model is None:
        from physrisk.kernel.calculation import get_default_hazard_model

        hazard_model = get_default_hazard_model()

    hint_inondation = HazardDataHint(path=CHEMIN_INONDATION_TUDELFT)
    demandes: dict[tuple[int, str], object] = {}
    for i, row in etablissements.iterrows():
        lon, lat = float(row["longitude"]), float(row["latitude"])
        for seuil in SEUILS_CHALEUR:
            for nom, scen, annee in (
                ("hist", "historical", 2005),
                ("futur", scenario.chaleur_scenario, scenario.chaleur_annee),
            ):
                demandes[(i, f"jours_tmoy_sup_{seuil}c_{nom}")] = HazardDataRequest(
                    ChronicHeat, lon, lat,
                    indicator_id=f"days_tas/above/{seuil}c", scenario=scen, year=annee,
                )
        for nom, scen, annee in (
            ("hist", "historical", 1985),
            ("futur", scenario.inondation_scenario, scenario.inondation_annee),
        ):
            demandes[(i, f"inondation_m_rp{PERIODE_RETOUR_INONDATION}_{nom}")] = HazardDataRequest(
                RiverineInundation, lon, lat,
                indicator_id="flood_depth", scenario=scen, year=annee, hint=hint_inondation,
            )

    reponses = hazard_model.get_hazard_data(list(demandes.values()))

    sortie = etablissements.copy()
    for (i, colonne), req in demandes.items():
        resp = reponses.get(req)
        if colonne.startswith("inondation"):
            valeur = _profondeur_periode_retour(resp, PERIODE_RETOUR_INONDATION)
        else:
            valeur = _parametre(resp)
        sortie.loc[i, colonne] = valeur

    for seuil in SEUILS_CHALEUR:
        base = f"jours_tmoy_sup_{seuil}c"
        sortie[f"{base}_delta"] = sortie[f"{base}_futur"] - sortie[f"{base}_hist"]
    sortie.attrs["scenario"] = scenario.__dict__
    return sortie
