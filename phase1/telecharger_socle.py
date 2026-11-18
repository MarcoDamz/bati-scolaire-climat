#!/usr/bin/env python3
"""Extrait les projections climatiques du « Socle Métropole » de Météo-France (2025) aux mailles des bâtiments
des 5 communes pilotes.

Source : « Projections climatiques pour le Hackathon 2025 – Socle Métropole », Météo-France, Licence Ouverte 2.0
https://www.data.gouv.fr/datasets/projections-climatiques-pour-le-hackathon-2025-socle-metropole
Stockage objet public data.gouv (compatible S3, sans compte) : bucket `meteofrance-drias`, préfixe `SocleM-Climat-2025/`.

Contenu (documentation officielle du hackathon « Le climat en données ») :
- RCM : 17 simulations EURO-CORDEX CMIP6 (4 modèles régionaux × 9 modèles globaux), historique 1950-2014,
  SSP3-7.0 (17) et SSP5-8.5 (4) 2015-2100, quotidien, grille SAFRAN 8 km, corrigé CDF-t sur ANASTASIA/SAFRAN ;
  variables tas, tasmax, tasmin, pr, rsds, rlds, huss, sfcWind.
- CPRCM : CNRM-AROME46t1 à 2,5 km (convection résolue), 1 simulation, pluie HORAIRE corrigée sur COMEPHORE.
Les données sont signalées « en cours d'évaluation » par Météo-France.

Usage (Colab : notebooks/01_extraction_climat.ipynb) :
    python3 telecharger_socle.py --lister  --dossier DOSSIER      # inventaire du dépôt et sélection
    python3 telecharger_socle.py           --dossier DOSSIER      # extraction RCM (reprend où il s'est arrêté)
    python3 telecharger_socle.py --cprcm   --dossier DOSSIER      # + pluie horaire AROME 2,5 km
"""
import argparse, os, re, sys, time, xml.etree.ElementTree as ET
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

ENDPOINT = "https://object.files.data.gouv.fr"
BUCKET = "meteofrance-drias"
PREFIXE = "SocleM-Climat-2025/"
VARIABLES_RCM = ("tas", "tasmax", "tasmin", "pr", "sfcWind", "huss", "rsds")
EXPERIENCES = ("historical", "ssp370", "ssp585")
DEBUT, FIN = "1976-01-01", "2100-12-31"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telecharger_explore2 import POINTS  # noqa: E402  (bâtiments des pilotes : insee, lon, lat)


# ------------------------------------------------------------------ inventaire S3
def _txt(el, nom, ns):
    x = el.find(f"s3:{nom}", ns)
    if x is None:
        x = el.find(nom)
    return None if x is None else x.text


def lister_objets(session, prefixe=PREFIXE, endpoint=ENDPOINT, bucket=BUCKET):
    """Liste récursive des objets (ListObjectsV2, accès anonyme). Renvoie [(clé, taille)]."""
    objets, jeton = [], None
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    while True:
        params = {"list-type": "2", "prefix": prefixe, "max-keys": "1000"}
        if jeton:
            params["continuation-token"] = jeton
        r = session.get(f"{endpoint}/{bucket}", params=params, timeout=120)
        r.raise_for_status()
        racine = ET.fromstring(r.content)
        contenus = racine.findall("s3:Contents", ns) + racine.findall("Contents")
        objets += [(_txt(c, "Key", ns), int(_txt(c, "Size", ns) or 0)) for c in contenus]
        if _txt(racine, "IsTruncated", ns) != "true":
            return objets
        jeton = _txt(racine, "NextContinuationToken", ns)


RCM_CONNUS = ("CNRM-ALADIN64E1", "HCLIM43-ALADIN", "ICON-CLM-202407-1-1", "RACMO23E", "CNRM-AROME46t1",
              "CNRM-ALADIN63-emul-CNRM-UNET11-tP22")
VARS_CONNUES = ("tasmax", "tasmin", "tas", "pr", "rsds", "rlds", "huss", "sfcWind")


