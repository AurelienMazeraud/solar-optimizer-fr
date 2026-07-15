import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

# A completer/personnaliser avec les vraies coordonnees de l'association une
# fois constituee (adresse, SIRET, RIB...).
PMO_NAME = "Ivry Soleil Partage"
PMO_ADDRESS = "Adresse a completer -- Ivry-sur-Seine"

_LEGAL_CAVEAT = (
    "Document genere automatiquement -- modele indicatif a faire valider par "
    "un-e expert-comptable/juriste (regime de TVA applicable, mentions "
    "legales obligatoires, SIRET, echeance et modalites de paiement) avant "
    "tout envoi a caractere officiel."
)


def _base_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SmallGrey", parent=styles["Normal"], fontSize=8, textColor=colors.grey,
    ))
    return styles


def generate_consumer_invoice_pdf(period, line, pmo_name=PMO_NAME, pmo_address=PMO_ADDRESS):
    """
    Genere en memoire (bytes PDF) une facture consolidee "mandataire" pour
    un consommateur, pour la periode ('AAAA-MM') et la ligne de
    facturation donnees (dict issu de
    get_billing_period_detail(period)["consumers"]).

    Modele indicatif du montage "mandataire de facturation" (la PMO facture
    au nom et pour le compte des producteurs mandants) -- a faire valider
    par un-e expert-comptable/juriste avant tout envoi reel.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = _base_styles()
    story = []

    story.append(Paragraph(pmo_name, styles["Title"]))
    story.append(Paragraph(pmo_address, styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Facture -- periode {period}", styles["Heading2"]))
    story.append(Paragraph(
        "Facture emise par Ivry Soleil Partage, mandataire de facturation "
        "pour le compte des producteurs de l'operation d'autoconsommation "
        "collective, au nom et pour le compte des producteurs mandants, en "
        "application du mandat de facturation signe avec chaque producteur.",
        styles["SmallGrey"],
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Destinataire :</b> {line['name'] or '(sans nom)'}", styles["Normal"]))
    if line.get("address"):
        story.append(Paragraph(line["address"], styles["Normal"]))
    if line.get("email"):
        story.append(Paragraph(line["email"], styles["Normal"]))
    story.append(Spacer(1, 16))

    table_data = [
        ["Designation", "Quantite", "Montant"],
        [
            f"Electricite autoconsommee collectivement ({period})",
            f"{line['kwh_acc']:.1f} kWh",
            f"{line['amount_eur']:.2f} EUR",
        ],
    ]
    table = Table(table_data, colWidths=[9 * cm, 4 * cm, 4 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e7d32")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Montant total du : {line['amount_eur']:.2f} EUR</b>", styles["Normal"]))
    story.append(Spacer(1, 4))
    paid = bool(line.get("paid"))
    story.append(Paragraph(
        f"Statut : {'payee' if paid else 'en attente de paiement'}"
        + (f" (le {line['paid_at'][:10]})" if paid and line.get("paid_at") else ""),
        styles["Normal"],
    ))
    story.append(Spacer(1, 24))
    story.append(Paragraph(_LEGAL_CAVEAT, styles["SmallGrey"]))
    story.append(Paragraph(f"Genere le {date.today().isoformat()}.", styles["SmallGrey"]))

    doc.build(story)
    return buffer.getvalue()


def generate_producer_statement_pdf(period, line, pmo_name=PMO_NAME, pmo_address=PMO_ADDRESS):
    """
    Genere en memoire (bytes PDF) un releve de versement pour un
    producteur, pour la periode ('AAAA-MM') et la ligne donnees (dict issu
    de get_billing_period_detail(period)["producers"]).

    Ce n'est PAS une facture : dans le montage "mandataire", le producteur
    reste responsable de sa propre facturation le cas echeant -- ce
    document est un simple recapitulatif du montant reverse par la PMO au
    titre du mandat de facturation, a faire valider par un-e expert-
    comptable/juriste avant tout usage reel.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = _base_styles()
    story = []

    story.append(Paragraph(pmo_name, styles["Title"]))
    story.append(Paragraph(pmo_address, styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Releve de versement -- periode {period}", styles["Heading2"]))
    story.append(Paragraph(
        "Recapitulatif du montant reverse par Ivry Soleil Partage, "
        "mandataire de facturation, au titre de l'energie que vous avez "
        "produite et mise a disposition de l'operation d'autoconsommation "
        "collective sur la periode. Ce document ne constitue pas une "
        "facture : il reste de votre responsabilite d'etablir, le cas "
        "echeant, votre propre facture aupres de la PMO selon les termes "
        "du mandat de facturation signe.",
        styles["SmallGrey"],
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Producteur :</b> {line['name'] or '(sans nom)'}", styles["Normal"]))
    if line.get("address"):
        story.append(Paragraph(line["address"], styles["Normal"]))
    if line.get("email"):
        story.append(Paragraph(line["email"], styles["Normal"]))
    story.append(Spacer(1, 16))

    table_data = [
        ["Designation", "Quantite", "Montant"],
        [
            f"Production mise a disposition de l'ACC ({period})",
            f"{line['kwh_produced']:.1f} kWh",
            f"{line['amount_eur']:.2f} EUR",
        ],
    ]
    table = Table(table_data, colWidths=[9 * cm, 4 * cm, 4 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b5e20")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Montant total reverse : {line['amount_eur']:.2f} EUR</b>", styles["Normal"]))
    story.append(Spacer(1, 4))
    paid = bool(line.get("paid"))
    story.append(Paragraph(
        f"Statut : {'verse' if paid else 'en attente de versement'}"
        + (f" (le {line['paid_at'][:10]})" if paid and line.get("paid_at") else ""),
        styles["Normal"],
    ))
    story.append(Spacer(1, 24))
    story.append(Paragraph(_LEGAL_CAVEAT, styles["SmallGrey"]))
    story.append(Paragraph(f"Genere le {date.today().isoformat()}.", styles["SmallGrey"]))

    doc.build(story)
    return buffer.getvalue()
