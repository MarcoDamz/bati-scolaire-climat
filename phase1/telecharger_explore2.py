#!/usr/bin/env python3
"""Extrait les projections climatiques journalières Explore2-2022 (ADAMONT, historique + RCP8.5) aux mailles
de 8 km qui contiennent les bâtiments des 5 communes pilotes du démonstrateur.

Le serveur public du CNRM (Météo-France) ne demande aucun compte, mais filtre certains hébergeurs cloud :
`tester_acces()` le vérifie avant de commencer.

Installation (Python 3.10 ou plus) :
    pip install xarray h5netcdf h5py netCDF4 fsspec aiohttp requests pandas pyarrow

Utilisation recommandée : Google Colab, notebook notebooks/01_extraction_explore2.ipynb (écrit dans Google Drive).
En ligne de commande :
    python3 telecharger_explore2.py --lister --dossier DOSSIER   # 1) vérifier ce qui sera téléchargé
    python3 telecharger_explore2.py --dossier DOSSIER            # 2) extraire (reprend où il s'est arrêté)

Résultat : DOSSIER/explore2_pilotes.parquet (une ligne par maille, chaîne, variable et jour).
Seules les mailles des pilotes sont lues : les fichiers nationaux ne sont pas conservés.
"""
import argparse, io, json, os, re, sys, tempfile, time
from html.parser import HTMLParser
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests

RACINE = "https://climatedata.umr-cnrm.fr/public/dcsc/projects/DRIAS/"
PIVOTS_DATASET = "https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/DCOQM6"

# Variables journalières corrigées. tas : température moyenne ; pr : précipitations ; sfcWind : vent moyen ;
# hurs : humidité relative (indice de feu) ; SWI : indice d'humidité des sols (argiles, modèle SIM2).
VARIABLES = ["tasmaxAdjust", "tasminAdjust", "tasAdjust", "prtotAdjust", "prAdjust", "sfcWindAdjust",
             "hursAdjust", "SWI"]
DEBUT, FIN = "1976-01-01", "2100-12-31"

