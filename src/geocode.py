import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class GeocodeError(Exception):
    """Erreur levee lors d'une recherche d'adresse."""


def _query_nominatim(address, limit, timeout):

    if not address or not address.strip():
        raise GeocodeError("Adresse vide.")

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": limit, "addressdetails": 0},
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

    return results


def geocode_address(address, timeout=10):
    """
    Convertit une adresse texte en (latitude, longitude) via Nominatim
    (OpenStreetMap), gratuit et sans cle API. Ne renvoie que le meilleur
    resultat — voir search_addresses() pour obtenir plusieurs candidats.

    Leve GeocodeError si l'adresse est vide, introuvable, ou en cas de
    probleme reseau.
    """

    results = _query_nominatim(address, limit=1, timeout=timeout)
    first = results[0]
    return float(first["lat"]), float(first["lon"])


def search_addresses(address, limit=5, timeout=10):
    """
    Recherche une adresse et renvoie jusqu'a `limit` candidats, pour
    laisser l'utilisateur choisir le bon dans une liste (adresse ambigue,
    plusieurs communes du meme nom, etc.) :

        [{"label": <adresse complete>, "lat": <float>, "lon": <float>}, ...]

    Leve GeocodeError si l'adresse est vide, introuvable, ou en cas de
    probleme reseau.
    """

    results = _query_nominatim(address, limit=limit, timeout=timeout)

    candidates = []
    for r in results:
        try:
            candidates.append({
                "label": r.get("display_name", f"{r['lat']}, {r['lon']}"),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            })
        except (KeyError, ValueError):
            continue

    if not candidates:
        raise GeocodeError("Adresse introuvable. Essaie d'etre plus precis.")

    return candidates
