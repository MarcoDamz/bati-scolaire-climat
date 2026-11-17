#!/usr/bin/env python3
"""
Enrichit les 21 instances de démo (onglet « Archétypes » de la base témoin) avec :
  1. identifiants officiels  : code INSEE / SIREN, population, communes membres
                               (API Géo, API Recherche d'entreprises, BANATIC pour les syndicats)
  2. arrêtés CatNat          : Géorisques, base GASPAR (une ligne par arrêté + synthèse par péril),
                               y compris les codes INSEE des communes déléguées / associées
  3. bâtiments possédés      : BDNB open data (bâtiments dont le propriétaire est la collectivité, via son SIREN),
                               avec repli sur les « Fichiers des locaux des personnes morales » (DGFiP)

Usage :  python3 enrichir_instances.py                    (stdlib seule ; duckdb conseillé pour le repli DGFiP)
         python3 enrichir_instances.py --no-bdnb          (sauter l'étape bâtiments)
         python3 enrichir_instances.py --no-pm            (ne pas utiliser les fichiers DGFiP des personnes morales)
         python3 enrichir_instances.py --catnat-regions   (agréger aussi les ~4 450 communes d'Occitanie)
         python3 enrichir_instances.py --pm-parquet CHEMIN (fichier locaux_personnes_morales déjà téléchargé)
Sorties : dossier ./sortie_instances/ (CSV + instances_enrichies.xlsx si openpyxl est installé)

Limites connues des API (constatées en novembre 2026) :
  - BDNB sans clé : 10 lignes maximum par appel (x-max-items-per-call), 120 appels/min, quota ~10 000 appels.
  - GASPAR : aucun arrêté pour Saint-Martin (97801), à compléter à la main.
"""
import csv, datetime as dt, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict

OUT = "sortie_instances"
CACHE = os.path.join(OUT, "_cache")
UA = {"User-Agent": "base-temoin-adaptation/1.0", "Accept": "application/json"}
GEO = "https://geo.api.gouv.fr"
RE = "https://recherche-entreprises.api.gouv.fr/search"
CATNAT = "https://georisques.gouv.fr/api/v1/gaspar/catnat"
BDNB = "https://api.bdnb.io/v1/bdnb/donnees"
BANATIC = "https://www.banatic.interieur.gouv.fr"
PM_DATASET = "https://www.data.gouv.fr/api/1/datasets/6900772ca5c4fa6c5687b3bd/"  # locaux des personnes morales (parquet)

BDNB_PAGE = 10          # plafond imposé par l'API BDNB sans clé
BDNB_INTERVALLE = 0.55  # s entre deux appels BDNB (120 appels/min)
CATNAT_LOT = 20         # codes INSEE par requête GASPAR