# Bâtiments des pilotes (code INSEE, lon, lat) : centroïdes BDNB des bâtiments dont la commune est propriétaire.
POINTS = [["11069", 2.2855, 43.2154], ["11069", 2.2862, 43.2227], ["11069", 2.3039, 43.2223], ["11069", 2.3044, 43.1875], ["11069", 2.3052, 43.1839], ["11069", 2.3063, 43.2194], ["11069", 2.3122, 43.1905], ["11069", 2.3166, 43.1966], ["11069", 2.3176, 43.1974], ["11069", 2.3203, 43.2069], ["11069", 2.3208, 43.1983], ["11069", 2.3226, 43.2105], ["11069", 2.323, 43.1993], ["11069", 2.3262, 43.2076], ["11069", 2.3285, 43.2006], ["11069", 2.3292, 43.2007], ["11069", 2.3295, 43.2205], ["11069", 2.3297, 43.2185], ["11069", 2.3314, 43.2044], ["11069", 2.3322, 43.2157], ["11069", 2.3324, 43.2067], ["11069", 2.333, 43.2101], ["11069", 2.3333, 43.2109], ["11069", 2.3336, 43.2096], ["11069", 2.3371, 43.2115], ["11069", 2.3389, 43.2241], ["11069", 2.342, 43.2208], ["11069", 2.342, 43.2214], ["11069", 2.3421, 43.2271], ["11069", 2.344, 43.2088], ["11069", 2.3446, 43.2086], ["11069", 2.3457, 43.2094], ["11069", 2.3463, 43.2136], ["11069", 2.3473, 43.2112], ["11069", 2.3474, 43.2114], ["11069", 2.3475, 43.2101], ["11069", 2.3477, 43.2167], ["11069", 2.3479, 43.2117], ["11069", 2.3479, 43.2124], ["11069", 2.3487, 43.2061], ["11069", 2.3487, 43.2109], ["11069", 2.3487, 43.2149], ["11069", 2.349, 43.2122], ["11069", 2.3498, 43.2102], ["11069", 2.3502, 43.2144], ["11069", 2.3502, 43.2146], ["11069", 2.3504, 43.2153], ["11069", 2.3504, 43.2191], ["11069", 2.3504, 43.222], ["11069", 2.3505, 43.2136], ["11069", 2.3505, 43.2137], ["11069", 2.3507, 43.2135], ["11069", 2.3507, 43.2136], ["11069", 2.3507, 43.2217], ["11069", 2.3508, 43.2135], ["11069", 2.3508, 43.2169], ["11069", 2.3509, 43.2155], ["11069", 2.3511, 43.2122], ["11069", 2.3513, 43.2102], ["11069", 2.3514, 43.2101], ["11069", 2.3516, 43.2128], ["11069", 2.3516, 43.2135], ["11069", 2.3516, 43.2162], ["11069", 2.3521, 43.2117], ["11069", 2.3521, 43.2171], ["11069", 2.3522, 43.2163], ["11069", 2.3523, 43.2109], ["11069", 2.3523, 43.2167], ["11069", 2.3524, 43.2161], ["11069", 2.3525, 43.2135], ["11069", 2.3526, 43.2117], ["11069", 2.3527, 43.2121], ["11069", 2.3528, 43.2113], ["11069", 2.3529, 43.2117], ["11069", 2.3531, 43.212], ["11069", 2.3532, 43.2109], ["11069", 2.3532, 43.2118], ["11069", 2.3532, 43.2128], ["11069", 2.3533, 43.2121], ["11069", 2.3536, 43.2006], ["11069", 2.3538, 43.211], ["11069", 2.3538, 43.2261], ["11069", 2.3539, 43.2165], ["11069", 2.3539, 43.2166], ["11069", 2.3545, 43.2139], ["11069", 2.3545, 43.2167], ["11069", 2.3547, 43.214], ["11069", 2.3549, 43.2155], ["11069", 2.3555, 43.211], ["11069", 2.3557, 43.2135], ["11069", 2.3557, 43.2145], ["11069", 2.3561, 43.2117], ["11069", 2.3562, 43.2259], ["11069", 2.3564, 43.2131], ["11069", 2.3565, 43.2106], ["11069", 2.3566, 43.2121], ["11069", 2.3567, 43.21], ["11069", 2.357, 43.2178], ["11069", 2.3573, 43.2106], ["11069", 2.3579, 43.2177], ["11069", 2.3592, 43.2091], ["11069", 2.3614, 43.2083], ["11069", 2.3614, 43.2085], ["11069", 2.3624, 43.2092], ["11069", 2.3634, 43.2123], ["11069", 2.3638, 43.217], ["11069", 2.3639, 43.2054], ["11069", 2.3642, 43.2062], ["11069", 2.3642, 43.2069], ["11069", 2.3643, 43.2072], ["11069", 2.3643, 43.2076], ["11069", 2.3644, 43.2066], ["11069", 2.3649, 43.2182], ["11069", 2.3654, 43.2091], ["11069", 2.3659, 43.2171], ["11069", 2.3677, 43.2127], ["11069", 2.3677, 43.213], ["11069", 2.3679, 43.2066], ["11069", 2.3694, 43.2381], ["11069", 2.3705, 43.212], ["11069", 2.3729, 43.2127], ["11069", 2.3731, 43.2257], ["11069", 2.3754, 43.202], ["11069", 2.3858, 43.2312], ["11069", 2.3935, 43.2177], ["11069", 2.3955, 43.2018], ["11069", 2.3959, 43.2023], ["11069", 2.3988, 43.2035], ["11069", 2.4152, 43.1812], ["11069", 2.4174, 43.182], ["11069", 2.4178, 43.1835], ["33214", -1.2016, 45.0006], ["33214", -1.2013, 45.0012], ["33214", -1.2011, 45.0031], ["33214", -1.1989, 45.0011], ["33214", -1.1983, 45.0045], ["33214", -1.1982, 45.0019], ["33214", -1.1968, 45.0025], ["33214", -1.1958, 45.0015], ["33214", -1.194, 45.0063], ["33214", -1.1932, 45.0033], ["33214", -1.1928, 45.0031], ["33214", -1.1926, 45.0033], ["33214", -1.1826, 45.0015], ["33214", -1.1745, 44.9985], ["33214", -1.1669, 45.0083], ["33214", -1.1441, 44.9573], ["33214", -1.1416, 44.9993], ["33214", -1.1367, 45.0035], ["33214", -1.1193, 44.972], ["33214", -1.0893, 44.9872], ["33214", -1.0817, 44.9781], ["33214", -1.0812, 44.9768], ["33214", -1.0804, 44.9789], ["33214", -1.0789, 44.977], ["33214", -1.0788, 44.9785], ["33214", -1.0785, 44.978], ["33214", -1.0776, 44.9767], ["33214", -1.0759, 44.9783], ["33214", -1.0758, 44.9785], ["33214", -1.0752, 44.9775], ["33214", -1.0742, 44.9803], ["33214", -1.0737, 44.9793], ["33214", -1.0719, 44.9779], ["33214", -1.0715, 44.978], ["33214", -1.0711, 44.9696], ["33225", -0.4166, 44.5692], ["33225", -0.4151, 44.5662], ["33225", -0.4147, 44.5662], ["33225", -0.4146, 44.5668], ["33225", -0.4144, 44.5672], ["33225", -0.4142, 44.5667], ["33225", -0.4134, 44.5673], ["33225", -0.4115, 44.5674], ["83067", 6.2823, 43.3203], ["83067", 6.2837, 43.3195], ["83067", 6.2842, 43.3192], ["83067", 6.2869, 43.3209], ["83067", 6.2872, 43.3177], ["83067", 6.2876, 43.3197], ["83067", 6.2876, 43.3198], ["83067", 6.2876, 43.3199], ["83067", 6.2876, 43.3204], ["83067", 6.2878, 43.3206], ["83067", 6.2885, 43.319], ["83067", 6.2885, 43.3191], ["83067", 6.2888, 43.32], ["83067", 6.2891, 43.3182], ["83067", 6.2898, 43.3224], ["83067", 6.2901, 43.321], ["83067", 6.2909, 43.3229], ["83067", 6.2913, 43.3218], ["83067", 6.2931, 43.3235], ["83067", 6.2942, 43.3238], ["83067", 6.3143, 43.3301], ["83067", 6.3229, 43.3373], ["85001", -1.3549, 46.3475], ["85001", -1.3345, 46.3385], ["85001", -1.3287, 46.332], ["85001", -1.3223, 46.3331], ["85001", -1.3214, 46.3302], ["85001", -1.3203, 46.3315], ["85001", -1.3199, 46.3318], ["85001", -1.3171, 46.3283], ["85001", -1.3155, 46.3352], ["85001", -1.314, 46.3358], ["85001", -1.3137, 46.3349], ["85001", -1.3094, 46.3361], ["85001", -1.3093, 46.3332], ["85001", -1.3087, 46.3198], ["85001", -1.3078, 46.3157], ["85001", -1.3078, 46.3313], ["85001", -1.3078, 46.3345], ["85001", -1.3076, 46.332], ["85001", -1.3073, 46.3341], ["85001", -1.3069, 46.3208], ["85001", -1.3068, 46.3202], ["85001", -1.306, 46.3359], ["85001", -1.3053, 46.3353], ["85001", -1.3052, 46.3353], ["85001", -1.3047, 46.334], ["85001", -1.3038, 46.3339], ["85001", -1.3022, 46.331], ["85001", -1.2982, 46.3288], ["85001", -1.2976, 46.331], ["85001", -1.2923, 46.3277], ["85001", -1.2902, 46.3266], ["85001", -1.2827, 46.3117]]


