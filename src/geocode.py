import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class GeocodeError(Exception):
    """Erreur levee lors d'une recherche d'adresse."""


def _query_nominatim(address, limit, timeout, countrycodes="fr"):

    if not address or not address.strip():
        raise GeocodeError("Adresse vide.")

    params = {"q": address, "format": "json", "limit": limit, "addressdetails": 0}
    if countrycodes:
        # Biais France par defaut : cet outil cible des adresses francaises,
        # et Nominatim remonte parfois des homonymes a l'etranger en premier
        # sans cette restriction (retour utilisateur : "il ne se localise
        # pas a la bonne adresse").
        params["countrycodes"] = countrycodes

    try:
        response = requests.get(
            NOMINATIM_URL,
            params=params,
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

    if not results and countrycodes:
        # Repli : peut-etre une adresse hors France (DOM-TOM, erreur de
        # saisie...) -> on retente une fois sans restriction de pays plutot
        # que d'echouer tout de suite.
        return _query_nominatim(address, limit=limit, timeout=timeout, countrycodes=None)

    if not results:
        raise GeocodeError(
            "Adresse introuvable. Essaie d'etre plus precis (numero, rue, ville), "
            "ou avec juste \"rue + ville\" si l'adresse complete ne donne rien."
        )

    return results


def geocode_address(address, timeout=10, countrycodes="fr"):
    """
    Convertit une adresse texte en (latitude, longitude) via Nominatim
    (OpenStreetMap), gratuit et sans cle API. Ne renvoie que le meilleur
    resultat — voir search_addresses() pour obtenir plusieurs candidats.

    Par defaut, la recherche est biaisee vers la France (countrycodes="fr")
    pour de meilleurs resultats sur des adresses locales ; passer
    countrycodes=None pour desactiver ce biais.

    Leve GeocodeError si l'adresse est vide, introuvable, ou en cas de
    probleme reseau.
    """

    results = _query_nominatim(address, limit=1, timeout=timeout, countrycodes=countrycodes)
    first = results[0]
    return float(first["lat"]), float(first["lon"])


def search_addresses(address, limit=5, timeout=10, countrycodes="fr"):
    """
    Recherche une adresse et renvoie jusqu'a `limit` candidats, pour
    laisser l'utilisateur choisir le bon dans une liste (adresse ambigue,
    plusieurs communes du meme nom, etc.) :

        [{"label": <adresse complete>, "lat": <float>, "lon": <float>}, ...]

    Par defaut, la recherche est biaisee vers la France (countrycodes="fr")
    pour de meilleurs resultats sur des adresses locales ; passer
    countrycodes=None pour desactiver ce biais.

    Leve GeocodeError si l'adresse est vide, introuvable, ou en cas de
    probleme reseau.
    """

    results = _query_nominatim(address, limit=limit, timeout=timeout, countrycodes=countrycodes)

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