# (ID, libellé, nature, paramètres)
#   insee / siren / code : identifiant figé (vérifié en novembre 2026) ; « nom » sert au contrôle de cohérence.
INSTANCES = [
    ("T01", "Ville de Paris", "commune", {"insee": "75056", "nom": "Paris"}),
    ("T02", "Aix-Marseille-Provence Métropole", "epci", {"siren": "200054807", "nom": "Aix-Marseille-Provence"}),
    ("T03", "Toulouse Métropole", "epci", {"siren": "243100518", "nom": "Toulouse Métropole"}),
    ("T04", "Bordeaux Métropole", "epci", {"siren": "243300316", "nom": "Bordeaux Métropole"}),
    ("T05", "Le Havre Seine Métropole", "epci", {"siren": "200084952", "nom": "Le Havre Seine Métropole"}),
    ("T06", "Perpignan Méditerranée Métropole", "epci", {"siren": "200027183", "nom": "Perpignan Méditerranée"}),
    ("T07", "Carcassonne Agglo", "epci", {"siren": "200035715", "nom": "Carcassonne Agglo"}),
    ("T08", "CA du Pays de Saint-Omer", "epci", {"siren": "200069037", "nom": "Pays de Saint-Omer"}),
    ("T09", "Coulaines", "commune", {"insee": "72095", "nom": "Coulaines"}),
    ("T10", "Lacanau", "commune", {"insee": "33214", "nom": "Lacanau"}),
    ("T11", "L'Aiguillon-la-Presqu'île", "commune", {"insee": "85001", "nom": "L'Aiguillon-la-Presqu'île"}),
    ("T12", "Île-de-Sein", "commune", {"insee": "29083", "nom": "Île-de-Sein"}),
    ("T13", "Métabief", "commune", {"insee": "25380", "nom": "Métabief", "siren_extra": "200051886"}),
    ("T14", "Chamonix-Mont-Blanc", "commune", {"insee": "74056", "nom": "Chamonix-Mont-Blanc"}),
    ("T15", "Gonfaron", "commune", {"insee": "83067", "nom": "Gonfaron"}),
    ("T16", "Landiras", "commune", {"insee": "33225", "nom": "Landiras"}),
    ("T17", "Département des Alpes-Maritimes", "departement", {"code": "06", "siren": "220600019"}),
    ("T18", "Département de la Seine-Saint-Denis", "departement", {"code": "93", "siren": "229300082"}),
    ("T19", "Région Occitanie", "region", {"code": "76", "siren": "200053791"}),
    ("T20", "Collectivité de Saint-Martin", "commune", {"insee": "97801", "siren": "219711272", "nom": "Saint-Martin"}),
    ("T21", "SYMADREM", "syndicat", {"siren": "251302048", "nom": "SYMADREM"}),
]

_dernier_appel = defaultdict(float)


def get(url, params=None, tries=5, headers=None, throttle=None, brut=False):
    """GET JSON avec reprises ; throttle=(clé, intervalle) espace les appels vers une même API."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=".,()")
    h = dict(UA, **(headers or {}))
    for i in range(tries):
        if throttle:
            cle, inter = throttle
            attente = _dernier_appel[cle] + inter - time.time()
            if attente > 0: time.sleep(attente)
            _dernier_appel[cle] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90) as r:
                corps = r.read().decode("utf-8")
                return (json.loads(corps), r.headers) if brut else json.loads(corps)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep((15 if e.code == 429 else 3) * (i + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < tries - 1:
                time.sleep(3 * (i + 1)); continue
            raise


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def date_fr(s):
    try:
        return dt.datetime.strptime(s, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def ajouter_note(r, txt):
    r["note"] = (r["note"] + " ; " if r["note"] else "") + txt


# ---------------------------------------------------------------- identifiants
def sirene(siren):
    """Fiche SIRENE (nom, nature juridique, état) d'un SIREN via l'API Recherche d'entreprises."""
    try:
        for x in get(RE, {"q": siren, "per_page": 5}).get("results", []):
            if x["siren"] == siren:
                return x
    except Exception as e:
        print(f"  ! SIRENE {siren} : {e}")
    return None


def communes_deleguees():
    """{code chef-lieu: [(code, nom, type)]} des communes déléguées / associées (anciens codes INSEE)."""
    m = defaultdict(list)
    for c in get(f"{GEO}/communes_associees_deleguees", {"fields": "nom,code,chefLieu,type"}):
        if c["code"] != c["chefLieu"]:
            m[c["chefLieu"]].append((c["code"], c["nom"], c["type"]))
    return m


def banatic_groupement(siren):
    """Page BANATIC d'un groupement (données JSON de l'application Next.js)."""
    html = urllib.request.urlopen(urllib.request.Request(BANATIC + "/", headers={"User-Agent": UA["User-Agent"]}),
                                  timeout=60).read().decode("utf-8")
    build = re.search(r'"buildId":"([^"]+)"', html).group(1)
    return get(f"{BANATIC}/_next/data/{build}/intercommunalite/{siren}.json")["pageProps"]["intercommunaliteJson"]


