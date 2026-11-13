"""Référentiel des établissements : Annuaire de l'éducation (data.education.gouv.fr)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

ANNUAIRE_EXPORT_URL = (
    "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "fr-en-annuaire-education/exports/csv"
)
TYPES_RETENUS = ("Collège", "Lycée")

# Colonnes de l'export Opendatasoft -> noms internes
COLONNES = {
    "identifiant_de_l_etablissement": "uai",
    "nom_etablissement": "nom",
    "type_etablissement": "type",
    "statut_public_prive": "statut",
    "code_region": "region_code",
    "libelle_region": "region",
    "code_departement": "departement_code",
    "libelle_departement": "departement",
    "nom_commune": "commune",
    "latitude": "latitude",
    "longitude": "longitude",
}


def telecharger_annuaire(timeout: int = 120) -> pd.DataFrame:
    """Télécharge les collèges et lycées publics depuis l'API Opendatasoft."""
    where = " OR ".join(f'type_etablissement="{t}"' for t in TYPES_RETENUS)
    params = {"delimiter": ";", "where": f'({where}) AND statut_public_prive="Public"'}
    resp = requests.get(ANNUAIRE_EXPORT_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return pd.read_csv(io.BytesIO(resp.content), sep=";", dtype=str)


def normaliser(brut: pd.DataFrame, region_code: str | None = None) -> pd.DataFrame:
    """Garde les collèges et lycées publics géolocalisés, avec des noms de colonnes stables."""
    manquantes = [c for c in COLONNES if c not in brut.columns]
    if manquantes:
        raise ValueError(
            f"Colonnes absentes de l'annuaire : {manquantes}. Colonnes reçues : {list(brut.columns)}"
        )
    df = brut[list(COLONNES)].rename(columns=COLONNES)
    df = df[df["type"].isin(TYPES_RETENUS) & (df["statut"] == "Public")]
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])
    df["region_code"] = df["region_code"].astype(str).str.zfill(2)
    if region_code is not None:
        df = df[df["region_code"] == str(region_code).zfill(2)]
    df["uai"] = df["uai"].str.upper().str.strip()
    return df.drop_duplicates("uai").drop(columns="statut").reset_index(drop=True)


def charger_etablissements(
    chemin_csv: str | Path | None = None, region_code: str | None = None
) -> pd.DataFrame:
    """Charge l'annuaire depuis un fichier local (export CSV `;`) ou depuis l'API."""
    brut = (
        pd.read_csv(chemin_csv, sep=";", dtype=str)
        if chemin_csv is not None
        else telecharger_annuaire()
    )
    return normaliser(brut, region_code)
