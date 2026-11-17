"""Tests du démonstrateur adaptation : niveaux TRACC et extrêmes, sur données synthétiques."""

import numpy as np
import pandas as pd
import pytest

from adaptation import extremes, tracc


def test_pivots_17_chaines_et_fenetres_de_20_ans():
    p = tracc.charger_pivots()
    assert len(p) == 17 and p["chaine"].is_unique
    per = tracc.periodes(p)
    assert set(per["etat"]) == set(tracc.ETATS)
    futur = per[per["etat"] != "référence"]
    duree = (futur["fin"] - futur["debut"]).dt.days / 365.25
    assert duree.between(19.9, 20.1).all()
    # les niveaux se suivent dans le temps pour chaque chaîne
    for _, g in futur.groupby("chaine"):
        assert g.sort_values("debut")["etat"].tolist() == ["+2 °C", "+2,7 °C", "+4 °C"]


def test_chaine_du_fichier_drias():
    nom = ("tasmaxAdjust_France_CNRM-CERFACS-CNRM-CM5_rcp85_r1i1p1_CNRM-ALADIN63_v2_"
           "MF-ADAMONT-SAFRAN-1980-2011_day_20060101-21001231.nc")
    assert tracc.chaine_du_fichier(nom) == "CNRM-CM5_ALADIN63"
    assert tracc.chaine_du_fichier("sans_rapport.nc") is None


def _series_tendance(p, pente_par_an=0.04):
    """Température journalière : 15 °C en 1990 + tendance linéaire, identique pour toutes les chaînes."""
    dates = pd.date_range("1976-01-01", "2100-12-31", freq="D")
    annees = dates.year + dates.dayofyear / 366
    lignes = []
    for ch in p["chaine"]:
        lignes.append(pd.DataFrame({"chaine": ch, "date": dates, "pilote": "X", "variable": "tas",
                                    "valeur": 15 + pente_par_an * (annees - 1990)}))
    return pd.concat(lignes, ignore_index=True)


def test_par_etat_et_synthese_suivent_la_tendance():
    p = tracc.charger_pivots()
    s = _series_tendance(p)
    par_ch = tracc.par_etat(s, pivots=p)
    syn = tracc.synthese_ensemble(par_ch)
    ref = syn[syn["etat"] == "référence"].iloc[0]
    assert ref["mediane"] == pytest.approx(15.0, abs=0.05)  # milieu de 1976-2005 ≈ 1991
    med = syn.set_index("etat")["ecart_median"]
    assert 0 < med["+2 °C"] < med["+2,7 °C"] < med["+4 °C"]
    # écart à +4 °C ≈ 0,04 × (année pivot médiane 2074 − 1991)
    assert med["+4 °C"] == pytest.approx(0.04 * (2074 - 1990.5), abs=0.4)
    assert (syn["n_chaines"] == 17).all()


def test_gev_retrouve_les_niveaux_de_retour():
    vrai = (-0.1, 50.0, 10.0)  # forme, position, échelle (Fréchet léger, typique des pluies)
    rng = np.random.default_rng(0)
    from scipy.stats import genextreme
    x = genextreme.rvs(*vrai, size=3000, random_state=rng)
    est = extremes.ajuster_gev(x)
    for T in (10, 100):
        assert extremes.niveau_retour(est, T) == pytest.approx(extremes.niveau_retour(vrai, T), rel=0.05)
    v100 = extremes.niveau_retour(vrai, 100)
    assert extremes.periode_retour(vrai, v100) == pytest.approx(100, rel=1e-6)


def test_niveaux_par_etat_plus_intenses_et_plus_frequents():
    """Pluie journalière synthétique dont l'intensité croît avec le temps : l'événement centennal
    de référence doit devenir plus fréquent aux niveaux de réchauffement élevés."""
    p = tracc.charger_pivots()
    rng = np.random.default_rng(1)
    dates = pd.date_range("1976-01-01", "2100-12-31", freq="D")
    facteur = 1 + 0.004 * np.clip(dates.year - 1990, 0, None)  # +0,4 %/an
    lignes = []
    for ch in p["chaine"]:
        pluie = rng.gamma(0.6, 6.0, size=len(dates)) * facteur
        lignes.append(pd.DataFrame({"chaine": ch, "date": dates, "pilote": "X", "variable": "pr", "valeur": pluie}))
    s = pd.concat(lignes, ignore_index=True)
    m = extremes.maxima_annuels(s)
    out = extremes.niveaux_par_etat(m, tracc.periodes(p), periodes=(100,))
    r = out.set_index("etat")
    assert r.loc["référence", "periode_retour_evenement_ref"] == pytest.approx(100, rel=1e-6)
    assert r.loc["+4 °C", "valeur"] > r.loc["+2 °C", "valeur"] > r.loc["référence", "valeur"]
    assert r.loc["+4 °C", "periode_retour_evenement_ref"] < 50
    assert (r["p10"] <= r["p90"]).all()


def test_maxima_cumul_sur_5_jours():
    s = pd.DataFrame({"chaine": "c", "pilote": "X", "variable": "pr",
                      "date": pd.date_range("2000-01-01", periods=10, freq="D"), "valeur": [0, 0, 10, 10, 10, 10, 10, 0, 0, 0]})
    m = extremes.maxima_annuels(s, fenetre_jours=5)
    assert m["maximum"].iloc[0] == 50
