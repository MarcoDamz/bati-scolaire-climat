#!/usr/bin/env python3
"""
Enrichit les 21 instances de démo (onglet « Archétypes » de la base témoin) avec :
  1. identifiants officiels  : code INSEE / SIREN, population, communes membres (API Géo, API Recherche d'entreprises)
  2. arrêtés CatNat          : Géorisques, base GASPAR (une ligne par arrêté + synthèse par péril)
  3. bâtiments possédés      : BDNB open data (bâtiments dont le propriétaire est la collectivité, via son SIREN)

Usage :  python3 enrichir_instances.py            (aucune dépendance obligatoire)
         python3 enrichir_instances.py --no-bdnb  (sauter l'étape bâtiments)
         python3 enrichir_instances.py --catnat-regions  (agréger aussi les ~4 400 communes d'Occitanie : long)
Sorties : dossier ./sortie_instances/ (CSV + instances_enrichies.xlsx si openpyxl est installé)
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

OUT = "sortie_instances"
UA = {"User-Agent": "base-temoin-adaptation/1.0", "Accept": "application/json"}
GEO = "https://geo.api.gouv.fr"
RE = "https://recherche-entreprises.api.gouv.fr/search"
CATNAT = "https://georisques.gouv.fr/api/v1/gaspar/catnat"
BDNB = "https://api.bdnb.io/v1/bdnb/donnees"

# (ID, libellé, nature, paramètres de recherche)
INSTANCES = [
    ("T01", "Ville de Paris", "commune", {"nom": "Paris", "dep": "75"}),
    ("T02", "Aix-Marseille-Provence Métropole", "epci", {"nom": "Aix-Marseille-Provence"}),
    ("T03", "Toulouse Métropole", "epci", {"nom": "Toulouse Métropole"}),
    ("T04", "Bordeaux Métropole", "epci", {"nom": "Bordeaux Métropole"}),
    ("T05", "Le Havre Seine Métropole", "epci", {"nom": "Le Havre Seine Métropole"}),
    ("T06", "Perpignan Méditerranée Métropole", "epci", {"nom": "Perpignan Méditerranée"}),
    ("T07", "Carcassonne Agglo", "epci", {"nom": "Carcassonne Agglo"}),
    ("T08", "CA du Pays de Saint-Omer", "epci", {"nom": "Pays de Saint-Omer"}),
    ("T09", "Coulaines", "commune", {"nom": "Coulaines", "dep": "72"}),
    ("T10", "Lacanau", "commune", {"nom": "Lacanau", "dep": "33"}),
    ("T11", "L'Aiguillon-la-Presqu'île", "commune", {"nom": "L'Aiguillon-la-Presqu'île", "dep": "85"}),
    ("T12", "Île-de-Sein", "commune", {"nom": "Île-de-Sein", "dep": "29"}),
    ("T13", "Métabief", "commune", {"nom": "Métabief", "dep": "25", "siren_extra": "syndicat mixte du Mont d'Or"}),
    ("T14", "Chamonix-Mont-Blanc", "commune", {"nom": "Chamonix-Mont-Blanc", "dep": "74"}),
    ("T15", "Gonfaron", "commune", {"nom": "Gonfaron", "dep": "83"}),
    ("T16", "Landiras", "commune", {"nom": "Landiras", "dep": "33"}),
    ("T17", "Département des Alpes-Maritimes", "departement", {"code": "06", "nature_juridique": "7220"}),
    ("T18", "Département de la Seine-Saint-Denis", "departement", {"code": "93", "nature_juridique": "7220"}),
    ("T19", "Région Occitanie", "region", {"code": "76", "nature_juridique": "7230"}),
    ("T20", "Collectivité de Saint-Martin", "commune", {"insee": "97801"}),
    ("T21", "SYMADREM", "syndicat", {"q": "SYMADREM"}),
]


def get(url, params=None, tries=4):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=".,()")
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and i < tries - 1:
                time.sleep(2 * (i + 1)); continue
            raise
        except urllib.error.URLError:
            if i < tries - 1:
                time.sleep(2 * (i + 1)); continue
            raise


def siren_par_recherche(q, nature=None, dep=None):
    p = {"q": q, "per_page": 5}
    if nature: p["nature_juridique"] = nature
    if dep: p["departement"] = dep
    try:
        res = get(RE, p).get("results", [])
        return (res[0]["siren"], res[0].get("nom_complet")) if res else (None, None)
    except Exception as e:
        print(f"  ! recherche SIREN « {q} » : {e}"); return (None, None)


def resoudre(inst):
    """Renvoie dict : nom_officiel, insee, siren, population, communes (liste de (insee, nom))."""
    iid, label, nature, p = inst
    r = {"id": iid, "libelle": label, "nature": nature, "nom_officiel": "", "insee": "", "siren": "",
         "population": "", "communes": [], "siren_extra": "", "note": ""}
    f = "nom,code,population,siren,codeDepartement,codeEpci"
    if nature == "commune":
        if "insee" in p:
            c = get(f"{GEO}/communes/{p['insee']}", {"fields": f})
        else:
            lst = get(f"{GEO}/communes", {"nom": p["nom"], "codeDepartement": p["dep"], "fields": f})
            c = lst[0] if lst else None
        if c:
            r.update(nom_officiel=c["nom"], insee=c["code"], siren=c.get("siren", ""), population=c.get("population", ""))
            r["communes"] = [(c["code"], c["nom"])]
        if p.get("siren_extra"):
            s, n = siren_par_recherche(p["siren_extra"], dep=p.get("dep"))
            r["siren_extra"] = f"{s} ({n})" if s else "non trouvé"
    elif nature == "epci":
        lst = get(f"{GEO}/epcis", {"nom": p["nom"], "fields": "nom,code,population"})
        if lst:
            e = lst[0]
            r.update(nom_officiel=e["nom"], siren=e["code"], population=e.get("population", ""))
            r["communes"] = [(c["code"], c["nom"]) for c in get(f"{GEO}/epcis/{e['code']}/communes", {"fields": "nom,code"})]
    elif nature == "departement":
        d = get(f"{GEO}/departements/{p['code']}")
        r["nom_officiel"] = d["nom"]
        r["communes"] = [(c["code"], c["nom"]) for c in get(f"{GEO}/departements/{p['code']}/communes", {"fields": "nom,code"})]
        r["population"] = sum(c.get("population") or 0 for c in get(f"{GEO}/departements/{p['code']}/communes", {"fields": "population"}))
        s, _ = siren_par_recherche(f"département {d['nom']}", nature=p["nature_juridique"])
        r["siren"] = s or ""
    elif nature == "region":
        reg = get(f"{GEO}/regions/{p['code']}")
        r["nom_officiel"] = reg["nom"]
        cs = get(f"{GEO}/regions/{p['code']}/communes", {"fields": "nom,code,population"})
        r["communes"] = [(c["code"], c["nom"]) for c in cs]
        r["population"] = sum(c.get("population") or 0 for c in cs)
        s, _ = siren_par_recherche(f"région {reg['nom']}", nature=p["nature_juridique"])
        r["siren"] = s or ""
    elif nature == "syndicat":
        s, n = siren_par_recherche(p["q"])
        r.update(siren=s or "", nom_officiel=n or "")
        r["note"] = "CatNat : communes membres non disponibles via l'API Géo, à compléter (BANATIC)"
    if not r["nom_officiel"]:
        r["note"] = (r["note"] + " ; " if r["note"] else "") + "non résolu, vérifier les paramètres"
    return r


def catnat_commune(insee):
    rows, page = [], 1
    while True:
        d = get(CATNAT, {"code_insee": insee, "page": page, "page_size": 100})
        data = d.get("data") or []
        rows += data
        if not d.get("next") or not data:
            return rows
        page += 1


def bdnb_batiments(siren):
    """Bâtiments BDNB dont le propriétaire (personne morale) a ce SIREN."""
    rel = []
    offset = 0
    while True:
        part = get(f"{BDNB}/rel_batiment_groupe_proprietaire_siren_open",
                   {"siren": f"eq.{siren}", "limit": 1000, "offset": offset})
        rel += part
        if len(part) < 1000: break
        offset += 1000
    ids = sorted({x["batiment_groupe_id"] for x in rel})
    details = []
    champs = ("batiment_groupe_id,code_commune_insee,libelle_commune_insee,usage_principal_bdnb_open,"
              "annee_construction,s_geom_groupe,nb_niveau,mat_mur_txt,mat_toit_txt,classe_bilan_dpe")
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            details += get(f"{BDNB}/batiment_groupe_complet",
                           {"batiment_groupe_id": f"in.({','.join(chunk)})", "select": champs})
        except Exception as e:
            print(f"    ! détails BDNB (lot {i // 50}) : {e}")
            details += [{"batiment_groupe_id": b} for b in chunk]
    return details


def main():
    os.makedirs(OUT, exist_ok=True)
    no_bdnb = "--no-bdnb" in sys.argv
    full_regions = "--catnat-regions" in sys.argv
    ident, cat_rows, synth, bat_rows = [], [], [], []

    for inst in INSTANCES:
        print(f"{inst[0]} {inst[1]}")
        try:
            r = resoudre(inst)
        except Exception as e:
            print(f"  ! résolution : {e}"); continue
        print(f"  → {r['nom_officiel']} | INSEE {r['insee']} | SIREN {r['siren']} | {len(r['communes'])} commune(s)")

        # CatNat
        communes = r["communes"]
        if r["nature"] == "region" and not full_regions:
            communes = []
            r["note"] = (r["note"] + " ; " if r["note"] else "") + "CatNat région non agrégé (option --catnat-regions)"
        par_peril, n_arr, communes_touchees = Counter(), 0, set()
        derniere = ""
        for code, nom in communes:
            try:
                arr = catnat_commune(code)
            except Exception as e:
                print(f"  ! CatNat {code} : {e}"); continue
            for a in arr:
                peril = a.get("libelle_risque_jo", "")
                debut = a.get("date_debut_evt", "")
                cat_rows.append([r["id"], r["libelle"], code, nom, a.get("code_national_catnat", ""), peril,
                                 debut, a.get("date_fin_evt", ""), a.get("date_publication_arrete", ""),
                                 a.get("date_publication_jo", "")])
                par_peril[peril] += 1; n_arr += 1; communes_touchees.add(code)
                derniere = max(derniere, debut or "")
            time.sleep(0.15)
        for peril, n in par_peril.most_common():
            synth.append([r["id"], r["libelle"], peril, n])
        r["catnat_total"] = n_arr if communes else ""
        r["catnat_communes"] = len(communes_touchees) if communes else ""
        r["catnat_principal"] = par_peril.most_common(1)[0][0] if par_peril else ""
        r["catnat_dernier"] = derniere

        # BDNB
        r["bdnb_nb"] = ""
        if not no_bdnb and r["siren"]:
            try:
                bats = bdnb_batiments(r["siren"])
                r["bdnb_nb"] = len(bats)
                usages = Counter(b.get("usage_principal_bdnb_open") or "n.d." for b in bats)
                r["bdnb_usages"] = " ; ".join(f"{u} : {n}" for u, n in usages.most_common(6))
                for b in bats:
                    bat_rows.append([r["id"], r["libelle"]] + [b.get(k, "") for k in BAT_COLS])
                print(f"  → {len(bats)} bâtiments BDNB")
            except Exception as e:
                print(f"  ! BDNB : {e}")
                r["note"] = (r["note"] + " ; " if r["note"] else "") + f"BDNB indisponible ({e})"
        ident.append(r)

    I_H = ["ID", "Instance", "Nature", "Nom officiel", "Code INSEE", "SIREN", "SIREN complémentaire", "Population",
           "Nb communes", "Arrêtés CatNat (total)", "Communes avec arrêté", "Péril CatNat principal",
           "Dernier événement CatNat", "Bâtiments possédés (BDNB)", "Usages principaux (BDNB)", "Note"]
    I_R = [[r["id"], r["libelle"], r["nature"], r["nom_officiel"], r["insee"], r["siren"], r["siren_extra"],
            r["population"], len(r["communes"]), r["catnat_total"], r["catnat_communes"], r["catnat_principal"],
            r["catnat_dernier"], r["bdnb_nb"], r.get("bdnb_usages", ""), r["note"]] for r in ident]
    C_H = ["ID", "Instance", "Code INSEE", "Commune", "N° CatNat", "Péril", "Début événement", "Fin événement",
           "Date arrêté", "Date JO"]
    S_H = ["ID", "Instance", "Péril", "Nombre d'arrêtés"]
    B_H = ["ID", "Instance"] + BAT_COLS

    tables = {"Instances enrichies": (I_H, I_R), "Synthèse CatNat": (S_H, synth),
              "Arrêtés CatNat": (C_H, cat_rows), "Bâtiments BDNB": (B_H, bat_rows)}
    for name, (h, rows) in tables.items():
        with open(os.path.join(OUT, name.replace(" ", "_") + ".csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(h); w.writerows(rows)
    try:
        from openpyxl import Workbook
        wb = Workbook(); wb.remove(wb.active)
        for name, (h, rows) in tables.items():
            ws = wb.create_sheet(name[:31]); ws.append(h)
            for row in rows: ws.append(row)
            ws.freeze_panes = "A2"
        wb.save(os.path.join(OUT, "instances_enrichies.xlsx"))
        print(f"\nOK → {OUT}/instances_enrichies.xlsx")
    except ImportError:
        print(f"\nOK → CSV dans {OUT}/ (installer openpyxl pour le fichier .xlsx)")


BAT_COLS = ["batiment_groupe_id", "code_commune_insee", "libelle_commune_insee", "usage_principal_bdnb_open",
            "annee_construction", "s_geom_groupe", "nb_niveau", "mat_mur_txt", "mat_toit_txt", "classe_bilan_dpe"]

if __name__ == "__main__":
    main()
