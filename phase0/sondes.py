#!/usr/bin/env python3
"""Phase 0 du démonstrateur : sonde chaque source de données sur les communes pilotes.

Pour chaque source : accessible ou non, ce qu'elle renvoie sur chaque pilote, et le blocage éventuel.
Résultat : phase0/sondes_resultats.json (relu par la note docs/phase0_faisabilite.md).

Usage : python3 phase0/sondes.py      (stdlib seule)
"""
import json, os, re, time, urllib.error, urllib.parse, urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "demonstrateur-adaptation/0.1"}

PILOTES = {  # code INSEE : (nom, typologie)
    "85001": ("L'Aiguillon-la-Presqu'île", "côtier"),
    "33214": ("Lacanau", "côtier"),
    "33225": ("Landiras", "rural"),
    "83067": ("Gonfaron", "rural"),
    "11069": ("Carcassonne", "ville moyenne"),
}

# Couches nationales des TRI (Directive inondation) sur le WFS Géorisques.
# typ_inond : 01 débordement de cours d'eau, 02 ruissellement, 03 submersion marine.
# scénario : 01FOR fréquent, 02MOY moyen (centennal), 03MCC moyen avec changement climatique, 04FAI extrême.
TRI_COUCHES = [f"ISO_HT_{t}_{s}_FXX" for t in ("01", "02", "03") for s in ("01FOR", "02MOY", "03MCC", "04FAI")
               if not (t == "02" and s == "03MCC")]


def http(url, params=None, headers=None, timeout=60, brut=False):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",|:")
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        corps = r.read()
        return (corps, r) if brut else json.loads(corps.decode("utf-8"))


def sonde(nom, fn):
    t0 = time.time()
    try:
        res = {"statut": "ok", **fn()}
    except urllib.error.HTTPError as e:
        res = {"statut": "erreur", "erreur": f"HTTP {e.code}"}
    except Exception as e:  # réseau coupé, hôte refusé, format inattendu
        res = {"statut": "erreur", "erreur": f"{type(e).__name__}: {e}"[:300]}
    res["duree_s"] = round(time.time() - t0, 1)
    print(f"  {nom:40s} {res['statut']:7s} {res.get('erreur', '')[:90]}")
    return res


def centre(insee):
    c = http(f"https://geo.api.gouv.fr/communes/{insee}", {"fields": "nom,centre,bbox,population,siren"})
    lon, lat = c["centre"]["coordinates"]
    xs = [p[0] for p in c["bbox"]["coordinates"][0]]
    ys = [p[1] for p in c["bbox"]["coordinates"][0]]
    return c, lon, lat, (min(xs), min(ys), max(xs), max(ys))


