"""Tempêtes : rafales maximales par événement aux bâtiments des pilotes (Copernicus C3S).

Source : « Windstorm tracks and footprints derived from reanalysis over Europe between 1940 to present »
(C3S, dérivé d'ERA5), produit `windstorm_footprint`, algorithme de suivi Hodges, résolution 0,25°.
Une empreinte = rafale maximale à 10 m sur 72 h pendant le passage d'une tempête.

Climat actuel uniquement : l'évolution future des tempêtes est jugée peu fiable (GIEC AR6, confiance faible
pour l'Europe de l'Ouest). La démo affiche donc les rafales de retour actuelles, sans les faire varier avec
le niveau TRACC, et le signale.

Usage : python3 -m adaptation.tempetes [annee_debut annee_fin]   (clé CDS injectée par le proxy)
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys
import time
import zipfile

import numpy as np
import pandas as pd
import requests
import xarray as xr

from adaptation import extremes

CDS = "https://cds.climate.copernicus.eu/api/retrieve/v1"
JEU = "sis-european-wind-storm-reanalysis"
CACHE = "data/cache/tempetes_c3s"
POINTS = "data/batiments_pilotes_points.json"
SORTIE = "resultats/phase1"
PERIODES_RETOUR = (10, 50, 100)


def _requete(annee: int) -> dict:
    return {"inputs": {
        "product": ["windstorm_footprint"], "variable": ["all"], "tracking_algorithm": "hodges",
        "event_aggregation": ["single_event"], "windstorm_footprint_resolution": "original",
        "spatial_extent": "full_domain", "year": [str(annee)],
        "month": [f"{m:02d}" for m in range(1, 13)], "day": [f"{d:02d}" for d in range(1, 32)]}}


def telecharger(annees, session: requests.Session) -> None:
    """Soumet une requête par année (en parallèle côté CDS), attend et dézippe dans le cache."""
    os.makedirs(CACHE, exist_ok=True)
    jobs = {}
    for a in annees:
        if os.path.exists(os.path.join(CACHE, f"{a}.ok")):
            continue
        r = session.post(f"{CDS}/processes/{JEU}/execution", json=_requete(a), timeout=120)
        if r.status_code >= 400:
            print(f"  ! {a} : {r.status_code} {r.text[:200]}"); continue
        jobs[a] = r.json()["jobID"]
    print(f"  {len(jobs)} requêtes soumises", flush=True)
    while jobs:
        for a, jid in list(jobs.items()):
            st = session.get(f"{CDS}/jobs/{jid}", timeout=60).json().get("status")
            if st == "successful":
                href = session.get(f"{CDS}/jobs/{jid}/results", timeout=60).json()["asset"]["value"]["href"]
                z = requests.get(href, timeout=600)
                z.raise_for_status()
                zipfile.ZipFile(io.BytesIO(z.content)).extractall(os.path.join(CACHE, str(a)))
                open(os.path.join(CACHE, f"{a}.ok"), "w").close()
                print(f"  {a} : {len(zipfile.ZipFile(io.BytesIO(z.content)).namelist())} tempêtes", flush=True)
                del jobs[a]
            elif st in ("failed", "dismissed", "deleted"):
                print(f"  ! {a} : {st}"); del jobs[a]
        if jobs:
            time.sleep(20)


def rafales_par_evenement() -> pd.DataFrame:
    """Rafale maximale de chaque tempête sur les mailles des bâtiments de chaque pilote."""
    pts = pd.DataFrame(json.load(open(POINTS)))
    lignes = []
    for f in sorted(glob.glob(os.path.join(CACHE, "*", "*.nc"))):
        with xr.open_dataset(f) as ds:
            fp = ds["footprint"].isel(track_id=0)
            debut = pd.Timestamp(ds["track_start_time"].values[0])
            centre = pd.Timestamp(ds["footprint_central_time"].values[0])
            val = fp.sel(longitude=xr.DataArray(pts["lon"].values, dims="p"),
                         latitude=xr.DataArray(pts["lat"].values, dims="p"), method="nearest").values
        p = pts.assign(rafale=val).groupby("pilote")["rafale"].max()
        for pilote, v in p.items():
            lignes.append({"pilote": pilote, "fichier": os.path.basename(f), "debut": debut, "date": centre,
                           "rafale_ms": float(v)})
    return pd.DataFrame(lignes)


def synthese(ev: pd.DataFrame, annees) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ev = ev.dropna(subset=["rafale_ms"]).copy()
    # une même tempête peut être suivie par deux trajectoires partageant la même empreinte : on n'en garde qu'une
    ev["_jour"] = ev["date"].dt.floor("3D")
    ev = ev.sort_values("date").drop_duplicates(subset=["pilote", "rafale_ms"]).drop(columns="_jour")
    ev["annee"] = ev["date"].dt.year
    # maximum annuel par pilote (années sans tempête retenue : maximum des empreintes = 0 n'a pas de sens, on les ignore)
    am = ev.groupby(["pilote", "annee"])["rafale_ms"].max().reset_index()
    retour = []
    for pilote, g in am.groupby("pilote"):
        params = extremes.ajuster_gev(g["rafale_ms"].to_numpy())
        for T in PERIODES_RETOUR:
            v = extremes.niveau_retour(params, T)
            retour.append({"pilote": pilote, "periode_retour": T, "rafale_ms": round(v, 1),
                           "rafale_kmh": round(v * 3.6), "n_annees": len(g),
                           "periode": f"{min(annees)}-{max(annees)}"})
    top = (ev.sort_values("rafale_ms", ascending=False).groupby("pilote").head(5)
           .assign(rafale_kmh=lambda d: (d["rafale_ms"] * 3.6).round())
           [["pilote", "date", "rafale_ms", "rafale_kmh", "fichier"]].sort_values(["pilote", "rafale_ms"], ascending=[True, False]))
    return am, pd.DataFrame(retour), top


def main():
    a0, a1 = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1979, 2025)
    annees = range(a0, a1 + 1)
    s = requests.Session()
    s.headers["User-Agent"] = "demonstrateur-adaptation/0.1"
    print(f"Téléchargement des empreintes {a0}-{a1}…", flush=True)
    telecharger(annees, s)
    ev = rafales_par_evenement()
    am, retour, top = synthese(ev, annees)
    os.makedirs(SORTIE, exist_ok=True)
    ev.to_csv(os.path.join(SORTIE, "tempetes_rafales_par_evenement.csv"), index=False)
    retour.to_csv(os.path.join(SORTIE, "tempetes_rafales_de_retour.csv"), index=False)
    top.to_csv(os.path.join(SORTIE, "tempetes_top5_par_pilote.csv"), index=False)
    print(retour.to_string(index=False))
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()
