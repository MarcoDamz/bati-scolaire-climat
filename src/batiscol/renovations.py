"""Historique des rénovations.

Pilote : jeu de données « Opérations de construction et de rénovation dans les lycées
franciliens » (Région Île-de-France, data.gouv.fr). Le schéma exact du fichier n'est pas
figé ici : les colonnes utiles (code UAI, année, nature de l'opération) sont détectées
automatiquement et peuvent être forcées via `colonnes=`.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import requests

DATAGOUV_DATASET_IDF = "operations-de-construction-et-de-renovation-dans-les-lycees-francilens"
DATAGOUV_API = "https://www.data.gouv.fr/api/1/datasets/{slug}/"

UAI_REGEX = re.compile(r"^\d{7}[A-Z]$")
ANNEE_REGEX = re.compile(r"(?:19|20)\d{2}")
MOTS_ANNEE = ("livraison", "fin", "annee", "année", "date", "achevement", "achèvement")
MOTS_NATURE = ("nature", "type", "operation", "opération", "libelle", "libellé", "objet")


def telecharger_datagouv(slug: str = DATAGOUV_DATASET_IDF, timeout: int = 120) -> pd.DataFrame:
    """Télécharge la première ressource CSV ou JSON d'un jeu de données data.gouv.fr."""
    meta = requests.get(DATAGOUV_API.format(slug=slug), timeout=timeout)
    meta.raise_for_status()
    ressources = meta.json().get("resources", [])
    for fmt in ("csv", "json"):
        for res in ressources:
            if (res.get("format") or "").lower() == fmt:
                contenu = requests.get(res["url"], timeout=timeout)
                contenu.raise_for_status()
                if fmt == "csv":
                    return pd.read_csv(io.BytesIO(contenu.content), sep=None, engine="python", dtype=str)
                return pd.json_normalize(contenu.json())
    raise RuntimeError(f"Aucune ressource CSV/JSON dans {slug} : {[r.get('format') for r in ressources]}")


def _sans_accents(texte: str) -> str:
    return texte.lower().translate(str.maketrans("éèêàâîôûç", "eeeaaiouc"))


def detecter_colonne_uai(df: pd.DataFrame) -> str:
    for col in df.columns:
        valeurs = df[col].dropna().astype(str).str.upper().str.strip()
        if len(valeurs) and valeurs.str.match(UAI_REGEX).mean() > 0.5:
            return col
    raise ValueError(f"Aucune colonne de code UAI détectée parmi {list(df.columns)}")


def detecter_colonnes_annee(df: pd.DataFrame) -> list[str]:
    mots = tuple(_sans_accents(m) for m in MOTS_ANNEE)
    cols = [c for c in df.columns if any(m in _sans_accents(str(c)) for m in mots)]
    return [c for c in cols if df[c].dropna().astype(str).str.contains(ANNEE_REGEX).mean() > 0.5]


def detecter_colonne_nature(df: pd.DataFrame, exclues: list[str]) -> str | None:
    mots = tuple(_sans_accents(m) for m in MOTS_NATURE)
    for col in df.columns:
        if col not in exclues and any(m in _sans_accents(str(col)) for m in mots):
            return col
    return None


def _annee(valeur) -> float:
    if pd.isna(valeur):
        return float("nan")
    m = re.search(r"(?:19|20)\d{2}", str(valeur))
    return float(m.group(0)) if m else float("nan")


def normaliser(brut: pd.DataFrame, colonnes: dict[str, str] | None = None) -> pd.DataFrame:
    """Une ligne par UAI : année de la dernière opération connue, nombre d'opérations, libellé."""
    colonnes = colonnes or {}
    col_uai = colonnes.get("uai") or detecter_colonne_uai(brut)
    cols_annee = [colonnes["annee"]] if "annee" in colonnes else detecter_colonnes_annee(brut)
    if not cols_annee:
        raise ValueError(f"Aucune colonne d'année détectée parmi {list(brut.columns)}")
    col_nature = colonnes.get("nature") or detecter_colonne_nature(brut, [col_uai, *cols_annee])

    df = pd.DataFrame({"uai": brut[col_uai].astype(str).str.upper().str.strip()})
    df["annee"] = brut[cols_annee].apply(lambda s: s.map(_annee)).max(axis=1)
    df["nature"] = brut[col_nature] if col_nature else None
    df = df[df["uai"].str.match(UAI_REGEX)].sort_values("annee")

    agg = df.groupby("uai").agg(
        derniere_operation_annee=("annee", "max"),
        nb_operations=("annee", "size"),
        derniere_operation_libelle=("nature", "last"),
    )
    return agg.reset_index()


def charger_renovations(chemin: str | Path | None = None, **kwargs) -> pd.DataFrame:
    if chemin is not None:
        brut = pd.read_csv(chemin, sep=None, engine="python", dtype=str)
    else:
        brut = telecharger_datagouv()
    return normaliser(brut, **kwargs)
