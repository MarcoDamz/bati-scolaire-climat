"""Niveaux de réchauffement de la TRACC appliqués à l'ensemble Explore2 RCP8.5 ADAMONT.

Méthode (Météo-France, rapport TRACC 2024) : pour chaque simulation, chaque niveau de réchauffement
correspond à la fenêtre de 20 ans centrée sur l'année « pivot » où la France hexagonale atteint ce niveau.
Les années pivots sont publiées par Explore2 (DOI 10.57745/DCOQM6), copiées dans `ressources/`.
La référence DRIAS est 1976-2005.

Le calendrier officiel de la TRACC (+2 °C en 2030, +2,7 °C en 2050, +4 °C en 2100) sert d'étiquette
pour l'affichage ; les calculs utilisent les fenêtres propres à chaque simulation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from typing import Callable

import numpy as np
import pandas as pd

REFERENCE = ("1976-01-01", "2005-12-31")


@dataclass(frozen=True)
class Niveau:
    code: str        # suffixe des colonnes Explore2 (RWL-20…)
    libelle: str     # affichage
    annee_tracc: int # horizon du calendrier TRACC


NIVEAUX = (
    Niveau("20", "+2 °C", 2030),
    Niveau("27", "+2,7 °C", 2050),
    Niveau("40", "+4 °C", 2100),
)
ETATS = ("référence",) + tuple(n.libelle for n in NIVEAUX)


def charger_pivots() -> pd.DataFrame:
    """Une ligne par chaîne de simulation (17), avec les bornes de chaque fenêtre."""
    with resources.files("adaptation.ressources").joinpath("annees_pivots_tracc_explore2.csv").open() as f:
        df = pd.read_csv(f)
    df = df[(df["EXP"] == "rcp85") & (df["BC"] == "ADAMONT")].copy()
    df["chaine"] = df["GCM"] + "_" + df["RCM"]
    return df.reset_index(drop=True)


def periodes(pivots: pd.DataFrame | None = None) -> pd.DataFrame:
    """Table longue : chaine, etat, debut, fin (référence commune + 3 fenêtres propres à chaque chaîne)."""
    p = charger_pivots() if pivots is None else pivots
    lignes = []
    for _, r in p.iterrows():
        lignes.append((r["chaine"], "référence", pd.Timestamp(REFERENCE[0]), pd.Timestamp(REFERENCE[1])))
        for n in NIVEAUX:
            lignes.append((r["chaine"], n.libelle, pd.Timestamp(r[f"start_RWL-{n.code}"]),
                           pd.Timestamp(r[f"end_RWL-{n.code}"])))
    return pd.DataFrame(lignes, columns=["chaine", "etat", "debut", "fin"])


def chaine_du_fichier(nom_fichier: str, pivots: pd.DataFrame | None = None) -> str | None:
    """Reconnaît la chaîne d'un fichier DRIAS (ex. tasmaxAdjust_France_CNRM-CERFACS-CNRM-CM5_rcp85_..._CNRM-ALADIN63_...)."""
    p = charger_pivots() if pivots is None else pivots
    for _, r in p.iterrows():
        for col in ("regexp_simulation_DRIAS", "regexp_indicateur_DRIAS", "regexp"):
            if re.search(r[col], nom_fichier):
                return r["chaine"]
    return None


def par_etat(series: pd.DataFrame, agregat: Callable[[pd.Series], float] = np.mean,
             cles: tuple[str, ...] = ("pilote", "variable"), pivots: pd.DataFrame | None = None) -> pd.DataFrame:
    """Agrège des séries journalières (colonnes : chaine, date, valeur + `cles`) par état TRACC.

    `agregat` reçoit les valeurs de la fenêtre (ex. moyenne, nombre de jours > seuil / 20 ans…).
    Renvoie une ligne par (cles…, chaine, etat)."""
    per = periodes(pivots)
    df = series.copy()
    df["date"] = pd.to_datetime(df["date"])
    sorties = []
    for (chaine, etat, debut, fin) in per.itertuples(index=False):
        fen = df[(df["chaine"] == chaine) & (df["date"] >= debut) & (df["date"] <= fin)]
        if fen.empty:
            continue
        g = fen.groupby(list(cles))["valeur"].apply(agregat).rename("valeur").reset_index()
        g["chaine"], g["etat"] = chaine, etat
        sorties.append(g)
    if not sorties:
        return pd.DataFrame(columns=[*cles, "chaine", "etat", "valeur"])
    return pd.concat(sorties, ignore_index=True)


def synthese_ensemble(par_chaine: pd.DataFrame, cles: tuple[str, ...] = ("pilote", "variable")) -> pd.DataFrame:
    """Médiane et fourchette (10e–90e centiles) de l'ensemble, et écart à la référence de chaque chaîne."""
    df = par_chaine.copy()
    ref = df[df["etat"] == "référence"][[*cles, "chaine", "valeur"]].rename(columns={"valeur": "ref"})
    df = df.merge(ref, on=[*cles, "chaine"], how="left")
    df["ecart"] = df["valeur"] - df["ref"]
    g = df.groupby([*cles, "etat"])
    out = g.agg(mediane=("valeur", "median"), p10=("valeur", lambda s: s.quantile(0.1)),
                p90=("valeur", lambda s: s.quantile(0.9)), ecart_median=("ecart", "median"),
                ecart_p10=("ecart", lambda s: s.quantile(0.1)), ecart_p90=("ecart", lambda s: s.quantile(0.9)),
                n_chaines=("chaine", "nunique")).reset_index()
    out["etat"] = pd.Categorical(out["etat"], categories=ETATS, ordered=True)
    return out.sort_values([*cles, "etat"]).reset_index(drop=True)