def perimetre_banatic(j):
    """Communes couvertes par un syndicat : communes adhérentes + périmètres des transferts de compétences
    (un transfert total d'un EPCI couvre toutes ses communes)."""
    communes, membres = {}, []
    for pd in j.get("perimetreDepartements") or []:
        for c in pd.get("communesAdherentes") or []:
            communes[c.get("code") or c.get("codeInsee")] = c.get("libelle") or c.get("nom")
        membres += [f"{g['libelle']} ({g['siren']})" for g in pd.get("groupementsAdherents") or []]
        membres += [f"{g['libelle']} ({g['siren']})" for g in pd.get("personnesMoralesAdherentes") or []]
    for comp in j.get("competencesGroupement") or []:
        for t in comp.get("transfertsEntrants") or []:
            per = t.get("perimetreCommune") or []
            if per:
                communes.update({c["code"]: c["libelle"] for c in per})
            elif not t.get("transfertPartiel"):
                communes.update({c["code"]: c["nom"] for c in get(f"{GEO}/epcis/{t['siren']}/communes", {"fields": "nom,code"})})
    return sorted(communes.items()), membres


def resoudre(inst):
    """Renvoie dict : nom_officiel, insee, siren, population, communes (liste de (insee, nom))."""
    iid, label, nature, p = inst
    r = {"id": iid, "libelle": label, "nature": nature, "nom_officiel": "", "insee": "", "siren": "",
         "population": "", "communes": [], "siren_extra": "", "nom_sirene": "", "controle": "", "note": "",
         "membres": ""}
    f = "nom,code,population,siren,codeDepartement,codeEpci"
    if nature == "commune":
        c = get(f"{GEO}/communes/{p['insee']}", {"fields": f})
        r.update(nom_officiel=c["nom"], insee=c["code"], siren=c.get("siren") or p.get("siren", ""),
                 population=c.get("population", ""))
        r["communes"] = [(c["code"], c["nom"])]
        if p.get("siren_extra"):
            x = sirene(p["siren_extra"])
            r["siren_extra"] = f"{p['siren_extra']} ({x['nom_complet']})" if x else f"{p['siren_extra']} (non trouvé)"
    elif nature == "epci":
        e = get(f"{GEO}/epcis/{p['siren']}", {"fields": "nom,code,population"})
        r.update(nom_officiel=e["nom"], siren=e["code"], population=e.get("population", ""))
        r["communes"] = [(c["code"], c["nom"]) for c in get(f"{GEO}/epcis/{e['code']}/communes", {"fields": "nom,code"})]
    elif nature == "departement":
        d = get(f"{GEO}/departements/{p['code']}")
        cs = get(f"{GEO}/departements/{p['code']}/communes", {"fields": "nom,code,population"})
        r.update(nom_officiel=d["nom"], siren=p["siren"], population=sum(c.get("population") or 0 for c in cs))
        r["communes"] = [(c["code"], c["nom"]) for c in cs]
    elif nature == "region":
        reg = get(f"{GEO}/regions/{p['code']}")
        cs = get(f"{GEO}/communes", {"codeRegion": p["code"], "fields": "nom,code,population"})
        r.update(nom_officiel=reg["nom"], siren=p["siren"], population=sum(c.get("population") or 0 for c in cs))
        r["communes"] = [(c["code"], c["nom"]) for c in cs]
    elif nature == "syndicat":
        r["siren"] = p["siren"]
        try:
            j = banatic_groupement(p["siren"])
            r["nom_officiel"] = j["identite"]["nom"]
            r["population"] = (j.get("populationGroupement") or {}).get("populationTotale", "")
            r["communes"], membres = perimetre_banatic(j)
            r["membres"] = " ; ".join(membres)
            ajouter_note(r, "communes = périmètre des compétences transférées (BANATIC)")
        except Exception as e:
            print(f"  ! BANATIC {p['siren']} : {e}")
            ajouter_note(r, f"BANATIC indisponible ({e}) : communes non agrégées")

    # Contrôles : fiche SIRENE + cohérence du nom
    if r["siren"]:
        x = sirene(r["siren"])
        if x:
            r["nom_sirene"] = x.get("nom_complet", "")
            if x.get("etat_administratif") != "A":
                ajouter_note(r, "SIREN cessé au répertoire SIRENE")
        else:
            ajouter_note(r, "SIREN introuvable dans SIRENE")
    else:
        ajouter_note(r, "pas de SIREN")
    attendu = norm(p.get("nom") or label)
    trouve = norm(r["nom_officiel"]) + " " + norm(r["nom_sirene"])
    mots = [m for m in attendu.split() if len(m) > 2 and m not in ("des", "les", "du", "de", "la")]
    r["controle"] = "OK" if r["nom_officiel"] and all(m in trouve for m in mots) else "À VÉRIFIER"
    if not r["nom_officiel"]:
        ajouter_note(r, "non résolu, vérifier les paramètres")
    return r


