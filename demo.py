# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "pandas>=2.2",
#     "pyarrow>=15",
#     "folium>=0.17",
#     "batiscol @ git+https://github.com/MarcoDamz/bati-scolaire-climat",
# ]
# ///
import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="medium",
    app_title="Bâti scolaire et risques climatiques",
)


@app.cell
def _():
    import os

    import marimo as mo
    import pandas as pd
    import folium
    from branca.colormap import LinearColormap

    from batiscol.scoring import ParametresScore, calculer_score

    return LinearColormap, ParametresScore, calculer_score, folium, mo, os, pd


@app.cell
def _(mo):
    mo.md("""
    # Bâti scolaire et risques climatiques

    **Quels collèges et lycées publics risquent le plus de souffrir du changement climatique,
    alors que leurs bâtiments n'ont pas été rénovés récemment ?**

    Cette page croise trois informations pour chaque établissement :

    1. **la chaleur** : combien de jours très chauds par an sont attendus vers le milieu du siècle ;
    2. **l'inondation** : quelle hauteur d'eau atteindrait une crue de rivière exceptionnelle ;
    3. **l'ancienneté des travaux** : quand a eu lieu la dernière rénovation connue.

    Elle en tire un **score de 0 à 100** : plus il est élevé, plus l'établissement mérite
    d'être examiné en priorité. Ce score sert à **trier**, pas à juger : il ne dit pas qu'un
    bâtiment est en mauvais état, il dit qu'il cumule une forte exposition climatique et
    des travaux anciens ou inconnus.

    **Comment lire la page :** les chiffres clés et la carte d'abord, puis le tableau des
    établissements, l'explication du score, des recommandations pour les élus, et enfin la
    méthode détaillée (sources, outil physrisk, scénarios, limites).
    """)
    return


@app.cell
def _(os):
    # Export statique (GitHub Pages) : pas de Python côté visiteur, les réglages sont figés.
    STATIQUE = os.environ.get("BATISCOL_STATIQUE") == "1"
    DEPOT = "https://github.com/MarcoDamz/bati-scolaire-climat"
    MOLAB = "https://molab.marimo.io/github/MarcoDamz/bati-scolaire-climat/blob/main/demo.py"
    # Résultats publiés par le workflow « pipeline » à côté de la page
    URL_RESULTATS = "https://marcodamz.github.io/bati-scolaire-climat/resultats.parquet"
    return DEPOT, MOLAB, STATIQUE, URL_RESULTATS


@app.cell
def _(URL_RESULTATS, os, pd):
    def charger():
        chemin = os.environ.get("RESULTS_PATH") or "data/resultats.parquet"
        if os.path.exists(chemin):
            return pd.read_parquet(chemin)
        try:  # molab ou poste sans données locales : version publiée
            return pd.read_parquet(URL_RESULTATS)
        except Exception:  # noqa: BLE001
            return None

    brut = charger()
    return (brut,)


@app.cell
def _():
    # Libellés grand public des scénarios utilisés par physrisk-lib.
    # Réchauffement mondial en fin de siècle (2081-2100 vs 1850-1900) : meilleures
    # estimations du 6e rapport du GIEC.
    SCENARIOS = {
        "ssp126": ("SSP1-2.6", "les émissions mondiales baissent fortement et rapidement",
                   "environ +1,8 °C en fin de siècle"),
        "ssp245": ("SSP2-4.5", "les émissions restent proches des politiques actuelles, "
                   "puis baissent lentement (scénario « intermédiaire »)",
                   "environ +2,7 °C en fin de siècle"),
        "ssp585": ("SSP5-8.5", "les émissions continuent d'augmenter fortement "
                   "(scénario « pessimiste »)", "environ +4,4 °C en fin de siècle"),
        "rcp4p5": ("RCP4.5", "émissions intermédiaires (ancienne génération de scénarios, "
                   "équivalent approché de SSP2-4.5)", "environ +2,5 °C en fin de siècle"),
        "rcp8p5": ("RCP8.5", "émissions très élevées (ancienne génération de scénarios, "
                   "équivalent approché de SSP5-8.5)", "environ +4,3 °C en fin de siècle"),
    }

    def decrire_scenario(texte: str) -> tuple[str, str, str, str]:
        """« ssp245 2050 » -> (code lisible, année, description, réchauffement)."""
        code, _, annee = str(texte).partition(" ")
        nom, desc, rechauffement = SCENARIOS.get(code, (code, "", ""))
        return nom, annee, desc, rechauffement

    return (decrire_scenario,)