class Liens(HTMLParser):
    def __init__(self):
        super().__init__(); self.liens = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h and not h.startswith(("?", "/", "#", "http", "..")):
                self.liens.append(h)


def lister_repertoire(session, url):
    r = session.get(url, timeout=120); r.raise_for_status()
    p = Liens(); p.feed(r.text)
    return p.liens


def interessant(chemin):
    """Ne descend que dans les branches Explore2 climat ADAMONT (et SIM2 pour l'humidité des sols)."""
    c = chemin.lower()
    if any(m in c for m in ("cdft", "rcp26", "rcp45", "corse/", "indicateur", "orchidee", "ctrip", "grsd", "j2000",
                            "mordor", "smash", "eros", "adamont-2017", "adamont-2020", "drias-2020")):
        return False
    return "explore2" in c or c.count("/") <= 1


def parcourir(session, racine, profondeur_max=8):
    fichiers, a_voir = [], [(racine, 0)]
    while a_voir:
        url, prof = a_voir.pop()
        try:
            liens = lister_repertoire(session, url)
        except requests.RequestException as e:
            print(f"  ! {url} : {e}"); continue
        for l in liens:
            u = urljoin(url, l)
            rel = u[len(racine):]
            if l.endswith("/"):
                if prof < profondeur_max and interessant(rel):
                    a_voir.append((u, prof + 1))
            elif l.endswith(".nc"):
                fichiers.append(u)
    return fichiers


