import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class GeocodeError(Exception):
    """Erreur levee lors d'une recherche d'adresse."""


def geocode_address(address, timeout=10):
    """
    Convertit une adresse texte en (latitude, longitude) via Nominatim
    (OpenStreetMap), gratuit et sans cle API. Respecte la politique d'usage
    de Nominatim (User-Agent identifiant l'app, usage occasionnel).

    Leve GeocodeError si l'adresse est vide, introuvable, ou en cas de
    probleme reseau.
    """

    if not address or not address.strip():
        raise GeocodeError("Adresse vide.")

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "solar-optimizer-fr/1.0 (usage communautaire non commercial)"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GeocodeError(f"Erreur reseau lors de la recherche d'adresse : {exc}") from exc

    if response.status_code != 200:
        raise GeocodeError(f"Service de geocodage indisponible ({response.status_code}).")

    try:
        results = response.json()
    except ValueError as exc:
        raise GeocodeError("Reponse invalide du service de geocodage.") from exc

    if not results:
        raise GeocodeError(
            "Adresse introuvable. Essaie d'etre plus precis (numero, rue, ville)."
        )

    first = results[0]
    return float(first["lat"]), float(first["lon"])