def decrire(cle):
    """Métadonnées d'un fichier (convention CORDEX-CMIP6) à partir de son nom, complété par son chemin.
    Lecture par jetons : robuste à l'ordre exact et aux segments ajoutés (méthode de correction, grille…)."""
    nom = cle.rsplit("/", 1)[-1]
    if not nom.endswith((".nc", ".nc4")):
        return None
    jetons = re.split(r"[_/]", cle[: -len(nom)] + nom.rsplit(".", 1)[0])
    noms = nom.rsplit(".", 1)[0].split("_")
    var = noms[0] if noms[0] in VARS_CONNUES else next((j for j in jetons if j in VARS_CONNUES), None)
    exp = next((j for j in noms + jetons if re.fullmatch(r"historical|ssp\d{3}", j)), None)
    membre = next((j for j in noms + jetons if re.fullmatch(r"r\d+i\d+p\d+f\d+", j)), None)
    pas = next((j for j in noms + jetons if j in ("day", "1hr", "mon")), None)
    rcm = next((r for r in RCM_CONNUS if r in cle), None)
    if not (var and exp and membre and pas and rcm):
        return None
    gcm = None
    if exp in noms and noms.index(exp) > 0:
        gcm = noms[noms.index(exp) - 1]
    if not gcm or gcm.startswith(("FR", "EUR", "ALP")):
        gcm = next((j for j in jetons if j in ("CMCC-CM2-SR5", "CNRM-ESM2-1", "NorESM2-MM", "IPSL-CM6A-LR",
                                                 "MIROC6", "EC-Earth3-Veg", "EC-Earth3", "MPI-ESM1-2-HR",
                                                 "MPI-ESM1-2-LR")), "inconnu")
    return dict(cle=cle, fichier=nom, var=var, exp=exp, membre=membre, pas=pas, rcm=rcm, gcm=gcm,
                corrige=bool(re.search(r"CDFt|[Aa]djust|ANASTASIA|SAFRAN|COMEPHORE", cle)),
                famille="CPRCM" if "AROME" in rcm else ("EMULATEUR" if "emul" in rcm else "RCM"),
                chaine=f"{gcm}_{membre}_{rcm}")


def selection(objets, cprcm=False):
    lignes = [dict(d, taille=t) for c, t in objets if (d := decrire(c))]
    inv = pd.DataFrame(lignes)
    if inv.empty:
        return inv, inv
    sel = inv[inv["exp"].isin(EXPERIENCES)]
    rcm = sel[(sel["famille"] == "RCM") & (sel["pas"] == "day") & sel["var"].isin(VARIABLES_RCM)]
    # données corrigées si le dépôt contient aussi les brutes
    if rcm["corrige"].any():
        rcm = rcm[rcm["corrige"]]
    parties = [rcm]
    if cprcm:
        cp = sel[(sel["famille"] == "CPRCM") & (sel["var"] == "pr") & (sel["pas"] == "1hr")]
        if cp["corrige"].any():
            cp = cp[cp["corrige"]]
        parties.append(cp)
    return inv, pd.concat(parties, ignore_index=True)


# ------------------------------------------------------------------ lecture des mailles
_grilles = {}


def _coords(ds):
    """lat/lon 2D de la grille ; à défaut, projection des x/y (grille SAFRAN en Lambert II étendu ou Lambert 93)."""
    for la, lo in (("lat", "lon"), ("latitude", "longitude")):
        if la in ds.variables and lo in ds.variables:
            lat, lon = ds[la].values, ds[lo].values
            if lat.ndim == 1:
                lon, lat = np.meshgrid(lon, lat)
            return lat, lon
    from pyproj import Transformer
    x, y = ds["x"].values, ds["y"].values
    epsg = 27572 if x.max() < 1.3e6 else 2154
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(xx, yy)
    return lat, lon


def mailles(ds):
    lat, lon = _coords(ds)
    cle = (lat.shape, float(np.nanmin(lat)), float(np.nanmin(lon)))
    if cle not in _grilles:
        res, coslat = {}, np.cos(np.radians(46.0))
        for insee, lo, la in POINTS:
            dist = ((lon - lo) * coslat) ** 2 + (lat - la) ** 2
            iy, ix = np.unravel_index(np.nanargmin(dist), dist.shape)
            res.setdefault((int(iy), int(ix)), set()).add(insee)
        _grilles[cle] = (res, lat, lon)
    return _grilles[cle]


def extraire(url, d):
    import fsspec, xarray as xr
    with fsspec.open(url, block_size=4 * 2**20).open() as f, xr.open_dataset(f, engine="h5netcdf") as ds:
        nomvar = d["var"] if d["var"] in ds.data_vars else [v for v in ds.data_vars if ds[v].ndim == 3][0]
        da = ds[nomvar]
        dims = [x for x in da.dims if x != "time"]
        res, lat, lon = mailles(ds)
        temps = ds.indexes["time"]
        temps = pd.to_datetime(temps.to_datetimeindex() if hasattr(temps, "to_datetimeindex") else temps)
        garde = (temps >= DEBUT) & (temps <= FIN + " 23:59")
        if not garde.any():
            return None
        idx = np.where(garde)[0]
        morceaux = []
        for (iy, ix), pilotes in res.items():
            serie = da.isel({dims[0]: iy, dims[1]: ix, "time": slice(idx[0], idx[-1] + 1)}).values.astype("float32")
            for insee in sorted(pilotes):
                morceaux.append(pd.DataFrame({
                    "pilote": insee, "maille": f"{iy}_{ix}", "lat": float(lat[iy, ix]), "lon": float(lon[iy, ix]),
                    "famille": d["famille"], "chaine": d["chaine"], "gcm": d["gcm"], "rcm": d["rcm"],
                    "membre": d["membre"], "scenario": d["exp"], "variable": d["var"],
                    "unite": da.attrs.get("units", ""), "pas": d["pas"],
                    "date": temps[idx[0]:idx[-1] + 1], "valeur": serie}))
        return pd.concat(morceaux, ignore_index=True)


