"""
Interface Streamlit pour le solveur de découpe de barres métalliques.
Lancer avec : streamlit run app.py
"""

import streamlit as st
import pandas as pd
from cutting_stock import Piece, solve_bfd, solve_optimal, summarize

st.set_page_config(page_title="Optimiseur de découpe métal", page_icon="🔩", layout="centered")

st.title("🔩 Optimiseur de découpe de barres métalliques")
st.caption("Minimise le nombre de barres utilisées et le déchet de matière.")

# --- Paramètres d'entrée ---
st.header("1. Paramètres")

bar_length = st.number_input(
    "Longueur de la barre standard (mm)", min_value=1, value=12000, step=1
)

st.subheader("2. Liste des pièces à découper")
st.caption("Ajoute une ligne par type de pièce : longueur (mm) et quantité nécessaire.")

if "pieces_df" not in st.session_state:
    st.session_state.pieces_df = pd.DataFrame(
        {"Label": ["Pièce A", "Pièce B"], "Longueur (mm)": [5000, 3000], "Quantité": [7, 6]}
    )

edited_df = st.data_editor(
    st.session_state.pieces_df,
    num_rows="dynamic",
    use_container_width=True,
    key="pieces_editor",
)

st.subheader("3. Méthode de résolution")
method = st.radio(
    "Choisir la méthode",
    options=["Rapide (heuristique BFD)", "Optimale (exacte, peut être plus lente)"],
    horizontal=False,
)

time_limit = 20
if method.startswith("Optimale"):
    time_limit = st.slider("Temps limite de calcul (secondes)", 5, 120, 20)

run = st.button("🚀 Calculer", type="primary")

if run:
    # Validation et conversion des données saisies
    df = edited_df.dropna()
    if df.empty:
        st.error("Ajoute au moins une pièce avant de calculer.")
        st.stop()

    pieces = []
    for _, row in df.iterrows():
        try:
            length = int(round(float(row["Longueur (mm)"])))
            qty = int(row["Quantité"])
            label = str(row["Label"]) if row["Label"] else f"{length}mm"
        except (ValueError, TypeError):
            st.error(f"Ligne invalide : {row.to_dict()}")
            st.stop()
        if length <= 0 or qty <= 0:
            st.error(f"Longueur et quantité doivent être positives (ligne : {row.to_dict()}).")
            st.stop()
        pieces.append(Piece(length=length, quantity=qty, label=label))

    try:
        with st.spinner("Calcul en cours..."):
            if method.startswith("Optimale"):
                bins = solve_optimal(bar_length, pieces, time_limit_s=time_limit)
            else:
                bins = solve_bfd(bar_length, pieces)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    except ModuleNotFoundError:
        st.error(
            "Le module 'ortools' n'est pas installé. Lance : pip install ortools"
        )
        st.stop()

    stats = summarize(bins)

    st.header("Résultat")
    col1, col2, col3 = st.columns(3)
    col1.metric("Nombre de barres", stats["nb_barres"])
    col2.metric("Déchet total (mm)", int(stats["dechet_total"]))
    col3.metric("Taux de déchet", f"{stats['taux_dechet_pct']} %")

    st.subheader("Détail par barre")
    rows = []
    for idx, b in enumerate(bins, 1):
        rows.append(
            {
                "Barre #": idx,
                "Pièces découpées": ", ".join(b.labels),
                "Matière utilisée (mm)": int(b.used),
                "Déchet (mm)": int(b.waste),
            }
        )
    result_df = pd.DataFrame(rows)
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    # Visualisation graphique simple de chaque barre
    st.subheader("Visualisation")
    for idx, b in enumerate(bins, 1):
        parts = []
        colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2", "#937860", "#DA8BC3"]
        html = f'<div style="display:flex;width:100%;height:28px;border:1px solid #ccc;margin-bottom:4px;">'
        for i, (cut, label) in enumerate(zip(b.cuts, b.labels)):
            pct = 100 * cut / b.capacity
            color = colors[i % len(colors)]
            html += (
                f'<div title="{label}: {int(cut)}mm" style="width:{pct}%;background:{color};'
                f'display:flex;align-items:center;justify-content:center;color:white;'
                f'font-size:11px;overflow:hidden;">{label}</div>'
            )
        waste_pct = 100 * b.waste / b.capacity
        if waste_pct > 0.5:
            html += (
                f'<div title="Déchet: {int(b.waste)}mm" style="width:{waste_pct}%;'
                f'background:repeating-linear-gradient(45deg,#eee,#eee 4px,#ddd 4px,#ddd 8px);"></div>'
            )
        html += "</div>"
        st.markdown(f"**Barre {idx}**", unsafe_allow_html=True)
        st.markdown(html, unsafe_allow_html=True)

    # Export CSV
    csv = result_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Télécharger le résultat (CSV)", csv, "resultat_decoupe.csv", "text/csv")
    