# ------------------------------------------------------------------ climat
def s_explore2_pivots():
    meta = http("https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/",
                {"persistentId": "doi:10.57745/DCOQM6"})
    fid = meta["data"]["latestVersion"]["files"][0]["dataFile"]["id"]
    corps, _ = http(f"https://entrepot.recherche.data.gouv.fr/api/access/datafile/{fid}?format=original", brut=True)
    lignes = corps.decode("utf-8").strip().splitlines()
    tete = lignes[0].split(",")
    rows = [dict(zip(tete, l.split(","))) for l in lignes[1:]]
    rcp85 = [r for r in rows if r["EXP"] == "rcp85" and r["BC"] == "ADAMONT"]
    piv = {n: sorted(int(r[f"pivot_RWL-{n}"][:4]) for r in rcp85 if r.get(f"pivot_RWL-{n}"))
           for n in ("20", "27", "40")}
    return {"simulations_rcp85_adamont": len(rcp85),
            "annees_pivots": {f"+{int(n) / 10:.1f}°C": {"min": v[0], "mediane": v[len(v) // 2], "max": v[-1], "n": len(v)}
                              for n, v in piv.items() if v},
            "chaines": [r["climateChain"] for r in rcp85]}


def s_explore2_hydro():
    d = http("https://entrepot.recherche.data.gouv.fr/api/search",
             {"q": "TRACC", "subtree": "explore2", "type": "dataset", "per_page": 100})["data"]
    return {"jeux_tracc": d["total_count"],
            "exemples": [x["name"][:110] for x in d["items"][:5]]}


def s_cnrm_climatedata():
    corps, _ = http("https://climatedata.umr-cnrm.fr/public/dcsc/projects/DRIAS/", brut=True, timeout=30)
    return {"repertoires": re.findall(r'href="([A-Za-z0-9_-]+/)"', corps.decode("utf-8", "ignore"))}


def s_drias_portail():
    corps, _ = http("https://www.drias-climat.fr/commande", brut=True)
    t = corps.decode("utf-8", "ignore")
    return {"connexion_requise": "driassecure/authenticate" in t}


def s_cds(collection):
    def f():
        d = http(f"https://cds.climate.copernicus.eu/api/catalogue/v1/collections/{collection}")
        return {"titre": d.get("title"), "periode": d.get("extent", {}).get("temporal", {}).get("interval"),
                "telechargement": "clé API CDS gratuite requise (en-tête PRIVATE-TOKEN)"}
    return f


# ------------------------------------------------------------------ aléas
def s_georisques_commune(insee):
    def f():
        G = "https://georisques.gouv.fr/api/v1"
        risques = http(f"{G}/gaspar/risques", {"code_insee": insee})["data"]
        tri = http(f"{G}/gaspar/tri", {"code_insee": insee})["data"] or []
        azi = http(f"{G}/gaspar/azi", {"code_insee": insee})["data"] or []
        catnat = http(f"{G}/gaspar/catnat", {"code_insee": insee, "page_size": 1})
        return {"risques": [x["libelle_risque_long"] for r in risques for x in r["risques_detail"]],
                "tri": [t["libelle_tri"] for t in tri], "azi": [a["libelle_azi"] for a in azi],
                "nb_reconnaissances_catnat": catnat.get("results")}
    return f


def s_georisques_rga(lon, lat):
    def f():
        corps, _ = http("https://georisques.gouv.fr/api/v1/rga", {"latlon": f"{lon},{lat}"}, brut=True)
        # réponse vide : point hors zone cartographiée (sols sans argile, ex. sables landais)
        return json.loads(corps) if corps.strip() else {"exposition": "non cartographiée (pas d'argile)"}
    return f


def s_tri_hauteurs(bbox):
    def f():
        lon0, lat0, lon1, lat1 = bbox
        out = {}
        for couche in TRI_COUCHES:
            corps, _ = http("https://www.georisques.gouv.fr/services",
                            {"service": "WFS", "version": "1.1.0", "request": "GetFeature",
                             "typeName": f"ms:{couche}", "maxFeatures": 1000,
                             "bbox": f"{lat0},{lon0},{lat1},{lon1},EPSG:4326"}, brut=True, timeout=120)
            t = corps.decode("utf-8", "ignore")
            n = t.count("<gml:featureMember>")
            if n:
                classes = sorted(set(re.findall(r"<ms:ht_min>([^<]*)</ms:ht_min>\s*<ms:ht_max>([^<]*)</ms:ht_max>", t)))
                out[couche] = {"objets": n, "classes_hauteur_m": classes}
        return {"couches_presentes": out}
    return f


# ------------------------------------------------------------------ bâtiments
def s_bdnb(siren):
    def f():
        _, r = http(f"https://api.bdnb.io/v1/bdnb/donnees/rel_batiment_groupe_proprietaire_siren_open",
                    {"siren": f"eq.{siren}", "select": "batiment_groupe_id"},
                    headers={"Prefer": "count=exact", "Range": "0-0"}, brut=True)
        m = re.search(r"/(\d+)", r.headers.get("content-range") or "")
        return {"batiments_proprietaire": int(m.group(1)) if m else 0,
                "plafond_lignes_par_appel": r.headers.get("x-max-items-per-call")}
    return f


def s_rnb(insee):
    def f():
        d = http("https://rnb-api.beta.gouv.fr/api/alpha/buildings/", {"insee_code": insee, "limit": 1})
        b = d["results"][0] if d["results"] else {}
        return {"exemple_rnb_id": b.get("rnb_id"), "liens_externes": sorted({e["source"] for e in b.get("ext_ids") or []})}
    return f


def s_bdtopo(bbox):
    def f():
        lon0, lat0, lon1, lat1 = bbox
        d = http("https://data.geopf.fr/wfs/ows",
                 {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "BDTOPO_V3:batiment",
                  "outputFormat": "application/json", "count": 1,
                  "bbox": f"{lat0},{lon0},{lat1},{lon1},urn:ogc:def:crs:EPSG::4326"}, timeout=120)
        p = d["features"][0]["properties"] if d["features"] else {}
        return {"batiments_commune_bbox": d.get("numberMatched"),
                "champs_utiles": {k: p.get(k) for k in ("hauteur", "nombre_d_etages", "altitude_minimale_sol",
                                                        "materiaux_des_murs", "usage_1", "identifiants_rnb")}}
    return f


def s_lidar(lon, lat):
    def f():
        d = http("https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json",
                 {"lon": lon, "lat": lat, "resource": "ign_lidar_hd_mnt_mono_wld"})
        e = d["elevations"][0]
        return {"altitude_m": e["z"], "precision": e.get("acc")}
    return f


def s_dpe(insee):
    def f():
        base = "https://data.ademe.fr/data-fair/api/v1/datasets"
        out = {}
        for nom, did, champ in (("logements", "meg-83tjwtg8dyz4vv7h1dqe", "code_insee_ban"),
                                ("tertiaire", "j9ol0fwjqckyf49vr29nknbu", "code_insee_ban")):
            d = http(f"{base}/{did}/lines", {"size": 0, "qs": f'{champ}:"{insee}"'})
            out[nom] = d.get("total")
        return {"nb_dpe": out}
    return f


def s_dvf(insee):
    def f():
        dep = insee[:2]
        corps, r = http(f"https://files.data.gouv.fr/geo-dvf/latest/csv/2024/communes/{dep}/{insee}.csv", brut=True)
        return {"mutations_2024": max(0, corps.decode("utf-8").count("\n") - 1)}
    return f


def main():
    res = {"date": time.strftime("%Y-%m-%d"), "climat": {}, "pilotes": {}}
    print("Climat")
    res["climat"]["explore2_annees_pivots_tracc"] = sonde("Explore2 années pivots TRACC", s_explore2_pivots)
    res["climat"]["explore2_hydro_tracc"] = sonde("Explore2 hydrologie TRACC", s_explore2_hydro)
    res["climat"]["cnrm_climatedata_public"] = sonde("Serveur public CNRM (DRIAS)", s_cnrm_climatedata)
    res["climat"]["drias_portail"] = sonde("Portail DRIAS (commande)", s_drias_portail)
    for c in ("reanalysis-cerra-single-levels", "sis-european-wind-storm-reanalysis"):
        res["climat"][c] = sonde(f"CDS {c}", s_cds(c))

    for insee, (nom, typo) in PILOTES.items():
        print(f"{nom} ({typo})")
        c, lon, lat, bbox = centre(insee)
        p = {"nom": nom, "typologie": typo, "population": c.get("population"), "siren": c.get("siren"),
             "centre": [lon, lat]}
        p["georisques"] = sonde("Géorisques (risques, TRI, AZI, CatNat)", s_georisques_commune(insee))
        p["rga_centre"] = sonde("Argiles (BRGM) au centre", s_georisques_rga(lon, lat))
        p["tri_hauteurs"] = sonde("Hauteurs d'eau TRI (WFS)", s_tri_hauteurs(bbox))
        p["bdnb"] = sonde("BDNB bâtiments propriétaire", s_bdnb(c["siren"]))
        p["rnb"] = sonde("RNB", s_rnb(insee))
        p["bdtopo"] = sonde("BD TOPO bâtiments", s_bdtopo(bbox))
        p["lidar_hd"] = sonde("LiDAR HD (altitude)", s_lidar(lon, lat))
        p["dpe"] = sonde("DPE ADEME", s_dpe(insee))
        p["dvf"] = sonde("DVF 2024", s_dvf(insee))
        res["pilotes"][insee] = p

    with open(os.path.join(ICI, "sondes_resultats.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nOK → phase0/sondes_resultats.json")


if __name__ == "__main__":
    main()
