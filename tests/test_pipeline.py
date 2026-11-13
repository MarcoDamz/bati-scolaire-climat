"""Tests hors-ligne : sources de données en fichiers locaux, modèle d'aléas simulé."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from batiscol import renovations, scoring
from batiscol.etablissements import normaliser as normaliser_etab


def annuaire_brut() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "identifiant_de_l_etablissement": ["0750001A", "0750002B", "0930003C", "0750004D", "0750005E"],
            "nom_etablissement": ["Lycée A", "Collège B", "Lycée C", "École D", "Lycée privé E"],
            "type_etablissement": ["Lycée", "Collège", "Lycée", "Ecole", "Lycée"],
            "statut_public_prive": ["Public", "Public", "Public", "Public", "Privé"],
            "code_region": ["11", "11", "11", "11", "11"],
            "libelle_region": ["Île-de-France"] * 5,
            "code_departement": ["075", "075", "093", "075", "075"],
            "libelle_departement": ["Paris", "Paris", "Seine-Saint-Denis", "Paris", "Paris"],
            "nom_commune": ["Paris", "Paris", "Saint-Denis", "Paris", "Paris"],
            "latitude": ["48.85", "48.86", "48.93", "48.84", "48.80"],
            "longitude": ["2.35", "2.36", "2.36", "2.30", "2.30"],
        }
    )


def renov_brut() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Code UAI": ["0750001A", "0750001A", "0930003C"],
            "Nature de l'opération": ["Restructuration", "Rénovation énergétique", "Toiture"],
            "Date de livraison": ["2004", "2018-09-01", "1995"],
        }
    )


class FakeHazardModel:
    """Chaleur : plus de jours dans le futur et pour le 0930003C ; inondation au 0930003C."""

    def get_hazard_data(self, requests):
        out = {}
        for r in requests:
            nord = r.latitude > 48.9
            if r.hazard_type.__name__ == "ChronicHeat":
                seuil = int(r.indicator_id.split("/")[-1].rstrip("c"))
                base = (40 if seuil == 25 else 8) + (10 if nord else 0)
                out[r] = SimpleNamespace(parameters=np.array([base * (1 if r.scenario == "historical" else 1.8)]))
            else:
                prof = 0.8 if nord else 0.0
                out[r] = SimpleNamespace(return_periods=np.array([10, 50, 100, 500]),
                                         intensities=np.array([0, prof / 2, prof, prof * 1.5]))
        return out


def test_normaliser_etablissements_filtre_public_college_lycee():
    df = normaliser_etab(annuaire_brut(), region_code="11")
    assert set(df["uai"]) == {"0750001A", "0750002B", "0930003C"}
    assert df["latitude"].dtype == float


def test_renovations_detection_automatique():
    df = renovations.normaliser(renov_brut())
    lignes = df.set_index("uai")
    assert lignes.loc["0750001A", "derniere_operation_annee"] == 2018
    assert lignes.loc["0750001A", "nb_operations"] == 2
    assert lignes.loc["0750001A", "derniere_operation_libelle"] == "Rénovation énergétique"
    assert lignes.loc["0930003C", "derniere_operation_annee"] == 1995


def test_vulnerabilite_par_anciennete():
    p = scoring.ParametresScore()
    v = scoring.vulnerabilite(pd.Series([2020, 2000, 1980, np.nan]), p)
    assert list(v) == [0.3, 0.6, 1.0, 1.0]


def test_pipeline_dagster_bout_en_bout(tmp_path):
    pytest.importorskip("physrisk")
    dg = pytest.importorskip("dagster")
    from batiscol import definitions as d

    class FakeModeleAleas(d.ModeleAleas):
        def get(self):
            return FakeHazardModel()

    etab_csv, renov_csv, sortie = tmp_path / "etab.csv", tmp_path / "renov.csv", tmp_path / "res.parquet"
    annuaire_brut().to_csv(etab_csv, sep=";", index=False)
    renov_brut().to_csv(renov_csv, sep=";", index=False)

    resultat = dg.materialize(
        d.ASSETS + [d.aleas_completes],
        resources={
            "parametres": d.Parametres(region="11", etablissements_csv=str(etab_csv),
                                       renovations_csv=str(renov_csv), sortie=str(sortie)),
            "modele_aleas": FakeModeleAleas(),
            "hf": d.HuggingFace(),
        },
    )
    assert resultat.success
    assert all(c.passed for c in resultat.get_asset_check_evaluations())

    df = pd.read_parquet(sortie)
    assert len(df) == 3
    assert df.iloc[0]["uai"] == "0930003C"  # plus chaud, inondable, rénové en 1995
    ligne = df.set_index("uai").loc["0930003C"]
    assert ligne["inondation_m_rp100_futur"] == pytest.approx(0.8)
    assert ligne["jours_tmoy_sup_25c_delta"] == pytest.approx(50 * 0.8)
    assert df.set_index("uai").loc["0750002B", "donnees_renovation"] == "inconnues"
    assert df["score"].between(0, 100).all()
    assert df["scenario_chaleur"].iloc[0] == "ssp245 2050"