def charger_pivots(session):
    meta = session.get(PIVOTS_DATASET, timeout=60).json()
    fid = meta["data"]["latestVersion"]["files"][0]["dataFile"]["id"]
    txt = session.get(f"https://entrepot.recherche.data.gouv.fr/api/access/datafile/{fid}?format=original",
                      timeout=120).text
    df = pd.read_csv(io.StringIO(txt))
    df = df[(df["EXP"] == "rcp85") & (df["BC"] == "ADAMONT")].copy()
    df["chaine"] = df["GCM"] + "_" + df["RCM"]
    return df


def chaine(nom, pivots):
    for _, r in pivots.iterrows():
        for col in ("regexp_simulation_DRIAS", "regexp_indicateur_DRIAS", "regexp"):
            if re.search(r[col].replace(".*rcp85", ".*(rcp85|historical)").replace("rcp85.*", "(rcp85|historical).*"), nom):
                return r["chaine"]
    return None


def selection(fichiers, pivots):
    out = []
    for u in fichiers:
        nom = u.rsplit("/", 1)[-1]
        var = nom.split("_")[0]
        if var not in VARIABLES:
            continue
        if "ADAMONT" not in nom.upper() or not re.search(r"(rcp85|historical)", nom):
            continue
        if not re.search(r"_day_|_day\.|_jour", nom) and var != "SWI":
            continue
        ch = chaine(nom, pivots)
        if ch:
            out.append((u, nom, var, ch))
    return out


def ouvrir(url, session):
    """Lecture à distance (requêtes partielles) si possible ; sinon téléchargement temporaire."""
    import xarray as xr
    try:
        import fsspec
        f = fsspec.open(url, block_size=4 * 2**20).open()
        return xr.open_dataset(f, engine="h5netcdf"), None
    except Exception:
        tmp = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
        with session.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            for bloc in r.iter_content(2**22):
                tmp.write(bloc)
        tmp.close()
        return xr.open_dataset(tmp.name), tmp.name


_grilles = {}


def mailles(ds):
    """Indices (iy, ix) de la maille la plus proche de chaque point de bâtiment ; mis en cache par grille."""
    lat = ds["lat"].values if "lat" in ds else ds["latitude"].values
    lon = ds["lon"].values if "lon" in ds else ds["longitude"].values
    if lat.ndim == 1:
        lon, lat = np.meshgrid(lon, lat)
    cle = (lat.shape, float(lat.flat[0]), float(lon.flat[0]))
    if cle not in _grilles:
        res = {}
        coslat = np.cos(np.radians(46.0))
        for insee, lo, la in POINTS:
            d = ((lon - lo) * coslat) ** 2 + (lat - la) ** 2
            iy, ix = np.unravel_index(np.nanargmin(d), d.shape)
            res.setdefault((int(iy), int(ix)), set()).add(insee)
        _grilles[cle] = (res, lat, lon)
    return _grilles[cle]


def extraire(url, nom, var, ch, session):
    ds, tmp = ouvrir(url, session)
    try:
        nomvar = var if var in ds.data_vars else [v for v in ds.data_vars if ds[v].ndim == 3][0]
        da = ds[nomvar]
        dims_spatiales = [d for d in da.dims if d != "time"]
        res, lat, lon = mailles(ds)
        temps = pd.to_datetime(ds.indexes["time"].to_datetimeindex() if hasattr(ds.indexes["time"], "to_datetimeindex")
                               else ds.indexes["time"])
        garde = (temps >= DEBUT) & (temps <= FIN)
        morceaux = []
        for (iy, ix), pilotes in res.items():
            serie = da.isel({dims_spatiales[0]: iy, dims_spatiales[1]: ix}).values.astype("float32")
            for insee in sorted(pilotes):
                morceaux.append(pd.DataFrame({
                    "pilote": insee, "maille": f"{iy}_{ix}", "lat": float(lat[iy, ix]), "lon": float(lon[iy, ix]),
                    "chaine": ch, "variable": var, "unite": da.attrs.get("units", ""),
                    "scenario": "rcp85" if "rcp85" in nom else "historical",
                    "date": temps[garde], "valeur": serie[garde]}))
        return pd.concat(morceaux, ignore_index=True) if morceaux else None
    finally:
        ds.close()
        if tmp:
            os.unlink(tmp)