# ---------------------------------------------------------------- CatNat
_catnat_cache = {}


def catnat_codes(codes):
    """Arrêtés GASPAR pour une liste de codes INSEE (requêtes groupées, mises en cache)."""
    a_faire = [c for c in dict.fromkeys(codes) if c not in _catnat_cache]
    for c in a_faire:
        _catnat_cache[c] = []
    for i in range(0, len(a_faire), CATNAT_LOT):
        lot = a_faire[i:i + CATNAT_LOT]
        page = 1
        while True:
            try:
                d = get(CATNAT, {"code_insee": ",".join(lot), "page": page, "page_size": 100})
            except Exception as e:
                print(f"  ! CatNat {lot[0]}… : {e}")
                for c in lot: _catnat_cache[c] = None
                break
            data = d.get("data") or []
            for a in data:
                _catnat_cache.setdefault(a.get("code_insee"), []).append(a)
            if not d.get("next") or not data:
                break
            page += 1
        time.sleep(0.1)
    return {c: _catnat_cache.get(c) for c in codes}


# ---------------------------------------------------------------- BDNB
BAT_COLS = ["batiment_groupe_id", "code_commune_insee", "libelle_commune_insee", "libelle_adr_principale_ban",
            "usage_principal_bdnb_open", "annee_construction", "s_geom_groupe", "nb_niveau", "mat_mur_txt",
            "mat_toit_txt", "classe_bilan_dpe"]
BDNB_T = ("bdnb", BDNB_INTERVALLE)


def bdnb_batiments(siren):
    """Bâtiments BDNB dont le propriétaire (personne morale, fichiers MAJIC PM) a ce SIREN.
    Pagination par 10 (plafond de l'API sans clé), tri stable sur batiment_groupe_id."""
    rel, offset, total = [], 0, None
    while True:
        part, h = get(f"{BDNB}/rel_batiment_groupe_proprietaire_siren_open",
                      {"siren": f"eq.{siren}", "order": "batiment_groupe_id", "limit": BDNB_PAGE, "offset": offset},
                      headers={"Prefer": "count=exact"} if total is None else None, throttle=BDNB_T, brut=True)
        if total is None:
            m = re.search(r"/(\d+)", h.get("content-range") or "")
            total = int(m.group(1)) if m else None
            if total: print(f"    BDNB : {total} lien(s) propriétaire → {(total + 9) // 10 * 2} appels")
        rel += part
        offset += len(part)
        if len(part) < BDNB_PAGE or (total is not None and offset >= total):
            break
    locaux = Counter()
    for x in rel:
        locaux[x["batiment_groupe_id"]] += x.get("nb_locaux_open") or 0
    ids = sorted(locaux)
    details = {}
    for i in range(0, len(ids), BDNB_PAGE):
        lot = ids[i:i + BDNB_PAGE]
        try:
            for b in get(f"{BDNB}/batiment_groupe_complet",
                         {"batiment_groupe_id": f"in.({','.join(lot)})", "select": ",".join(BAT_COLS)}, throttle=BDNB_T):
                details[b["batiment_groupe_id"]] = b
        except Exception as e:
            print(f"    ! détails BDNB (lot {i // BDNB_PAGE}) : {e}")
    return [dict(details.get(b, {"batiment_groupe_id": b}), nb_locaux=locaux[b]) for b in ids]


