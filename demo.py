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
    import plotly.express as px

    from batiscol.scoring import ParametresScore, calculer_score

    return ParametresScore, calculer_score, mo, os, pd, px


@app.cell
def _(mo):
    mo.md("""
    # Bâti scolaire et risques climatiques

    Exposition des collèges et lycées publics à la chaleur chronique et aux crues,
    calculée avec [physrisk-lib](https://github.com/os-climate/physrisk) (OS-Climate / FINOS),
    pondérée par l'ancienneté de la dernière rénovation connue.
    """)
    return


@app.cell
def _(os, pd):
    def charger():
        chemin = os.environ.get("RESULTS_PATH")
        if not chemin and os.environ.get("HF_DATASET_REPO"):
            from huggingface_hub import hf_hub_download

            chemin = hf_hub_download(os.environ["HF_DATASET_REPO"], "resultats.parquet", repo_type="dataset")
        chemin = chemin or "data/resultats.parquet"
        return pd.read_parquet(chemin) if os.path.exists(chemin) else None

    brut = charger()
    return (brut,)


@app.cell
def _(brut, mo):
    mo.stop(
        brut is None,
        mo.callout(
            mo.md(
                "Aucun résultat trouvé. Matérialisez le pipeline "
                "(`dagster dev -m batiscol.definitions`), puis définissez `RESULTS_PATH` "
                "ou `HF_DATASET_REPO`."
            ),
            kind="warn",
        ),
    )
    mo.md(
        f"Scénarios : chaleur **{brut['scenario_chaleur'].iloc[0]}**, "
        f"inondation **{brut['scenario_inondation'].iloc[0]}**"
    )
    return


@app.cell
def _(brut, mo):
    TOUS = "Toutes"
    region = mo.ui.dropdown([TOUS, *sorted(brut["region"].dropna().unique())], value=TOUS, label="Région")
    type_etab = mo.ui.dropdown([TOUS, *sorted(brut["type"].dropna().unique())], value=TOUS, label="Type")
    renov_connues = mo.ui.checkbox(label="Seulement rénovations connues")
    poids_chaleur = mo.ui.slider(0, 1, step=0.05, value=0.6, label="Poids chaleur (inondation = 1 − poids)")
    seuil_chaleur = mo.ui.dropdown({"25 °C": 25, "30 °C": 30}, value="25 °C", label="Seuil de température moyenne")
    annee_recente = mo.ui.slider(1995, 2025, step=1, value=2010, label="Rénovation « récente » à partir de")
    mo.vstack(
        [
            mo.hstack([region, type_etab, renov_connues], justify="start"),
            mo.hstack([poids_chaleur, seuil_chaleur, annee_recente], justify="start"),
        ]
    )
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
    return (df,)


@app.cell
def _(df, mo):
    mo.stop(df.empty, mo.md("Aucun établissement pour ces filtres."))
    mo.hstack(
        [
            mo.stat(len(df), label="Établissements"),
            mo.stat(f"{df['score'].median():.1f}", label="Score médian"),
            mo.stat(f"{(df['donnees_renovation'] == 'connues').mean():.0%}", label="Rénovations connues"),
            mo.stat(int((df["inondation_m_rp100_futur"] > 0).sum()), label="En zone de crue centennale"),
        ]
    )
    return


@app.cell
def _(df, px):
    carte = px.scatter_map(
        df, lat="latitude", lon="longitude", color="score", size=df["score"].clip(lower=1),
        color_continuous_scale="YlOrRd", range_color=(0, 100), size_max=14, zoom=8,
        hover_name="nom", hover_data={"commune": True, "score": True, "latitude": False, "longitude": False},
        map_style="carto-positron", height=560,
    )
    carte.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    carte
    return


@app.cell
def _(df, mo):
    colonnes = {
        "score": "Score",
        "nom": "Établissement",
        "type": "Type",
        "commune": "Commune",
        "jours_tmoy_sup_25c_hist": "Jours Tmoy>25°C (hist.)",
        "jours_tmoy_sup_25c_futur": "Jours Tmoy>25°C (futur)",
        "inondation_m_rp100_futur": "Crue 100 ans (m)",
        "derniere_operation_annee": "Dernière opération",
        "derniere_operation_libelle": "Nature",
        "uai": "UAI",
    }
    mo.ui.table(
        df[[c for c in colonnes if c in df.columns]].rename(columns=colonnes).round(1),
        page_size=15,
        selection=None,
    )
    return


@app.cell
def _(mo):
    mo.accordion(
        {
            "Méthode et limites": mo.md(
                """
                **Score** = 100 × vulnérabilité × (poids chaleur × exposition chaleur
                + poids inondation × exposition inondation).

                - *Exposition chaleur* : rang centile, dans la sélection, du nombre de jours par an
                  où la température moyenne dépasse le seuil (physrisk-lib, CMIP6, 0,25°).
                - *Exposition inondation* : hauteur d'eau d'une crue fluviale centennale sans
                  protection (TU Delft, 100 m), plafonnée à 1 m.
                - *Vulnérabilité* : 0,3 si rénovation récente, 0,6 si intermédiaire (≥ 1990),
                  1,0 si ancienne ou inconnue.

                **Ce que le score ne mesure pas** : l'état réel des bâtiments (sanitaires,
                toitures, moisissures). Un score élevé signale un établissement à examiner.

                **Limites** : un seul modèle climatique, pas d'effet d'îlot de chaleur urbain,
                historique des rénovations disponible seulement pour le pilote Île-de-France.
                """
            )
        }
    )
    return


if __name__ == "__main__":
    app.run()