# ------------------------------------------------------------------ pilotage
def tester_acces(endpoint=ENDPOINT, delai=30):
    """Vérifie que le stockage répond et que la liste anonyme du dépôt est autorisée ; affiche un diagnostic précis."""
    url = f"{endpoint}/{BUCKET}"
    try:
        r = requests.get(url, params={"list-type": "2", "prefix": PREFIXE, "max-keys": "5"}, timeout=delai)
    except requests.RequestException as e:
        print(f"Stockage data.gouv injoignable ({type(e).__name__}) : {e}")
        return False
    print(f"Réponse du stockage : HTTP {r.status_code}")
    if r.ok and "<Key>" in r.text:
        print("Liste du dépôt autorisée.")
        return True
    code = re.search(r"<Code>([^<]+)</Code>", r.text)
    print(f"Liste refusée ou vide{f' ({code.group(1)})' if code else ''}. Début de la réponse :\n{r.text[:500]}")
    if code and code.group(1) == "AccessDenied":
        print("Le stockage accepte peut-être la lecture d'un fichier connu mais pas la liste : envoyer ce message.")
    return False


def executer(dossier=".", lister=False, cprcm=False, endpoint=ENDPOINT, nom="socle_pilotes.parquet"):
    os.makedirs(dossier, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "demonstrateur-adaptation/0.1"
    print(f"Inventaire de {endpoint}/{BUCKET}/{PREFIXE} …")
    objets = lister_objets(s, endpoint=endpoint)
    inv, sel = selection(objets, cprcm)
    pd.DataFrame(objets, columns=["cle", "taille"]).to_csv(os.path.join(dossier, "socle_inventaire.csv"), index=False)
    print(f"  {len(objets)} objets, {len(inv)} fichiers NetCDF reconnus, {len(sel)} retenus "
          f"({sel['taille'].sum() / 1e9 if len(sel) else 0:.0f} Go au total, seules les mailles utiles sont lues)")
    if len(sel):
        sel.to_csv(os.path.join(dossier, "socle_fichiers_retenus.csv"), index=False)
        print(sel.groupby(["famille", "exp", "var"])["chaine"].nunique().rename("simulations").unstack("var").to_string())
    if lister or sel.empty:
        if sel.empty:
            print("\nAucun fichier reconnu : envoyez socle_inventaire.csv (dans le dossier de sortie).")
        return sel

    parts = os.path.join(dossier, nom + ".parts")
    os.makedirs(parts, exist_ok=True)
    faits, t0 = set(os.listdir(parts)), time.time()
    for i, d in enumerate(sel.to_dict("records"), 1):
        part = re.sub(r"\.nc4?$", ".parquet", d["fichier"])
        if part in faits:
            continue
        print(f"[{i}/{len(sel)}] {d['fichier']}", flush=True)
        url = f"{endpoint}/{BUCKET}/{quote(d['cle'])}"
        for essai in range(3):
            try:
                df = extraire(url, d)
                if df is not None:
                    tmp = os.path.join(parts, part + ".tmp")
                    df.to_parquet(tmp, index=False)
                    os.replace(tmp, os.path.join(parts, part))
                break
            except Exception as e:
                print(f"   ! essai {essai + 1} : {e}")
                time.sleep(10 * (essai + 1))
        print(f"   {(time.time() - t0) / 60:.0f} min écoulées", flush=True)

    fichiers = [os.path.join(parts, p) for p in sorted(os.listdir(parts)) if p.endswith(".parquet")]
    tout = pd.concat((pd.read_parquet(p) for p in fichiers), ignore_index=True)
    for c in ("pilote", "maille", "famille", "chaine", "gcm", "rcm", "membre", "scenario", "variable", "unite", "pas"):
        tout[c] = tout[c].astype("category")
    sortie = os.path.join(dossier, nom)
    tout.to_parquet(sortie, index=False, compression="zstd")
    print(f"\nOK → {sortie} ({len(tout):,} lignes, {os.path.getsize(sortie) / 1e6:.0f} Mo)")
    return tout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lister", action="store_true", help="inventaire et sélection seulement")
    ap.add_argument("--cprcm", action="store_true", help="ajouter la pluie horaire AROME 2,5 km")
    ap.add_argument("--dossier", default=".", help="dossier de sortie (ex. dossier Google Drive)")
    ap.add_argument("--endpoint", default=ENDPOINT)
    a = ap.parse_args()
    if tester_acces(a.endpoint):
        executer(a.dossier, a.lister, a.cprcm, a.endpoint)


if __name__ == "__main__":
    main()