# ---------------------------------------------------------------- repli DGFiP (fichiers des personnes morales)
def pm_parquet(chemin=None):
    if chemin:
        return chemin
    os.makedirs(CACHE, exist_ok=True)
    meta = get(PM_DATASET)
    res = next(x for x in meta["resources"] if x["title"] == "locaux_personnes_morales_latest.parquet")
    dest = os.path.join(CACHE, "locaux_personnes_morales_latest.parquet")
    if not os.path.exists(dest) or os.path.getsize(dest) != res.get("filesize"):
        print(f"  téléchargement {res['url']} ({(res.get('filesize') or 0) / 1e6:.0f} Mo)…")
        urllib.request.urlretrieve(res["url"], dest)
    return dest


def pm_locaux(sirens, chemin):
    """Par SIREN : (nb locaux, nb parcelles, millésime, lignes agrégées par parcelle)."""
    import duckdb
    lst = ",".join(f"'{s}'" for s in sirens)
    con = duckdb.connect()
    q = f"""
        select numero_siren, millesime, code_insee, nom_commune, section, numero_parcelle,
               trim(concat_ws(' ', ltrim(numero_voirie, '0'), indice_de_repetition, nature_voie, nom_voie)) as adresse,
               count(*) as nb_locaux, string_agg(distinct code_droit_libelle, ' / ') as droits,
               any_value(denomination) as denomination
        from read_parquet('{chemin}') where numero_siren in ({lst})
        group by all order by numero_siren, code_insee, section, numero_parcelle, adresse"""
    out = defaultdict(lambda: [0, 0, "", []])
    for s, mil, insee, commune, sec, num, adr, n, droits, denom in con.sql(q).fetchall():
        o = out[s]
        o[0] += n; o[2] = mil
        if insee and len(insee) == 6:  # DOM : département sur 3 caractères + commune sur 3 (971127 → 97127)
            insee = insee[:3] + insee[4:]
        o[3].append(dict(code_commune_insee=insee,libelle_commune_insee=(commune or "").title(),
                         libelle_adr_principale_ban=adr, parcelle=f"{sec}{num}", nb_locaux=n, droits=droits,
                         denomination=denom))
    for s, o in out.items():
        o[1] = len({(x["code_commune_insee"], x["parcelle"]) for x in o[3]})
    return out


# ---------------------------------------------------------------- principal
def arg(nom):
    return sys.argv[sys.argv.index(nom) + 1] if nom in sys.argv else None


