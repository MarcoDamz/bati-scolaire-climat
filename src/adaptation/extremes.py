"""Événements extrêmes par niveau de réchauffement : maxima annuels et loi GEV.

Une fenêtre TRACC ne contient que 20 ans par simulation, trop peu pour estimer seul un événement
centennal. On ajuste donc la GEV sur l'ensemble des maxima annuels des 17 simulations d'un même état
(« super-ensemble », ~340 années), et on mesure l'incertitude entre modèles par un ajustement par chaîne
(médiane et fourchette 10–90 %).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import genextreme

PERIODES_RETOUR = (10, 30, 100, 200)


def maxima_annuels(series: pd.DataFrame, cles: tuple[str, ...] = ("pilote", "variable", "chaine"),
                   fenetre_jours: int = 1) -> pd.DataFrame:
    """Maximum annuel de `valeur` (cumul glissant sur `fenetre_jours`, ex. 5 pour le cumul de pluie sur 5 jours)."""
    df = series.sort_values([*cles, "date"]).copy()
    df["date"] = pd.to_datetime(df["date"])
    if fenetre_jours > 1:
        df["valeur"] = df.groupby(list(cles))["valeur"].transform(lambda s: s.rolling(fenetre_jours).sum())
    df["annee"] = df["date"].dt.year
    return df.groupby([*cles, "annee"])["valeur"].max().rename("maximum").reset_index()


def ajuster_gev(maxima: np.ndarray) -> tuple[float, float, float]:
    """Paramètres (forme, position, échelle) au sens de scipy, par maximum de vraisemblance."""
    x = np.asarray(maxima, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 10:
        raise ValueError("au moins 10 maxima annuels sont nécessaires")
    return genextreme.fit(x)


def niveau_retour(params: tuple[float, float, float], periode: float) -> float:
    c, loc, scale = params
    return float(genextreme.isf(1.0 / periode, c, loc=loc, scale=scale))


def periode_retour(params: tuple[float, float, float], valeur: float) -> float:
    """Période de retour (ans) d'une valeur donnée : sert à dire « la crue centennale d'hier revient tous les N ans »."""
    c, loc, scale = params
    p = float(genextreme.sf(valeur, c, loc=loc, scale=scale))
    return float("inf") if p <= 0 else 1.0 / p


def niveaux_par_etat(maxima: pd.DataFrame, etats: pd.DataFrame,
                     cles: tuple[str, ...] = ("pilote", "variable"),
                     periodes: tuple[int, ...] = PERIODES_RETOUR) -> pd.DataFrame:
    """Niveaux de retour par état TRACC.

    `maxima` : sortie de `maxima_annuels` ; `etats` : sortie de `tracc.periodes` (chaine, etat, debut, fin).
    Renvoie, pour chaque (cles…, etat, periode) : valeur du super-ensemble, médiane et fourchette par chaîne,
    et la période de retour actuelle de l'événement de référence (même période, état « référence »)."""
    m = maxima.merge(etats.assign(a0=etats["debut"].dt.year, a1=etats["fin"].dt.year), on="chaine")
    m = m[(m["annee"] >= m["a0"]) & (m["annee"] <= m["a1"])]
    lignes = []
    for cle, g in m.groupby([*cles, "etat"]):
        *ids, etat = cle
        params = ajuster_gev(g["maximum"].to_numpy())
        par_chaine = {}
        for ch, gc in g.groupby("chaine"):
            try:
                par_chaine[ch] = ajuster_gev(gc["maximum"].to_numpy())
            except (ValueError, RuntimeError):
                continue
        for T in periodes:
            vals = np.array([niveau_retour(p, T) for p in par_chaine.values()]) if par_chaine else np.array([np.nan])
            lignes.append(dict(zip(cles, ids), etat=etat, periode_retour=T, valeur=niveau_retour(params, T),
                               mediane_chaines=float(np.nanmedian(vals)), p10=float(np.nanquantile(vals, 0.1)),
                               p90=float(np.nanquantile(vals, 0.9)), n_chaines=len(par_chaine),
                               gev_forme=params[0], gev_position=params[1], gev_echelle=params[2]))
    out = pd.DataFrame(lignes)
    if out.empty:
        return out
    # Fréquence future de l'événement de référence : « l'événement centennal de 1976-2005 revient tous les N ans ».
    ref = out[out["etat"] == "référence"][[*cles, "periode_retour", "valeur"]].rename(columns={"valeur": "valeur_ref"})
    out = out.merge(ref, on=[*cles, "periode_retour"], how="left")
    out["periode_retour_evenement_ref"] = [
        periode_retour((r.gev_forme, r.gev_position, r.gev_echelle), r.valeur_ref) for r in out.itertuples()]
    return out