def tester_acces(racine=RACINE, delai=30):
    """Vérifie que le serveur du CNRM répond depuis cette machine (il filtre certains hébergeurs cloud)."""
    try:
        r = requests.get(racine, timeout=delai, headers={"User-Agent": "demonstrateur-adaptation/0.1"})
        r.raise_for_status()
        print(f"Serveur CNRM accessible ({r.status_code}).")
        return True
    except requests.RequestException as e:
        print(f"Serveur CNRM inaccessible depuis cette machine : {e}\n"
              "Il filtre certains hébergeurs cloud. Lancez alors le script depuis un poste classique "
              "(même commande), en écrivant dans le dossier Google Drive synchronisé.")
        return False


def executer(dossier=".", lister=False, racine=RACINE, nom="explore2_pilotes.parquet"):
    """Liste puis extrait. Tout est écrit dans `dossier` (ex. un dossier Google Drive monté dans Colab) :
    la liste des fichiers retenus, un fichier par fichier source traité (reprise après coupure), le Parquet final."""
    os.makedirs(dossier, exist_ok=True)
    sortie = os.path.join(dossier, nom)
    s = requests.Session(); s.headers["User-Agent"] = "demonstrateur-adaptation/0.1"
    print("Années pivots TRACC…")
    pivots = charger_pivots(s)
    print(f"  {len(pivots)} chaînes RCP8.5 ADAMONT")
    print(f"Parcours de {racine} …")
    retenus = selection(parcourir(s, racine), pivots)
    bilan = pd.DataFrame(retenus, columns=["url", "fichier", "variable", "chaine"])
    print(f"  {len(bilan)} fichiers retenus")
    if len(bilan):
        print(bilan.groupby(["variable"])["chaine"].nunique().rename("chaînes couvertes").to_string())
    liste = os.path.join(dossier, "explore2_fichiers_retenus.csv")
    bilan.to_csv(liste, index=False)
    print(f"  liste détaillée : {liste}")
    if lister or bilan.empty:
        if bilan.empty:
            print("\nAucun fichier reconnu : envoyez explore2_fichiers_retenus.csv et la sortie de ce script.")
        return bilan

    parts_dir = sortie + ".parts"
    os.makedirs(parts_dir, exist_ok=True)
    faits = set(os.listdir(parts_dir))
    t0 = time.time()
    for i, (url, nomf, var, ch) in enumerate(retenus, 1):
        part = nomf.replace(".nc", ".parquet")
        if part in faits:
            continue
        print(f"[{i}/{len(retenus)}] {nomf}", flush=True)
        for essai in range(3):
            try:
                df = extraire(url, nomf, var, ch, s)
                if df is not None:
                    tmp = os.path.join(parts_dir, part + ".tmp")
                    df.to_parquet(tmp, index=False)
                    os.replace(tmp, os.path.join(parts_dir, part))  # écriture atomique : pas de fichier tronqué
                break
            except Exception as e:
                print(f"   ! essai {essai + 1} : {e}")
                time.sleep(10 * (essai + 1))
        print(f"   {(time.time() - t0) / 60:.0f} min écoulées", flush=True)

    parts = [os.path.join(parts_dir, p) for p in sorted(os.listdir(parts_dir)) if p.endswith(".parquet")]
    tout = pd.concat((pd.read_parquet(p) for p in parts), ignore_index=True)
    for c in ("pilote", "maille", "chaine", "variable", "unite", "scenario"):
        tout[c] = tout[c].astype("category")
    tout.to_parquet(sortie, index=False, compression="zstd")
    print(f"\nOK → {sortie} ({len(tout):,} lignes, {os.path.getsize(sortie) / 1e6:.0f} Mo)")
    return tout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lister", action="store_true", help="lister les fichiers retenus sans rien extraire")
    ap.add_argument("--racine", default=RACINE)
    ap.add_argument("--dossier", default=".", help="dossier de sortie (ex. dossier Google Drive)")
    args = ap.parse_args()
    if tester_acces(args.racine):
        executer(args.dossier, args.lister, args.racine)


if __name__ == "__main__":
    main()