def main():
    os.makedirs(OUT, exist_ok=True)
    no_bdnb = "--no-bdnb" in sys.argv
    no_pm = "--no-pm" in sys.argv
    full_regions = "--catnat-regions" in sys.argv
    ident, cat_rows, synth, bat_rows = [], [], [], []
    deleguees = communes_deleguees()

    for inst in INSTANCES:
        print(f"{inst[0]} {inst[1]}")
        try:
            r = resoudre(inst)
        except Exception as e:
            print(f"  ! résolution : {e}"); continue
        print(f"  → {r['nom_officiel']} | INSEE {r['insee']} | SIREN {r['siren']} ({r['nom_sirene']}) | "
              f"{len(r['communes'])} commune(s) | contrôle {r['controle']}")

        # CatNat (communes actuelles + anciens codes des communes déléguées / associées)
        communes = r["communes"]
        if r["nature"] == "region" and not full_regions:
            communes = []
            ajouter_note(r, "CatNat région non agrégé (option --catnat-regions)")
        cibles = []
        for code, nom in communes:
            cibles.append((code, nom, code, nom))
            cibles += [(code, nom, ac, an) for ac, an, _ in deleguees.get(code, [])]
        anciens = [c for c in cibles if c[0] != c[2]]
        if anciens and r["nature"] == "commune":
            ajouter_note(r, "CatNat inclut les anciens codes : " + ", ".join(f"{c[3]} ({c[2]})" for c in anciens))
        par_code = catnat_codes([c[2] for c in cibles])
        par_peril, communes_touchees, vus = Counter(), set(), set()
        derniere, echecs = None, 0
        for code, nom, code_g, nom_g in cibles:
            arr = par_code.get(code_g)
            if arr is None:
                echecs += 1; continue
            for a in arr:
                cle = (code_g, a.get("code_national_catnat"), a.get("libelle_risque_jo"), a.get("date_debut_evt"),
                       a.get("date_fin_evt"))  # un arrêté peut reconnaître plusieurs périls / épisodes
                if cle in vus: continue
                vus.add(cle)
                peril = a.get("libelle_risque_jo", "")
                debut = date_fr(a.get("date_debut_evt"))
                cat_rows.append([r["id"], r["libelle"], code, nom, code_g, a.get("libelle_commune") or nom_g,
                                 a.get("code_national_catnat", ""), peril, debut, date_fr(a.get("date_fin_evt")),
                                 date_fr(a.get("date_publication_arrete")), date_fr(a.get("date_publication_jo"))])
                par_peril[peril] += 1; communes_touchees.add(code)
                if debut and (derniere is None or debut > derniere): derniere = debut
        if echecs:
            ajouter_note(r, f"CatNat : {echecs} code(s) INSEE en échec")
        n_arr = sum(par_peril.values())
        for peril, n in par_peril.most_common():
            synth.append([r["id"], r["libelle"], peril, n])
        r["catnat_total"] = n_arr if communes else ""
        r["catnat_communes"] = len(communes_touchees) if communes else ""
        r["catnat_principal"] = par_peril.most_common(1)[0][0] if par_peril else ""
        r["catnat_dernier"] = derniere
        if communes and n_arr == 0:
            ajouter_note(r, "aucun arrêté CatNat dans GASPAR : à vérifier à la main")
        print(f"  → {n_arr} arrêté(s) CatNat sur {len(communes_touchees)} commune(s)")

        # BDNB
        r.update(bdnb_nb="", bdnb_usages="", bat_source="")
        if not no_bdnb and r["siren"]:
            try:
                bats = bdnb_batiments(r["siren"])
                r["bdnb_nb"] = len(bats)
                usages = Counter(b.get("usage_principal_bdnb_open") or "n.d." for b in bats)
                r["bdnb_usages"] = " ; ".join(f"{u} : {n}" for u, n in usages.most_common(6))
                if bats:
                    r["bat_source"] = "BDNB"
                for b in bats:
                    bat_rows.append([r["id"], r["libelle"], "BDNB"] + [b.get(k, "") for k in BAT_COLS]
                                    + ["", b.get("nb_locaux", ""), "", ""])
                print(f"  → {len(bats)} bâtiment(s) BDNB")
            except Exception as e:
                print(f"  ! BDNB : {e}")
                r["bdnb_nb"] = "erreur"
                ajouter_note(r, f"BDNB indisponible ({e})")
        ident.append(r)

    # Repli et contrôle : fichiers DGFiP des locaux des personnes morales
    if not no_pm:
        try:
            chemin = pm_parquet(arg("--pm-parquet"))
            pm = pm_locaux([r["siren"] for r in ident if r["siren"]], chemin)
            for r in ident:
                n_loc, n_parc, mil, lignes = pm.get(r["siren"], (0, 0, "", []))
                r["pm_locaux"], r["pm_parcelles"] = (n_loc, n_parc) if r["siren"] else ("", "")
                if r["siren"] and not r["bat_source"] and not no_bdnb:
                    if lignes:
                        r["bat_source"] = f"Fichiers PM DGFiP {mil} (repli)"
                        ajouter_note(r, f"aucun bâtiment BDNB : repli sur les fichiers DGFiP des personnes morales ({mil})")
                        for x in lignes:
                            bat_rows.append([r["id"], r["libelle"], f"Fichiers PM DGFiP {mil}", "",
                                             x["code_commune_insee"], x["libelle_commune_insee"],
                                             x["libelle_adr_principale_ban"]] + [""] * 6
                                            + [x["parcelle"], x["nb_locaux"], x["droits"], x["denomination"]])
                    else:
                        ajouter_note(r, "aucun bien trouvé ni dans la BDNB ni dans les fichiers DGFiP")
        except ImportError:
            print("  ! repli DGFiP : installer duckdb (pip install duckdb)")
        except Exception as e:
            print(f"  ! repli DGFiP : {e}")

    I_H = ["ID", "Instance", "Nature", "Nom officiel", "Nom au répertoire SIRENE", "Contrôle nom", "Code INSEE",
           "SIREN", "SIREN complémentaire", "Population", "Nb communes", "Membres (BANATIC)",
           "Reconnaissances CatNat (arrêté × péril × épisode)", "Communes avec arrêté", "Péril CatNat principal", "Dernier événement CatNat",
           "Bâtiments possédés (BDNB)", "Usages principaux (BDNB)", "Locaux PM DGFiP", "Parcelles PM DGFiP",
           "Source bâtiments", "Note"]
    I_R = [[r["id"], r["libelle"], r["nature"], r["nom_officiel"], r["nom_sirene"], r["controle"], r["insee"],
            r["siren"], r["siren_extra"], r["population"], len(r["communes"]), r["membres"], r["catnat_total"],
            r["catnat_communes"], r["catnat_principal"], r["catnat_dernier"], r["bdnb_nb"], r["bdnb_usages"],
            r.get("pm_locaux", ""), r.get("pm_parcelles", ""), r["bat_source"], r["note"]] for r in ident]
    C_H = ["ID", "Instance", "Code INSEE (commune actuelle)", "Commune", "Code INSEE GASPAR", "Commune GASPAR",
           "N° CatNat", "Péril", "Début événement", "Fin événement", "Date arrêté", "Date JO"]
    S_H = ["ID", "Instance", "Péril", "Nombre de reconnaissances"]
    B_H = ["ID", "Instance", "Source"] + BAT_COLS + ["parcelle (DGFiP)", "nb_locaux", "droits (DGFiP)",
                                                    "dénomination propriétaire (DGFiP)"]

    tables = {"Instances enrichies": (I_H, I_R), "Synthèse CatNat": (S_H, synth),
              "Arrêtés CatNat": (C_H, cat_rows), "Bâtiments BDNB": (B_H, bat_rows)}
    for name, (h, rows) in tables.items():
        with open(os.path.join(OUT, name.replace(" ", "_") + ".csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(h); w.writerows(rows)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook(); wb.remove(wb.active)
        for name, (h, rows) in tables.items():
            ws = wb.create_sheet(name[:31]); ws.append(h)
            for row in rows: ws.append(row)
            for cell in ws[1]: cell.font = Font(bold=True)
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(ws.iter_cols(min_row=1, max_row=min(ws.max_row, 300)), 1):
                large = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, large + 2), 60)
                for c in col[1:]:
                    if isinstance(c.value, dt.date): c.number_format = "DD/MM/YYYY"
            for row in ws.iter_rows(min_row=2):
                for c in row:
                    if isinstance(c.value, dt.date): c.number_format = "DD/MM/YYYY"
        wb.save(os.path.join(OUT, "instances_enrichies.xlsx"))
        print(f"\nOK → {OUT}/instances_enrichies.xlsx")
    except ImportError:
        print(f"\nOK → CSV dans {OUT}/ (installer openpyxl pour le fichier .xlsx)")


if __name__ == "__main__":
    main()
