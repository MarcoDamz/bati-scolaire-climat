"""Évolution des crues par niveau de réchauffement TRACC, d'après les projections hydrologiques Explore2.

Source : « Ensemble des indicateurs des changements par niveaux de réchauffement TRACC issus des projections
hydrologiques Explore2 (référence 1991-2020) », DOI 10.57745/W0KO1G (Recherche Data Gouv, licence ouverte).
Indicateurs : variation (%) du débit journalier maximal annuel (QJXA) et de sa valeur décennale (QJXA-10),
pour chaque chaîne climat × modèle hydrologique (ensemble RCP8.5 ADAMONT, chaînes aberrantes filtrées).

Attention : la référence de ces indicateurs est 1991-2020 (et non 1976-2005 comme les données DRIAS).
"""

from __future__ import annotations

import io
import os
import urllib.request

import pandas as pd

ENTREPOT = "https://entrepot.recherche.data.gouv.fr/api/access/datafile/{id}?format=original"
FICHIERS = {  # identifiants des fichiers dans le jeu 10.57745/W0KO1G
    "delta-QJXA_yr": 650453,
    "delta-QJXA-10_yr": 650451,
}
STATIONS_ID = 642043  # points de simulation (10.57745/UTKWR5)
NIVEAUX = {"RWL-20": "+2 °C", "RWL-27": "+2,7 °C", "RWL-40": "+4 °C"}

# Points de simulation retenus par pilote : (code, représentativité, justification)
STATIONS_PILOTES = {
    "11069": [("Y115201001", "bonne", "Aude à Limoux, en amont de Carcassonne (même cours d'eau que le TRI)"),
              ("Y136401001", "bonne", "Fresquel à Carcassonne, affluent couvert par le TRI")],
    "83067": [("Y521501001", "bonne", "Aille au Cannet-des-Maures, petit bassin torrentiel à 7 km")],
    "85001": [("N351161000", "moyenne", "Lay à La Bretonnière, fleuve côtier se jetant dans la baie de l'Aiguillon")],
    "33214": [("S131501000", "moyenne", "Canal des Étangs au Porge, exutoire des lacs médocains")],
    "33225": [("S213401001", "faible", "Petite Leyre à Belhade, à 29 km ; le Ciron n'est pas simulé")],
}


def _telecharger(fid: int, cache: str) -> str:
    os.makedirs(cache, exist_ok=True)
    chemin = os.path.join(cache, f"explore2_{fid}")
    if not os.path.exists(chemin):
        req = urllib.request.Request(ENTREPOT.format(id=fid), headers={"User-Agent": "demonstrateur-adaptation/0.1"})
        with urllib.request.urlopen(req, timeout=600) as r, open(chemin, "wb") as f:
            f.write(r.read())
    return chemin


def stations(cache: str = "data/cache") -> pd.DataFrame:
    return pd.read_csv(_telecharger(STATIONS_ID, cache))


def changements_crues(cache: str = "data/cache") -> pd.DataFrame:
    """Une ligne par pilote, station, indicateur et niveau : médiane et fourchette 10–90 % de l'ensemble (%)."""
    codes = {c for lst in STATIONS_PILOTES.values() for c, _, _ in lst}
    st = stations(cache).set_index("code")
    lignes = []
    for indicateur, fid in FICHIERS.items():
        d = pd.read_parquet(_telecharger(fid, cache))
        d = d[d["code"].isin(codes) & (d["EXP"] == "historical-rcp85") & (d["BC"] == "ADAMONT")]
        for pilote, lst in STATIONS_PILOTES.items():
            for code, repr_, motif in lst:
                for rwl, g in d[d["code"] == code].groupby("RWL"):
                    v = g[indicateur].dropna()
                    lignes.append({
                        "pilote": pilote, "code_station": code, "station": st.loc[code, "name"],
                        "surface_km2": st.loc[code, "surface_km2"], "representativite": repr_, "justification": motif,
                        "indicateur": indicateur, "etat": NIVEAUX[rwl],
                        "mediane_pct": v.median(), "p10_pct": v.quantile(0.1), "p90_pct": v.quantile(0.9),
                        "part_hausse": (v > 0).mean(), "n_simulations": len(v),
                        "n_chaines_climat": g[["GCM", "RCM"]].drop_duplicates().shape[0], "n_modeles_hydro": g["HM"].nunique(),
                    })
    return pd.DataFrame(lignes)
