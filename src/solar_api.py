import requests

BUILDING_INSIGHTS_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"


class SolarApiError(Exception):
    """Erreur levee lors d'un appel a Google Solar API (cle invalide, pas de
    batiment trouve, quota depasse, probleme reseau...)."""


def fetch_roof_segments(latitude, longitude, api_key,
                         required_quality="MEDIUM",
                         max_segments=4,
                         timeout=15):
    """
    Interroge Google Solar API (buildingInsights.findClosest) pour le
    batiment le plus proche des coordonnees donnees.

    Renvoie un dict :

        {
            "segments": [{"tilt": <degres>, "azimuth": <degres>, "area": <m2>}, ...],
            "max_panels_count": <int ou None>,
            "panel_capacity_watts": <float ou None>,
            "max_array_area_m2": <float ou None>,
        }

    - segments : pans de toiture tries par surface decroissante.
      - tilt (pitchDegrees) : 0 = plat, 90 = vertical.
      - azimuth (azimuthDegrees) : 0 = Nord, 90 = Est, 180 = Sud (meme
        convention que pvlib, aucune conversion necessaire).
      - area (areaMeters2) : surface reelle du pan (deja corrigee de
        l'inclinaison, pas la projection au sol).
    - max_panels_count : nombre maximal de panneaux que Google estime
      pouvoir installer sur ce toit (avec son propre modele de panneau,
      voir panel_capacity_watts pour la puissance unitaire assumee).
    - panel_capacity_watts : puissance unitaire (Wc) du panneau de
      reference utilise par Google pour ce calcul.
    - max_array_area_m2 : surface totale occupee par cette configuration
      maximale.

    Leve SolarApiError avec un message clair en cas d'echec.
    """

    if not api_key:
        raise SolarApiError("Aucune cle API Google Solar renseignee.")

    params = {
        "location.latitude": latitude,
        "location.longitude": longitude,
        "requiredQuality": required_quality,
        "exactQualityRequired": "false",
        "key": api_key,
    }

    try:
        response = requests.get(BUILDING_INSIGHTS_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise SolarApiError(f"Erreur reseau lors de l'appel a Google Solar API : {exc}") from exc

    if response.status_code == 404:
        raise SolarApiError(
            "Aucun batiment trouve par Google Solar API a proximite de ces "
            "coordonnees (rayon d'environ 50 m). Verifie la latitude/longitude."
        )

    if response.status_code == 403:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        raise SolarApiError(
            f"Acces refuse par Google Solar API (403) : {detail}\n\n"
            "Causes les plus frequentes : facturation non activee sur le projet "
            "Google Cloud, API 'Solar API' non activee (APIs & Services > Library), "
            "ou cle restreinte (Application restrictions de type 'referrers HTTP', "
            "incompatible avec un appel serveur — utiliser 'None' ou une "
            "restriction par adresse IP a la place)."
        )

    if response.status_code != 200:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        raise SolarApiError(
            f"Google Solar API a renvoye une erreur ({response.status_code}) : {detail}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise SolarApiError("Reponse invalide (non-JSON) de Google Solar API.") from exc

    solar_potential = data.get("solarPotential", {})
    segments = solar_potential.get("roofSegmentStats", [])

    if not segments:
        raise SolarApiError(
            "Batiment trouve, mais aucun pan de toiture exploitable n'a ete "
            "detecte par Google Solar API pour cette adresse."
        )

    parsed = []
    for seg in segments:
        stats = seg.get("stats", {})
        area = stats.get("areaMeters2")
        tilt = seg.get("pitchDegrees")
        azimuth = seg.get("azimuthDegrees")

        if area is None or tilt is None or azimuth is None:
            continue

        parsed.append({
            "tilt": max(0.0, min(90.0, tilt)),
            "azimuth": max(0.0, min(360.0, azimuth)),
            "area": area,
        })

    if not parsed:
        raise SolarApiError(
            "Les pans de toiture retournes par Google Solar API sont incomplets "
            "(donnees manquantes)."
        )

    parsed.sort(key=lambda s: s["area"], reverse=True)

    return {
        "segments": parsed[:max_segments],
        "max_panels_count": solar_potential.get("maxArrayPanelsCount"),
        "panel_capacity_watts": solar_potential.get("panelCapacityWatts"),
        "max_array_area_m2": solar_potential.get("maxArrayAreaMeters2"),
    }
