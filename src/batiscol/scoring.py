"""Indice d'exposition climatique du bâti scolaire, transparent et paramétrable."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ParametresScore:
    poids_chaleur: float = 0.6
    poids_inondation: float = 0.4
    colonne_chaleur: str = "jours_tmoy_sup_25c_futur"
    colonne_inondation: str = "inondation_m_rp100_futur"
    plafond_inondation_m: float = 1.0
    annee_renovation_recente: int = 2010
    annee_renovation_ancienne: int = 1990
    vuln_recente: float = 0.3
    vuln_intermediaire: float = 0.6
    vuln_ancienne_ou_inconnue: float = 1.0


def vulnerabilite(annee_derniere_operation: pd.Series, p: ParametresScore) -> pd.Series:
    annee = pd.to_numeric(annee_derniere_operation, errors="coerce")
    v = np.where(
        annee >= p.annee_renovation_recente,
        p.vuln_recente,
        np.where(annee >= p.annee_renovation_ancienne, p.vuln_intermediaire, p.vuln_ancienne_ou_inconnue),
    )
    return pd.Series(v, index=annee.index, dtype=float)


def calculer_score(df: pd.DataFrame, p: ParametresScore = ParametresScore()) -> pd.DataFrame:
    sortie = df.copy()
    chaleur = pd.to_numeric(sortie[p.colonne_chaleur], errors="coerce")
    sortie["exposition_chaleur"] = chaleur.rank(pct=True).fillna(0.0)
    inondation = pd.to_numeric(sortie[p.colonne_inondation], errors="coerce").fillna(0.0)
    sortie["exposition_inondation"] = inondation.clip(0, p.plafond_inondation_m) / p.plafond_inondation_m

    annees = sortie["derniere_operation_annee"] if "derniere_operation_annee" in sortie else pd.Series(np.nan, index=sortie.index)
    sortie["donnees_renovation"] = np.where(annees.notna(), "connues", "inconnues")
    sortie["vulnerabilite"] = vulnerabilite(annees, p)

    exposition = p.poids_chaleur * sortie["exposition_chaleur"] + p.poids_inondation * sortie["exposition_inondation"]
    sortie["score"] = (100 * sortie["vulnerabilite"] * exposition).round(1)
    sortie.attrs["parametres_score"] = p.__dict__
    return sortie.sort_values("score", ascending=False).reset_index(drop=True)