@app.cell
def _(brut, decrire_scenario, mo):
    mo.stop(
        brut is None,
        mo.callout(
            mo.md(
                "Aucun résultat trouvé. Matérialisez le pipeline "
                "(`dagster dev -m batiscol.definitions`) ou définissez `RESULTS_PATH`."
            ),
            kind="warn",
        ),
    )
    _ch = decrire_scenario(brut["scenario_chaleur"].iloc[0])
    _in = decrire_scenario(brut["scenario_inondation"].iloc[0])
    mo.callout(
        mo.md(
            f"""
            **Quel futur est représenté ici ?** Personne ne sait quelle quantité de gaz à
            effet de serre l'humanité émettra : les climatologues calculent donc plusieurs
            futurs possibles, appelés *scénarios*.

            - **Chaleur : scénario {_ch[0]}, horizon {_ch[1]}** — {_ch[2]} ({_ch[3]} au niveau mondial).
            - **Inondation : scénario {_in[0]}, horizon {_in[1]}** — {_in[2]}.

            Les valeurs « futur » sont des moyennes sur une vingtaine d'années autour de
            l'horizon indiqué, pas une prévision pour une année précise. Le détail est dans
            la section *Méthode* en bas de page.
            """
        ),
        kind="neutral",
    )
    return


@app.cell
def _(brut, mo):
    TOUS = "Toutes"
    # Valeurs par défaut = paramètres de la méthode (ParametresScore)
    region = mo.ui.dropdown([TOUS, *sorted(brut["region"].dropna().unique())], value=TOUS, label="Région")
    type_etab = mo.ui.dropdown([TOUS, *sorted(brut["type"].dropna().unique())], value=TOUS, label="Type")
    renov_connues = mo.ui.checkbox(label="Seulement rénovations connues")
    poids_chaleur = mo.ui.slider(0, 1, step=0.05, value=0.6, label="Poids chaleur (inondation = 1 − poids)")
    seuil_chaleur = mo.ui.dropdown({"25 °C": 25, "30 °C": 30}, value="25 °C", label="Seuil de température moyenne")
    annee_recente = mo.ui.slider(1995, 2025, step=1, value=2010, label="Rénovation « récente » à partir de")
    return (
        TOUS,
        annee_recente,
        poids_chaleur,
        region,
        renov_connues,
        seuil_chaleur,
        type_etab,
    )


@app.cell
def _(
    DEPOT,
    MOLAB,
    STATIQUE,
    annee_recente,
    mo,
    poids_chaleur,
    region,
    renov_connues,
    seuil_chaleur,
    type_etab,
):
    if STATIQUE:
        _sortie = mo.callout(
            mo.md(
                f"Version statique, calculée avec les paramètres par défaut : poids chaleur "
                f"**{poids_chaleur.value}**, seuil **{seuil_chaleur.selected_key}**, rénovation "
                f"récente à partir de **{annee_recente.value}**. "
                f"[Ouvrir dans molab]({MOLAB}) pour modifier les réglages et lire le code, "
                f"ou consulter le [dépôt GitHub]({DEPOT}) pour le pipeline complet."
            ),
            kind="info",
        )
    else:
        _sortie = mo.vstack(
            [
                mo.hstack([region, type_etab, renov_connues], justify="start"),
                mo.hstack([poids_chaleur, seuil_chaleur, annee_recente], justify="start"),
            ]
        )
    _sortie
    return


