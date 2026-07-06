import requests

BUILDING_INSIGHTS_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"


class SolarApiError(Exception):
    """Erreur levee lors d'un appel a Google Solar API (cle invalide, pas de
    batiment trouve, quota depasse, probleme reseau...)."""


def _latlng(obj):
    """Convertit un objet LatLng de l'API ({"latitude":.., "longitude":..})
    en tuple (lat, lon), ou None si absent/incomplet."""
    if not obj:
        return None
    lat = obj.get("latitude")
    lon = obj.get("longitude")
    if lat is None or lon is None:
        return None
    return (lat, lon)


def _bbox(obj):
    """Convertit un objet LatLngBox ({"sw": LatLng, "ne": LatLng}) en
    {"sw": (lat, lon), "ne": (lat, lon)}, ou None si absent/incomplet."""
    if not obj:
        return None
    sw = _latlng(obj.get("sw"))
    ne = _latlng(obj.get("ne"))
    if sw is None or ne is None:
        return None
    return {"sw": sw, "ne": ne}


def fetch_roof_segments(latitude, longitude, api_key,
                         required_quality="MEDIUM",
                         max_segments=4,
                         timeout=15):
    """
    Interroge Google Solar API (buildingInsights.findClosest) pour le
    batiment le plus proche des coordonnees donnees.

    Renvoie un dict :

        {
            "segments": [
                {
                    "tilt": <degres>, "azimuth": <degres>, "area": <m2>,
                    "center": (lat, lon) ou None,
                    "bbox": {"sw": (lat, lon), "ne": (lat, lon)} ou None,
                },
                ...
            ],
            "max_panels_count": <int ou None>,
            "panel_capacity_watts": <float ou None>,
            "panel_height_m": <float ou None>,
            "panel_width_m": <float ou None>,
            "max_array_area_m2": <float ou None>,
            "building_center": (lat, lon) ou None,
            "building_bbox": {"sw": (lat, lon), "ne": (lat, lon)} ou None,
        }

    - segments : pans de toiture tries par surface decroissante.
      - tilt (pitchDegrees) : 0 = plat, 90 = vertical. L'algorithme de
        segmentation de Google (base sur l'imagerie/LIDAR) peut se tromper
        legerement, notamment sur des toits plats, complexes ou de petite
        taille : ces valeurs restent a corriger manuellement si elles ne
        correspondent pas a ce qu'on observe sur la vue satellite.
      - azimuth (azimuthDegrees) : 0 = Nord, 90 = Est, 180 = Sud (meme
        convention que pvlib, aucune conversion necessaire).
      - area (areaMeters2) : surface reelle du pan (deja corrigee de
        l'inclinaison, pas la projection au sol).
      - center / bbox : position du pan, pour affichage sur une carte.
    - max_panels_count : nombre maximal de panneaux que Google estime
      pouvoir installer sur ce toit, avec SON propre panneau de reference
      (voir panel_capacity_watts / panel_height_m / panel_width_m) — pas
      forcement les memes dimensions que le panneau choisi dans le
      formulaire, donc a prendre comme un ordre de grandeur.
    - panel_capacity_watts : puissance unitaire (Wc) du panneau de
      reference utilise par Google pour ce calcul.
    - panel_height_m / panel_width_m : dimensions (m) de ce panneau de
      reference, en orientation portrait.
    - max_array_area_m2 : surface totale occupee par cette configuration
      maximale.
    - building_center / building_bbox : position et emprise du batiment
      detecte, pour verifier visuellement qu'il s'agit bien du bon
      batiment (Google cherche le batiment le plus proche du point donne,
      dans un rayon d'environ 50 m).

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
            "center": _latlng(seg.get("center")),
            "bbox": _bbox(seg.get("boundingBox")),
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
        "panel_height_m": solar_potential.get("panelHeightMeters"),
        "panel_width_m": solar_potential.get("panelWidthMeters"),
        "max_array_area_m2": solar_potential.get("maxArrayAreaMeters2"),
        "building_center": _latlng(data.get("center")),
        "building_bbox": _bbox(data.get("boundingBox")),
    }
