import base64
import json
import re

from anthropic import Anthropic, APIError, APIConnectionError, AuthenticationError

DEFAULT_MODEL = "claude-sonnet-5"

EXTRACTION_PROMPT = """Tu recois une facture d'electricite (EDF ou autre fournisseur francais).
Extrais les informations suivantes et reponds UNIQUEMENT avec un objet JSON
valide (pas de texte avant/apres, pas de commentaire), avec exactement ces
cles. Mets `null` pour toute valeur absente ou illisible -- n'invente rien.

{
  "adresse": string ou null,          // adresse postale complete du point de livraison
  "point_de_livraison": string ou null, // PDL / PRM (identifiant Linky, 14 chiffres)
  "titulaire_nom": string ou null,     // nom/prenom, ou raison sociale si personne morale
  "titulaire_type": string ou null,    // "particulier" ou "professionnel"
  "numero_client": string ou null,
  "fournisseur": string ou null,
  "periode_debut": string ou null,     // date ISO (AAAA-MM-JJ) si trouvable
  "periode_fin": string ou null,       // date ISO (AAAA-MM-JJ) si trouvable
  "consommation_annuelle_kwh": nombre ou null,
  "puissance_souscrite_kva": nombre ou null,
  "option_tarifaire": string ou null,  // ex: Base, Heures Creuses/Pleines, Tempo
  "montant_ttc_eur": nombre ou null,
  "prix_moyen_kwh_eur": nombre ou null, // calcule si possible (montant / consommation)
  "autres_infos_utiles": object ou null, // tout autre champ pertinent trouve sur la facture
  "confiance": string ou null          // "haute", "moyenne" ou "basse" : ta confiance globale sur ces valeurs
}

Si la consommation annuelle n'est pas directement indiquee mais qu'une
consommation sur une autre periode l'est (ex: facture mensuelle, ou releve
sur 2 mois), essaie de l'annualiser et indique-le dans "autres_infos_utiles".
"""

PRODUCTION_EXTRACTION_PROMPT = """Tu recois un document (PDF, capture d'ecran ou export)
resumant la production annuelle d'une installation photovoltaique deja en
service -- typiquement issu d'une application de suivi d'onduleur (Enphase,
SolarEdge, Huawei, SMA...), d'un certificat de production, ou d'un bilan
annuel du gestionnaire de reseau. Le format peut varier enormement : adapte-toi.

Extrais les informations suivantes et reponds UNIQUEMENT avec un objet JSON
valide (pas de texte avant/apres, pas de commentaire), avec exactement ces
cles. Mets `null` pour toute valeur absente ou illisible -- n'invente rien.

{
  "production_annuelle_kwh": nombre ou null,   // production totale sur 12 mois
  "energie_exportee_kwh": nombre ou null,       // part revendue/injectee sur le reseau, si indiquee
  "puissance_installee_kwc": nombre ou null,
  "periode_debut": string ou null,              // date ISO (AAAA-MM-JJ) si trouvable
  "periode_fin": string ou null,
  "autres_infos_utiles": object ou null,
  "confiance": string ou null                   // "haute", "moyenne" ou "basse"
}

Si la production annuelle n'est pas directement indiquee mais qu'une
production sur une autre periode l'est (ex: releve mensuel ou trimestriel),
essaie de l'annualiser (somme sur 12 mois glissants ou extrapolation) et
indique-le dans "autres_infos_utiles".
"""


class InvoiceExtractionError(Exception):
    """Erreur levee lors de l'extraction de donnees depuis une facture
    (cle API invalide, probleme reseau, reponse non exploitable...)."""


def _guess_media_type(filename):
    ext = filename.lower().rsplit(".", 1)[-1] if filename and "." in filename else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }.get(ext, "application/pdf")


def _extract_json(text):
    """Parse la reponse du modele en JSON, en tolerant les blocs de code
    markdown (```json ... ```) et le texte parasite eventuel autour de
    l'objet JSON."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise InvoiceExtractionError(
        "Impossible d'interpreter la reponse de l'IA comme du JSON valide."
    )


def _call_extraction(file_bytes, filename, api_key, prompt, model=DEFAULT_MODEL, timeout=60.0):
    """
    Envoie un document (PDF ou image) a l'API Claude (Anthropic) avec le
    prompt d'extraction fourni, et renvoie le dict JSON obtenu. Leve
    InvoiceExtractionError avec un message clair en cas d'echec (cle
    invalide, reseau, reponse non exploitable).

    Aucune donnee n'est stockee cote Anthropic au-dela du traitement de la
    requete (comportement standard de l'API) ; le fichier n'est conserve
    que le temps de l'appel, dans la memoire du processus qui execute cette
    fonction.
    """
    if not api_key:
        raise InvoiceExtractionError("Aucune cle API Anthropic renseignee.")
    if not file_bytes:
        raise InvoiceExtractionError("Fichier vide ou illisible.")

    media_type = _guess_media_type(filename)
    b64_data = base64.b64encode(file_bytes).decode("ascii")
    block_type = "document" if media_type == "application/pdf" else "image"
    content_block = {
        "type": block_type,
        "source": {"type": "base64", "media_type": media_type, "data": b64_data},
    }

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [content_block, {"type": "text", "text": prompt}],
            }],
            timeout=timeout,
        )
    except AuthenticationError as exc:
        raise InvoiceExtractionError(
            f"Cle API Anthropic invalide ou refusee : {exc}"
        ) from exc
    except APIConnectionError as exc:
        raise InvoiceExtractionError(
            f"Erreur reseau lors de l'appel a l'API Anthropic : {exc}"
        ) from exc
    except APIError as exc:
        raise InvoiceExtractionError(f"Erreur de l'API Anthropic : {exc}") from exc

    text_parts = [
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    raw_text = "\n".join(text_parts).strip()
    if not raw_text:
        raise InvoiceExtractionError("Reponse vide de l'API Anthropic.")

    return _extract_json(raw_text)


def extract_invoice_data(file_bytes, filename, api_key, model=DEFAULT_MODEL, timeout=60.0):
    """
    Envoie une facture (PDF ou image) a l'API Claude (Anthropic) et renvoie
    un dict avec les champs extraits (voir EXTRACTION_PROMPT pour la liste
    exacte).
    """
    return _call_extraction(file_bytes, filename, api_key, EXTRACTION_PROMPT, model, timeout)


def extract_production_data(file_bytes, filename, api_key, model=DEFAULT_MODEL, timeout=60.0):
    """
    Envoie un releve/export de production annuelle (app de monitoring
    d'onduleur, certificat, bilan...) a l'API Claude et renvoie un dict avec
    les champs extraits (voir PRODUCTION_EXTRACTION_PROMPT). Complementaire a
    extract_invoice_data (qui porte sur la consommation, pas la production).
    """
    return _call_extraction(
        file_bytes, filename, api_key, PRODUCTION_EXTRACTION_PROMPT, model, timeout,
    )
