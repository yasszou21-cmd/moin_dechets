"""
Interface Streamlit pour le solveur de découpe de barres métalliques.
Lancer avec : streamlit run app.py
"""

import streamlit as st
import pandas as pd
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from cutting_stock import Piece, solve_bfd, solve_optimal, solve_from_chutes, summarize

st.set_page_config(page_title="Optimiseur de découpe métal", page_icon="🔩", layout="centered")

st.title("🔩 Optimiseur de découpe de barres métalliques")

mode = st.radio(
    "Que veux-tu faire ?",
    ["🆕 Découper depuis des barres standard neuves", "♻️ Découper depuis un stock de chutes existant"],
    horizontal=False,
)

def generer_pdf(result_df, stats, unite_bin="Barre"):
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    elements = []

    elements.append(
        Paragraph("Résultat d'optimisation de découpe", styles["Title"])
    )
    elements.append(Spacer(1, 15))

    elements.append(
        Paragraph(
            f"Nombre de {unite_bin.lower()}s : {stats['nb_barres']}<br/>"
            f"Déchet total : {int(stats['dechet_total'])} mm<br/>"
            f"Taux de déchet : {stats['taux_dechet_pct']} %",
            styles["Normal"],
        )
    )

    elements.append(Spacer(1, 20))

    # Conversion du DataFrame en tableau PDF
    data = [list(result_df.columns)] + result_df.astype(str).values.tolist()

    table = Table(data, repeatRows=1)

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    elements.append(table)

    doc.build(elements)

    buffer.seek(0)
    return buffer.getvalue()
    
def afficher_resultat(bins, unite_bin="Barre"):
    """Affiche le tableau récapitulatif + la visualisation graphique + l'export CSV
    pour une liste de Bin — réutilisé par les deux modes."""
    stats = summarize(bins)

    st.header("Résultat")
    col1, col2, col3 = st.columns(3)
    col1.metric(f"Nombre de {unite_bin.lower()}s", stats["nb_barres"])
    col2.metric("Déchet total (mm)", int(stats["dechet_total"]))
    col3.metric("Taux de déchet", f"{stats['taux_dechet_pct']} %")

    st.subheader(f"Détail par {unite_bin.lower()}")
    rows = []
    for idx, b in enumerate(bins, 1):
        rows.append(
            {
                f"{unite_bin} #": idx,
                f"Longueur {unite_bin.lower()} (mm)": int(b.capacity),
                "Pièces découpées": ", ".join(b.labels) if b.labels else "—",
                "Matière utilisée (mm)": int(b.used),
                "Déchet (mm)": int(b.waste),
            }
        )
    result_df = pd.DataFrame(rows)
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    st.subheader("Visualisation")
    for idx, b in enumerate(bins, 1):
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
        st.markdown(f"**{unite_bin} {idx}** ({int(b.capacity)}mm)", unsafe_allow_html=True)
        st.markdown(html, unsafe_allow_html=True)

   pdf = generer_pdf(result_df, stats, unite_bin)

   st.download_button(
    "📥 Télécharger le résultat (PDF)",
    pdf,
    "resultat_decoupe.pdf",
    "application/pdf",
   )


def lire_pieces_depuis_editeur(df, nom_erreur="pièce"):
    """Convertit un data_editor (Label/Longueur/Quantité) en liste de Piece,
    avec validation. Retourne None si erreur (message déjà affiché)."""
    df = df.dropna()
    if df.empty:
        st.error(f"Ajoute au moins un(e) {nom_erreur} avant de calculer.")
        return None

    pieces = []
    for _, row in df.iterrows():
        try:
            length = int(round(float(row["Longueur (mm)"])))
            qty = int(row["Quantité"])
            label = str(row["Label"]) if row["Label"] else f"{length}mm"
        except (ValueError, TypeError):
            st.error(f"Ligne invalide : {row.to_dict()}")
            return None
        if length <= 0 or qty <= 0:
            st.error(f"Longueur et quantité doivent être positives (ligne : {row.to_dict()}).")
            return None
        pieces.append(Piece(length=length, quantity=qty, label=label))
    return pieces


# ============================================================
# MODE 1 : barre standard neuve (comportement original)
# ============================================================
if mode.startswith("🆕"):
    st.caption("Minimise le nombre de barres neuves utilisées et le déchet de matière.")

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
        pieces = lire_pieces_depuis_editeur(edited_df, "pièce")
        if pieces is None:
            st.stop()

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
            st.error("Le module 'ortools' n'est pas installé. Lance : pip install ortools")
            st.stop()

        afficher_resultat(bins, unite_bin="Barre")


# ============================================================
# MODE 2 : découpe depuis un stock de chutes existant (nouveau)
# ============================================================
else:
    st.caption(
        "Découpe des pièces à partir de chutes déjà en stock (longueurs et quantités "
        "différentes). Si tout n'est pas réalisable, propose le meilleur usage possible "
        "des chutes disponibles."
    )

    st.header("1. Stock de chutes disponibles")
    st.caption("Ajoute une ligne par chute : longueur (mm) et quantité disponible.")

    if "chutes_df" not in st.session_state:
        st.session_state.chutes_df = pd.DataFrame(
            {"Label": ["Chute A", "Chute B"], "Longueur (mm)": [3200, 1800], "Quantité": [4, 6]}
        )

    chutes_edited = st.data_editor(
        st.session_state.chutes_df,
        num_rows="dynamic",
        use_container_width=True,
        key="chutes_editor",
    )

    st.header("2. Pièces à découper")
    st.caption("Ajoute une ligne par type de pièce demandée : longueur (mm) et quantité nécessaire.")

    if "pieces_demande_df" not in st.session_state:
        st.session_state.pieces_demande_df = pd.DataFrame(
            {"Label": ["Pièce X", "Pièce Y"], "Longueur (mm)": [1200, 900], "Quantité": [5, 8]}
        )

    pieces_edited = st.data_editor(
        st.session_state.pieces_demande_df,
        num_rows="dynamic",
        use_container_width=True,
        key="pieces_demande_editor",
    )

    time_limit_chutes = st.slider("Temps limite de calcul (secondes)", 5, 120, 30)

    run_chutes = st.button("🚀 Calculer", type="primary", key="run_chutes")

    if run_chutes:
        chutes = lire_pieces_depuis_editeur(chutes_edited, "chute")
        pieces_demande = lire_pieces_depuis_editeur(pieces_edited, "pièce")
        if chutes is None or pieces_demande is None:
            st.stop()

        try:
            with st.spinner("Calcul en cours..."):
                resultat = solve_from_chutes(chutes, pieces_demande, time_limit_s=time_limit_chutes)
        except ModuleNotFoundError:
            st.error("Le module 'ortools' n'est pas installé. Lance : pip install ortools")
            st.stop()

        if resultat["feasible"]:
            st.success(
                "✅ Toute la demande peut être satisfaite avec les chutes disponibles. "
                "Voici la répartition qui minimise le déchet."
            )
        else:
            st.warning(
                "⚠️ Le stock de chutes ne suffit pas à satisfaire toute la demande. "
                "Voici la meilleure utilisation possible des chutes pour couper le "
                "maximum de pièces."
            )
            st.subheader("Manque par type de pièce")
            manque_rows = [
                {"Pièce": label, "Quantité manquante": manque}
                for label, manque in resultat["shortfall"].items()
            ]
            st.dataframe(pd.DataFrame(manque_rows), use_container_width=True, hide_index=True)

        if resultat["bins"]:
            afficher_resultat(resultat["bins"], unite_bin="Chute")
        else:
            st.info("Aucune chute n'a pu être utilisée avec les pièces demandées.")