@app.cell
def _(
    ParametresScore,
    TOUS,
    annee_recente,
    brut,
    calculer_score,
    poids_chaleur,
    region,
    renov_connues,
    seuil_chaleur,
    type_etab,
):
    # Le score est recalculé en direct : les paramètres de la méthode sont ceux du pipeline.
    p = ParametresScore(
        poids_chaleur=poids_chaleur.value,
        poids_inondation=round(1 - poids_chaleur.value, 2),
        colonne_chaleur=f"jours_tmoy_sup_{seuil_chaleur.value}c_futur",
        annee_renovation_recente=annee_recente.value,
    )
    df = brut
    if region.value != TOUS:
        df = df[df["region"] == region.value]
    if type_etab.value != TOUS:
        df = df[df["type"] == type_etab.value]
    df = calculer_score(df, p)
    if renov_connues.value:
        df = df[df["donnees_renovation"] == "connues"]
    return df, p


@app.cell
def _(df, mo, p):
    mo.stop(df.empty, mo.md("Aucun établissement pour ces filtres."))
    _seuil = p.colonne_chaleur.split("_")[3]  # « 25c »
    _hist = df[p.colonne_chaleur.replace("_futur", "_hist")].median()
    _futur = df[p.colonne_chaleur].median()
    mo.vstack(
        [
            mo.md("## Chiffres clés"),
            mo.hstack(
                [
                    mo.stat(len(df), label="Établissements"),
                    mo.stat(f"{df['score'].median():.1f}", label="Score médian (sur 100)"),
                    mo.stat(f"{_hist:.0f} → {_futur:.0f}",
                            label=f"Jours/an à Tmoy > {_seuil[:-1]} °C (médiane, passé → futur)"),
                    mo.stat(int((df["inondation_m_rp100_futur"] > 0).sum()), label="En zone de crue centennale"),
                    mo.stat(f"{(df['donnees_renovation'] == 'connues').mean():.0%}", label="Rénovations connues"),
                ]
            ),
            mo.md(
                "*Tmoy* = température **moyenne** de la journée, nuit comprise. Une journée à "
                "Tmoy > 25 °C est une journée caniculaire : après-midi souvent au-dessus de "
                "32 °C et nuit qui ne rafraîchit pas les bâtiments."
            ),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Carte

    Chaque point est un établissement. **Couleur et taille suivent le score** : petit et
    jaune = peu prioritaire, gros et rouge foncé = à examiner en premier. Survolez un point
    pour voir son nom ; zoomez avec la molette ou les boutons.
    """)
    return


@app.cell
def _(LinearColormap, df, folium, mo):
    # Leaflet (folium) : rendu fiable dans un export statique, sans WebGL.
    echelle = LinearColormap(["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"], vmin=0, vmax=100,
                             caption="Score")
    carte = folium.Map(
        location=[df["latitude"].mean(), df["longitude"].mean()],
        tiles="OpenStreetMap",
        zoom_start=9,
        control_scale=True,
    )
    for _r in df.sort_values("score").itertuples():
        folium.CircleMarker(
            location=[_r.latitude, _r.longitude],
            radius=4 + _r.score / 12,
            color=echelle(_r.score),
            fill=True,
            fill_opacity=0.85,
            weight=1,
            tooltip=f"{_r.nom} ({_r.commune}) — score {_r.score:.0f}",
        ).add_to(carte)
    echelle.add_to(carte)
    carte.fit_bounds([[df["latitude"].min(), df["longitude"].min()], [df["latitude"].max(), df["longitude"].max()]])
    mo.iframe(carte.get_root().render(), height="560px")
    return


@app.cell
def _(STATIQUE, df, mo):
    colonnes = {
        "score": "Score",
        "nom": "Établissement",
        "type": "Type",
        "commune": "Commune",
        "jours_tmoy_sup_25c_hist": "Jours Tmoy>25°C (passé)",
        "jours_tmoy_sup_25c_futur": "Jours Tmoy>25°C (futur)",
        "inondation_m_rp100_futur": "Crue 100 ans (m)",
        "derniere_operation_annee": "Dernière opération",
        "derniere_operation_libelle": "Nature",
        "uai": "UAI",
    }
    tableau = df[[c for c in colonnes if c in df.columns]].round(1)
    if "derniere_operation_annee" in tableau:
        tableau["derniere_operation_annee"] = tableau["derniere_operation_annee"].astype("Int64").astype(str).replace("<NA>", "–")
    tableau = tableau.rename(columns=colonnes)
    _intro = mo.md(
        """
        ## Établissements

        Classés du score le plus élevé au plus bas. **Jours Tmoy>25°C** : nombre moyen de
        journées caniculaires par an, sur la période passée de référence et à l'horizon
        futur. **Crue 100 ans** : hauteur d'eau au pied de l'établissement lors d'une crue
        qui a 1 chance sur 100 de survenir chaque année (0 = hors zone inondable).
        **Dernière opération** : année des derniers travaux connus (« – » = inconnu).
        **UAI** : identifiant officiel de l'établissement.
        """
    )
    if STATIQUE:
        # mo.ui.table charge ses pages via le kernel : rien ne s'affiche dans un export statique.
        _sortie = mo.vstack(
            [
                _intro,
                mo.md(f"**Les {min(50, len(tableau))} établissements au score le plus élevé**"),
                mo.Html(
                    tableau.head(50).to_html(index=False, na_rep="–", border=0)
                    .replace("<table", '<table style="border-collapse:collapse;font-size:13px;width:100%"')
                    .replace("<td>", '<td style="padding:4px 8px;border-bottom:1px solid #e5e7eb">')
                    .replace("<th>", '<th style="padding:4px 8px;text-align:left;border-bottom:2px solid #9ca3af">')
                ),
            ]
        )
    else:
        _sortie = mo.vstack([_intro, mo.ui.table(tableau, page_size=15, selection=None)])
    _sortie
    return


@app.cell
def _(df, mo, p):
    def _vuln_texte(r) -> str:
        if r.donnees_renovation == "inconnues":
            return "aucune rénovation connue → traité comme ancien (pire cas)"
        annee = int(r.derniere_operation_annee)
        if annee >= p.annee_renovation_recente:
            return f"dernière opération en {annee}, considérée comme récente"
        if annee >= p.annee_renovation_ancienne:
            return f"dernière opération en {annee}, d'ancienneté intermédiaire"
        return f"dernière opération en {annee}, considérée comme ancienne"

    def _fr(x, d=2) -> str:
        return f"{x:.{d}f}".replace(".", ",")

    _r = df.iloc[0]
    _seuil = p.colonne_chaleur.split("_")[3][:-1]
    _jours = _r[p.colonne_chaleur]
    _expo = p.poids_chaleur * _r.exposition_chaleur + p.poids_inondation * _r.exposition_inondation
    _n_prio = int((df["score"] >= 60).sum())
    _n_vig = int(((df["score"] >= 30) & (df["score"] < 60)).sum())
    _n_bas = int((df["score"] < 30).sum())

    mo.md(
        f"""
        ## Comment se calcule le score ?

        Le score répond à la question : *« cet établissement est-il à la fois très exposé
        au climat futur **et** doté d'un bâti peu ou pas rénové ? »*. Il combine deux notes :

        **1. Une note d'exposition, entre 0 et 1**, qui mélange chaleur et inondation :

        - **Chaleur** : on compte les journées caniculaires (Tmoy > {_seuil} °C) attendues à
          l'horizon futur, puis on regarde le **rang** de l'établissement parmi ceux affichés.
          0,80 signifie « plus de jours de chaleur que 80 % des établissements de la
          sélection ». C'est une mesure **relative** : elle change si l'on filtre une autre région.
        - **Inondation** : la hauteur d'eau de la crue centennale, ramenée entre 0 et 1
          (0 m → 0 ; {p.plafond_inondation_m:g} m ou plus → 1). Au-delà d'un mètre d'eau,
          les dégâts sont de toute façon majeurs.
        - Les deux sont additionnés avec des **poids** : {p.poids_chaleur:.0%} pour la
          chaleur, {p.poids_inondation:.0%} pour l'inondation, car la chaleur touche tous
          les établissements chaque année alors que la crue est rare et localisée.

        **2. Un coefficient de vulnérabilité du bâti**, selon la date des derniers travaux :

        | Dernière rénovation connue | Coefficient | Effet |
        |---|---|---|
        | {p.annee_renovation_recente} ou après | {_fr(p.vuln_recente, 1)} | le score est fortement réduit |
        | de {p.annee_renovation_ancienne} à {p.annee_renovation_recente - 1} | {_fr(p.vuln_intermediaire, 1)} | réduit |
        | avant {p.annee_renovation_ancienne}, ou inconnue | {_fr(p.vuln_ancienne_ou_inconnue, 1)} | inchangé |

        Un établissement sans information est traité comme non rénové : c'est un choix
        de prudence, qui fait remonter les établissements pour lesquels **on ne sait pas**.

        **Score = 100 × vulnérabilité × exposition.**

        ### Exemple : l'établissement en tête de liste

        **{_r.nom}** ({_r['commune']}) :

        - environ **{_jours:.0f} jours/an** à Tmoy > {_seuil} °C dans le futur → rang
          chaleur **{_fr(_r.exposition_chaleur)}** ;
        - crue centennale : **{_fr(_r.inondation_m_rp100_futur)} m** d'eau → note
          inondation **{_fr(_r.exposition_inondation)}** ;
        - exposition = {_fr(p.poids_chaleur)} × {_fr(_r.exposition_chaleur)} +
          {_fr(p.poids_inondation)} × {_fr(_r.exposition_inondation)} = **{_fr(_expo)}** ;
        - vulnérabilité **{_fr(_r.vulnerabilite, 1)}** ({_vuln_texte(_r)}) ;
        - score = 100 × {_fr(_r.vulnerabilite, 1)} × {_fr(_expo)} = **{_r.score:.0f}**.

        ### Comment interpréter les valeurs

        | Score | Lecture proposée | Établissements ici |
        |---|---|---|
        | 60 à 100 | **à examiner en priorité** : forte exposition et bâti ancien ou inconnu | {_n_prio} |
        | 30 à 60 | **vigilance** : exposition notable, ou bâti ancien mais exposition modérée | {_n_vig} |
        | 0 à 30 | **moins prioritaire** : faible exposition, ou rénovation récente | {_n_bas} |

        Ces seuils sont des repères de lecture, pas des normes. Un score au-dessus de 60
        n'est possible que si la rénovation est ancienne ou inconnue : un établissement
        rénové après {p.annee_renovation_recente} ne peut pas dépasser
        {100 * p.vuln_recente:.0f}.
        """
    )
    return


@app.cell
def _(df, mo, p):
    _n = len(df)
    _inconnues = (df["donnees_renovation"] == "inconnues").mean()
    _prio = df[df["score"] >= 60]
    _crue = df[df["inondation_m_rp100_futur"] > 0]
    _crue_forte = int((df["inondation_m_rp100_futur"] >= 0.5).sum())
    _delta = (df[p.colonne_chaleur] - df[p.colonne_chaleur.replace("_futur", "_hist")]).median()
    _seuil = p.colonne_chaleur.split("_")[3][:-1]
    _top = ", ".join(f"{r.nom} ({r.commune})" for r in df.head(5).itertuples())
    _types = set(df["type"].dropna())
    _qui = []
    if "Collège" in _types:
        _qui.append("les **conseils départementaux** pour les collèges")
    if "Lycée" in _types:
        _qui.append("les **conseils régionaux** pour les lycées")
    _qui_txt = " et ".join(_qui) or "les collectivités propriétaires"

    mo.md(
        f"""
        ## Recommandations pour les décideurs publics

        Ces pistes s'adressent d'abord aux collectivités propriétaires des bâtiments :
        {_qui_txt}. Elles s'appuient sur les résultats affichés ci-dessus
        ({_n} établissements, réglages actuels).

        **1. Combler d'abord le manque d'information sur le bâti.**
        Pour **{_inconnues:.0%}** des établissements, aucune rénovation n'est connue en
        données ouvertes. Tant que cette information manque, aucun classement, celui-ci
        compris, ne peut distinguer un bâtiment rénové d'un bâtiment vétuste. Publier un
        inventaire du patrimoine scolaire (année de construction, travaux réalisés, état
        de l'enveloppe, consommation d'énergie, températures relevées l'été) est une
        mesure peu coûteuse qui améliore toutes les décisions suivantes.

        **2. Lancer un diagnostic de terrain sur les établissements prioritaires.**
        {len(_prio)} établissements ont un score de 60 ou plus (en tête : {_top}). Ils
        méritent une visite technique : isolation et toiture, protections solaires,
        possibilité de ventiler la nuit, et **mesure des températures dans les salles**
        en juin et septembre, quand les élèves sont présents.

        **3. Préparer les établissements situés en zone inondable.**
        {len(_crue)} établissements seraient touchés par une crue centennale, dont
        {_crue_forte} avec 50 cm d'eau ou plus. Pour eux : vérifier le plan de prévention
        du risque inondation (PPRI) de la commune et la fiche Géorisques, mettre à jour le
        plan particulier de mise en sûreté (PPMS), et lors des travaux surélever les
        équipements sensibles (électricité, chaufferie, serveurs) et choisir des matériaux
        qui supportent l'eau.

        **4. Faire du confort d'été un critère de chaque rénovation.**
        Avec environ **{_delta:.0f} journées caniculaires de plus par an** (Tmoy > {_seuil} °C,
        en médiane), une rénovation pensée seulement pour l'hiver ne suffit plus. Privilégier
        dans cet ordre : protections solaires extérieures (volets, brise-soleil), isolation
        de la toiture, ventilation nocturne et brasseurs d'air, végétalisation et
        désimperméabilisation des cours (« cours oasis »). La climatisation, coûteuse et
        qui réchauffe l'extérieur, reste un dernier recours ciblé (salles de repos,
        infirmerie, salles d'examen).

        **5. Programmer sur plusieurs années, avec un scénario prudent.**
        Un bâtiment rénové aujourd'hui servira 30 à 50 ans. La trajectoire de
        réchauffement de référence pour l'adaptation (TRACC) retenue par l'État prévoit
        environ +2,7 °C en France dès 2050 et +4 °C en 2100 : il est donc raisonnable de
        tester aussi le scénario pessimiste (SSP5-8.5). Intégrer ce classement dans le
        plan pluriannuel d'investissement, en le combinant avec les obligations de baisse
        de consommation d'énergie du « décret tertiaire » (−40 % en 2030, −50 % en 2040,
        −60 % en 2050) pour faire d'une pierre deux coups, et mobiliser les financements
        dédiés au bâti scolaire.

        **6. Associer la communauté éducative et rendre compte.**
        Les équipes savent quelles salles sont invivables en juin. Recueillir leurs
        relevés, publier les critères de priorisation retenus et l'avancement des travaux
        permet de vérifier et corriger ce classement, et d'expliquer les choix aux familles.

        *Rappel : ce classement est un outil de tri pour décider où regarder en premier.
        Il ne remplace ni un diagnostic technique, ni la connaissance de terrain.*
        """
    )
    return


@app.cell
def _(mo):
    mo.vstack(
        [
            mo.md("## Méthode, sources et limites"),
            mo.accordion(
                {
                    "D'où viennent les données ?": mo.md(
                        """
                        Toutes les données sont **publiques et gratuites**.

                        | Information | Source | Producteur |
                        |---|---|---|
                        | Liste, type et position GPS des collèges et lycées publics | [Annuaire de l'éducation](https://data.education.gouv.fr/explore/dataset/fr-en-annuaire-education/) | Ministère de l'Éducation nationale |
                        | Travaux réalisés dans les lycées | [Opérations de construction et de rénovation dans les lycées franciliens](https://www.data.gouv.fr/fr/datasets/operations-de-construction-et-de-renovation-dans-les-lycees-francilens/) | Région Île-de-France |
                        | Jours de chaleur, actuels et futurs | Indicateurs d'aléas OS-Climate, lus avec physrisk-lib | Projections climatiques CMIP6 (communauté scientifique internationale) |
                        | Hauteur d'eau en cas de crue | Cartes européennes des crues de rivière, lues avec physrisk-lib | Université technique de Delft (TU Delft) |

                        **Point important :** l'historique des travaux n'existe en données
                        ouvertes que pour les lycées d'Île-de-France (projet pilote). Ailleurs,
                        et pour tous les collèges, la rénovation est « inconnue » et le score
                        repose uniquement sur l'exposition climatique.

                        Le calcul est refait automatiquement par un programme dont le code est
                        public (lien vers le dépôt GitHub plus haut) : chacun peut le vérifier
                        ou le relancer.
                        """
                    ),
                    "Qu'est-ce que physrisk et comment l'utilise-t-on ?": mo.md(
                        """
                        [physrisk-lib](https://github.com/os-climate/physrisk) est un outil
                        libre (open source) développé par **OS-Climate**, une initiative
                        aujourd'hui hébergée par la fondation FINOS (Linux Foundation). Il a été
                        conçu pour que banques, assureurs et investisseurs évaluent les
                        **risques physiques** du climat (chaleur, inondation, sécheresse,
                        vent…) qui pèsent sur des bâtiments ou des usines.

                        Il donne accès à des **cartes d'aléas déjà calculées** par des
                        scientifiques à partir de modèles climatiques, stockées sur un
                        serveur public. On lui donne une position (latitude, longitude), un
                        indicateur, un scénario et une année ; il renvoie la valeur au point
                        demandé.

                        **Ici, pour chaque établissement, on lui demande :**

                        1. le nombre moyen de jours par an où la température moyenne dépasse
                           25 °C, puis 30 °C (indicateur `days_tas/above/25c` et `30c`),
                           sur la période passée de référence et à l'horizon futur ;
                        2. la hauteur d'eau d'une crue de rivière pour plusieurs fréquences
                           (crue de 10 ans, 50 ans, 100 ans…), dont on retient la crue
                           centennale, passée et future.

                        physrisk sait aussi traduire ces aléas en **dommages financiers**
                        (pourcentage de perte de valeur d'un bâtiment). On ne s'en sert pas :
                        pour une école, « combien de jours de canicule » et « combien
                        d'eau » parlent davantage qu'un montant de perte, et ses courbes de
                        dommages ne sont pas conçues pour des bâtiments scolaires.
                        """
                    ),
                    "À quoi correspondent les scénarios climatiques ?": mo.md(
                        """
                        Le climat futur dépend des émissions de gaz à effet de serre à venir,
                        que personne ne connaît. Le GIEC (groupe d'experts du climat de
                        l'ONU) utilise donc des **scénarios** : des histoires cohérentes de
                        l'évolution du monde (population, économie, énergie), traduites en
                        émissions puis en climat par des modèles.

                        | Scénario | Ce qu'il suppose | Réchauffement mondial vers 2100* |
                        |---|---|---|
                        | **SSP1-2.6** | forte baisse rapide des émissions (proche de l'accord de Paris) | ≈ +1,8 °C |
                        | **SSP2-4.5** | poursuite des tendances actuelles (« intermédiaire ») | ≈ +2,7 °C |
                        | **SSP5-8.5** | forte hausse continue des émissions (« pessimiste ») | ≈ +4,4 °C |

                        *\\* par rapport à la fin du XIXe siècle ; la France métropolitaine se
                        réchauffe plus vite que la moyenne mondiale.*

                        Les **RCP4.5 et RCP8.5**, utilisés pour les crues, sont l'ancienne
                        génération de ces scénarios (jeu de cartes plus ancien) et
                        correspondent approximativement à SSP2-4.5 et SSP5-8.5.

                        **Horizons :** la chaleur est comparée entre une période de référence
                        centrée sur 2005 et l'horizon choisi (2030, 2040 ou 2050). Les crues
                        sont comparées entre une période centrée sur 1985 et une période
                        centrée sur 2085 (2071-2100). Chaque valeur est une **moyenne sur
                        environ 20 à 30 ans**, pas une prévision météo.

                        D'ici 2050, les scénarios divergent encore peu : les émissions déjà
                        passées dominent. C'est après 2050 que les choix d'aujourd'hui font
                        la différence.
                        """
                    ),
                    "Que veut dire « crue centennale » ?": mo.md(
                        """
                        Une crue **centennale** a **1 chance sur 100 de se produire chaque
                        année**. Ce n'est pas « une fois par siècle » : sur les 30 ans de vie
                        d'un bâtiment rénové, la probabilité d'en connaître au moins une est
                        d'environ **26 %**. C'est aussi la crue de référence des plans de
                        prévention du risque inondation (PPRI) en France, lorsqu'aucune crue
                        historique plus forte n'est connue.

                        Les cartes utilisées supposent **qu'aucune digue ne protège** le
                        site : elles surestiment donc le risque derrière des ouvrages de
                        protection efficaces. Elles ne couvrent que les **débordements de
                        rivière**, pas le ruissellement lors d'un orage violent, ni la
                        submersion marine.
                        """
                    ),
                    "Limites à garder en tête": mo.md(
                        """
                        - **L'état réel des bâtiments n'est pas mesuré** (isolation,
                          toiture, sanitaires, humidité) : il n'est pas disponible en données
                          ouvertes. Seule l'année des derniers travaux est utilisée, et
                          seulement pour le pilote Île-de-France.
                        - **Résolution grossière pour la chaleur** : une maille d'environ
                          25 km. Tous les établissements d'une même ville ont souvent la même
                          valeur, et l'**îlot de chaleur urbain** (béton, absence d'arbres)
                          n'est pas pris en compte, alors qu'il peut ajouter plusieurs degrés.
                        - **Un seul jeu de modèles climatiques** : l'incertitude entre
                          modèles n'est pas représentée.
                        - **Calendrier scolaire** : une partie des jours de canicule tombe en
                          juillet-août, quand les établissements sont fermés. Mais les
                          épisodes de juin (examens) et de septembre deviennent plus fréquents.
                        - **Score relatif** : la note de chaleur est un rang dans la
                          sélection affichée. Comparer des scores entre deux sélections
                          différentes n'a pas de sens.
                        - **Choix de pondération** : les poids et seuils sont des choix
                          raisonnés mais discutables. La version interactive (molab) permet de
                          les modifier pour voir si le classement tient.
                        """
                    ),
                    "Petit glossaire": mo.md(
                        """
                        - **Aléa** : phénomène naturel potentiellement dangereux (canicule, crue).
                        - **Exposition** : le fait d'être situé là où l'aléa se produit.
                        - **Vulnérabilité** : la fragilité face à l'aléa (ici, un bâti non
                          rénové supporte moins bien la chaleur).
                        - **Risque** = aléa × exposition × vulnérabilité.
                        - **CMIP6** : programme international qui coordonne les simulations
                          des modèles climatiques utilisées par le GIEC.
                        - **Tmoy** : température moyenne d'une journée, jour et nuit.
                        - **UAI** : unité administrative immatriculée, le numéro officiel
                          de chaque établissement scolaire.
                        - **TRACC** : trajectoire de réchauffement de référence pour
                          l'adaptation au changement climatique, fixée par l'État pour que
                          tous les acteurs se préparent au même climat futur.
                        """
                    ),
                }
            ),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
