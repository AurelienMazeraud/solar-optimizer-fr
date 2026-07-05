import math

import streamlit as st
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go

from src.config import load_config
from src.weather import load_weather
from src.pv import Roof
from src.house import House
from src.energy import EnergyBalance, Battery
from src.finance import Investment
from src.solar_api import fetch_roof_segments, SolarApiError
from src.geocode import geocode_address, search_addresses, GeocodeError


st.set_page_config(
    page_title="Calculateur solaire & autoconsommation",
    page_icon="☀️",
    layout="wide",
)

MAX_GRID_COLS = 10
MAX_GRID_ROWS = 12


@st.cache_data(show_spinner="Recuperation des donnees meteo (PVGIS)...", ttl=60 * 60 * 24)
def get_weather(lat, lon):
    return load_weather(lat, lon)


@st.cache_data(show_spinner="Interrogation de Google Solar API...", ttl=60 * 60 * 24)
def get_roof_segments(lat, lon, api_key):
    return fetch_roof_segments(lat, lon, api_key)


def load_defaults():
    try:
        return load_config("config/maison.yaml")
    except Exception:
        return None


def panel_grid_dims(width_m, height_m, panel_w, panel_h, orientation):
    """Nombre de colonnes/lignes de panneaux qui tiennent dans un pan de
    width_m x height_m, selon l'orientation choisie pour le panneau."""
    if orientation == "Paysage":
        eff_w, eff_h = panel_h, panel_w
    else:
        eff_w, eff_h = panel_w, panel_h
    cols = int(width_m // eff_w) if eff_w > 0 else 0
    rows = int(height_m // eff_h) if eff_h > 0 else 0
    return max(cols, 0), max(rows, 0)


def auto_distribute(desired_total, slot_counts):
    """Repartit desired_total panneaux entre plusieurs pans, au prorata des
    places disponibles (slot_counts), sans depasser la capacite de chacun."""
    total_slots = sum(slot_counts)
    if total_slots == 0:
        return [0] * len(slot_counts)
    desired_total = max(0, min(int(desired_total), total_slots))
    raw = [desired_total * s / total_slots for s in slot_counts]
    alloc = [min(int(r), s) for r, s in zip(raw, slot_counts)]
    remaining = desired_total - sum(alloc)
    order = sorted(
        range(len(slot_counts)),
        key=lambda i: (raw[i] - int(raw[i])),
        reverse=True,
    )
    guard = 0
    while remaining > 0 and guard < 10000:
        progressed = False
        for i in order:
            if remaining <= 0:
                break
            if alloc[i] < slot_counts[i]:
                alloc[i] += 1
                remaining -= 1
                progressed = True
        guard += 1
        if not progressed:
            break
    return alloc


cfg = load_defaults()

st.title("☀️ Calculateur d'efficacite de panneau solaire")
st.caption(
    "Simulation de production photovoltaique, autoconsommation, batterie et "
    "retour sur investissement, pour evaluer sa propre situation avant de "
    "rejoindre ou constituer une communaute d'autoconsommation collective."
)

with st.expander("ℹ️ Comment fonctionne ce simulateur ?"):
    st.markdown(
        "Cinq étapes : **1)** situer sa maison sur la carte, **2)** choisir un "
        "modèle de panneau, **3)** placer les panneaux sur chaque pan de toit, "
        "**4)** décrire sa consommation et son financement, **5)** lire les "
        "résultats (énergie et argent). Chaque section a son propre encadré "
        "d'explication — pas besoin de connaissances techniques en amont."
    )

# ------------------------------------------------------------------
# Localisation : recherche d'adresse (avec suggestions a choisir) +
# carte interactive + champs precis. En dehors du formulaire pour une
# mise a jour immediate (les widgets dans un st.form ne redeclenchent
# pas de calcul avant validation).
# ------------------------------------------------------------------
st.subheader("\U0001F4CD Localisation")

with st.expander("ℹ️ Pourquoi ces informations ?"):
    st.markdown(
        "La quantité de soleil reçue dépend de l'endroit où l'on se trouve "
        "(latitude/longitude) : plus on est au sud en France, plus l'ensoleillement "
        "annuel est important. L'altitude influence légèrement la production "
        "(air plus clair en altitude, mais aussi plus froid, ce qui améliore "
        "un peu le rendement des panneaux). Ces trois valeurs servent à "
        "interroger la base météo européenne PVGIS pour reconstituer une "
        "année type heure par heure."
    )

default_lat = float(cfg["site"]["latitude"]) if cfg else 48.815
default_lon = float(cfg["site"]["longitude"]) if cfg else 2.385

current_lat = st.session_state.get("lat", default_lat)
current_lon = st.session_state.get("lon", default_lon)

st.caption(
    "Tape une adresse puis choisis-la dans la liste, ou clique directement "
    "sur la carte pour placer le point sur ta maison — les champs "
    "latitude/longitude se mettent à jour automatiquement, et **dès qu'une "
    "position est choisie, la détection du toit se lance toute seule** "
    "(section ci-dessous) si une clé API est configurée. Remarque : un vrai "
    "glisser-déposer de la punaise n'est pas fiable dans les cartes "
    "interactives utilisées ici — cliquer directement au bon endroit fait "
    "la même chose en un seul geste."
)

address = st.text_input(
    "Rechercher une adresse", placeholder="ex : 12 rue de la Paix, Paris",
)

if address and address != st.session_state.get("_last_geocoded_query"):
    st.session_state["_last_geocoded_query"] = address
    try:
        st.session_state["_address_candidates"] = search_addresses(address, limit=5)
    except GeocodeError as exc:
        st.session_state["_address_candidates"] = []
        st.warning(str(exc))

candidates = st.session_state.get("_address_candidates", [])
if candidates:
    labels = [c["label"] for c in candidates]
    choice = st.selectbox(
        "Résultats trouvés — sélectionne la bonne adresse",
        labels, index=None, placeholder="Choisis une adresse...",
        key="_address_choice",
    )
    if choice:
        selected = candidates[labels.index(choice)]
        selected_point = (selected["lat"], selected["lon"])
        if st.session_state.get("_last_address_applied") != selected_point:
            st.session_state["_last_address_applied"] = selected_point
            st.session_state["lat"], st.session_state["lon"] = selected_point
            current_lat, current_lon = selected_point

location_map = folium.Map(location=[current_lat, current_lon], zoom_start=19)
folium.CircleMarker(
    location=[current_lat, current_lon],
    radius=9, color="#d62728", weight=2,
    fill=True, fill_color="#d62728", fill_opacity=0.85,
    tooltip="Position actuelle — clique ailleurs pour la déplacer",
).add_to(location_map)
map_state = st_folium(location_map, height=350, width=None, key="location_map")

clicked = map_state.get("last_clicked") if map_state else None
if clicked:
    click_point = (round(clicked["lat"], 6), round(clicked["lng"], 6))
    if st.session_state.get("_last_map_click") != click_point:
        st.session_state["_last_map_click"] = click_point
        st.session_state["lat"], st.session_state["lon"] = click_point
        current_lat, current_lon = click_point

c1, c2, c3 = st.columns(3)
lat = c1.number_input(
    "Latitude", min_value=-90.0, max_value=90.0,
    value=current_lat, format="%.4f", key="lat",
)
lon = c2.number_input(
    "Longitude", min_value=-180.0, max_value=180.0,
    value=current_lon, format="%.4f", key="lon",
)
altitude = c3.number_input(
    "Altitude (m)", min_value=0.0, max_value=4000.0,
    value=float(cfg["site"]["altitude"]) if cfg else 45.0,
)

# ------------------------------------------------------------------
# Repérage automatique du toit : se declenche tout seul des que la
# position (lat, lon) change, sans bouton a cliquer — un bouton de
# secours reste disponible pour forcer une nouvelle tentative.
# ------------------------------------------------------------------
with st.expander("\U0001F50E Repérage automatique du toit (Google Solar API, optionnel)", expanded=True):
    st.caption(
        "Dès qu'une position est choisie ci-dessus (adresse ou clic sur la "
        "carte), l'inclinaison, l'azimut et la surface de chaque pan de "
        "toiture sont récupérés automatiquement. 10 000 requêtes gratuites "
        "par mois chez Google — largement suffisant pour un usage ponctuel."
    )

    server_key = ""
    try:
        server_key = st.secrets.get("GOOGLE_SOLAR_API_KEY", "")
    except Exception:
        server_key = ""

    if server_key:
        # Cle configuree cote serveur (secrets.toml ou secrets Streamlit
        # Community Cloud) : on l'utilise directement, sans jamais la
        # mettre dans un widget que les visiteurs pourraient inspecter.
        api_key = server_key
        st.caption("✅ Clé API configurée côté serveur (non visible des visiteurs).")
    else:
        st.warning(
            "Aucune clé configurée côté serveur. Le champ ci-dessous est "
            "uniquement pour un test local : ne l'utilise jamais sur une "
            "app publique, la valeur saisie resterait visible/inspectable "
            "par n'importe quel visiteur de la page.",
            icon="⚠️",
        )
        api_key = st.text_input(
            "Clé API Google Solar (test local uniquement)",
            value="",
            type="password",
            help="Pour un usage durable/deploye, stocke plutot la cle dans "
                 "`.streamlit/secrets.toml` (GOOGLE_SOLAR_API_KEY = \"...\") — "
                 "ce fichier est deja exclu du depot Git.",
        )

    lookup_signature = (round(lat, 5), round(lon, 5), api_key)
    force_retry = st.button("🔄 Relancer la détection du toit")
    should_lookup = api_key and (
        force_retry or st.session_state.get("_last_solar_lookup") != lookup_signature
    )

    if not api_key:
        st.caption(
            "Renseigne une clé (ci-dessus, ou dans secrets.toml) pour activer "
            "la détection automatique."
        )
    elif should_lookup:
        st.session_state["_last_solar_lookup"] = lookup_signature
        try:
            result = get_roof_segments(lat, lon, api_key)
        except SolarApiError as exc:
            st.error(str(exc))
        else:
            segments = result["segments"]
            n_found = len(segments)
            st.session_state["n_sections"] = min(max(n_found, 1), 4)
            for i, seg in enumerate(segments):
                st.session_state[f"tilt_{i}"] = int(round(seg["tilt"]))
                st.session_state[f"az_{i}"] = int(round(seg["azimuth"]))
                # Google ne fournit que la surface du pan, pas sa forme :
                # on approxime par un carre, a ajuster manuellement si les
                # dimensions reelles sont connues (plan de toiture, mesure).
                side = math.sqrt(max(seg["area"], 1.0))
                st.session_state[f"width_{i}"] = round(side, 1)
                st.session_state[f"height_{i}"] = round(side, 1)

            st.success(
                f"{n_found} pan(s) de toiture detecte(s) et pre-remplis "
                "ci-dessous (inclinaison, azimut ; largeur/hauteur approximees "
                "en carré à partir de la surface — à ajuster si besoin)."
            )

            max_panels = result.get("max_panels_count")
            panel_w = result.get("panel_capacity_watts")
            panel_h_m = result.get("panel_height_m")
            panel_w_m = result.get("panel_width_m")
            if max_panels:
                ref_bits = []
                if panel_w:
                    ref_bits.append(f"{panel_w:.0f} Wc")
                if panel_h_m and panel_w_m:
                    ref_bits.append(f"{panel_h_m:.2f} × {panel_w_m:.2f} m")
                ref = f" (panneau de référence Google : {', '.join(ref_bits)})" if ref_bits else ""
                st.info(
                    f"📐 Estimation Google : jusqu'à **{max_panels} panneaux** "
                    f"installables sur ce toit{ref}. Si tes panneaux ont des "
                    "dimensions différentes (voir section ci-dessous), le nombre "
                    "réel peut varier — le calcul de production utilise bien tes "
                    "propres dimensions, pas celles de Google."
                )
    else:
        st.caption("Position déjà analysée pour cette clé — clique sur 🔄 pour relancer.")

# ------------------------------------------------------------------
# Modules PV : la taille du panneau doit etre connue AVANT de dessiner
# la grille de placement sur chaque pan.
# ------------------------------------------------------------------
st.subheader("\U0001F527 Modules photovoltaïques")

with st.expander("ℹ️ Pourquoi ces informations ?"):
    st.markdown(
        "La **puissance crête (Wc)** est la puissance maximale du panneau "
        "dans des conditions de test standard (plein soleil, 25°C) — en "
        "usage réel, la production est toujours un peu inférieure. Les "
        "**dimensions** (largeur/hauteur) déterminent combien de panneaux "
        "tiennent physiquement sur chaque pan de toit. Le **performance "
        "ratio** regroupe les pertes réelles (câblage, échauffement, "
        "salissures, ombrage partiel...) — 0.85 est une valeur courante en "
        "France. Le **rendement onduleur** est la perte de conversion du "
        "courant continu (panneaux) vers le courant alternatif (maison) : "
        "environ 0.97 pour un onduleur récent."
    )

c1, c2, c3, c4 = st.columns(4)
panel_power = c1.number_input(
    "Puissance unitaire (Wc)", min_value=100, max_value=700,
    value=int(cfg["pv"]["panel_power"]) if cfg else 640,
)
panel_width = c2.number_input(
    "Largeur panneau (m)", min_value=0.5, max_value=3.0,
    value=float(cfg["pv"]["panel_width"]) if cfg else 1.134,
)
panel_height = c3.number_input(
    "Hauteur panneau (m)", min_value=0.5, max_value=3.0,
    value=float(cfg["pv"]["panel_height"]) if cfg else 2.382,
)
c1, c2 = st.columns(2)
performance_ratio = c1.slider(
    "Performance ratio (pertes systeme : cablage, temperature, salissures...)",
    0.5, 1.0, float(cfg["pv"]["performance_ratio"]) if cfg else 0.86,
)
inverter_efficiency = c2.slider(
    "Rendement onduleur",
    0.8, 1.0, float(cfg["pv"]["inverter_efficiency"]) if cfg else 0.97,
)
panel_power_kw = panel_power / 1000

# ------------------------------------------------------------------
# Toiture(s) : geometrie de chaque pan + grille cliquable de panneaux.
# En dehors du st.form pour que les clics sur la grille reagissent
# immediatement.
# ------------------------------------------------------------------
st.subheader("\U0001F3E0 Toiture(s) & placement des panneaux")

with st.expander("ℹ️ Pourquoi ces informations ?"):
    st.markdown(
        "**Inclinaison** : 0° = toit plat, 90° = mur vertical (la plupart "
        "des toits français sont entre 15° et 45°). **Azimut** : 0° = Nord, "
        "90° = Est, 180° = Sud, 270° = Ouest — un pan plein Sud reçoit "
        "généralement le plus de soleil sur l'année. **Largeur/hauteur du "
        "pan** servent à calculer combien de panneaux tiennent physiquement "
        "dessus, en fonction de leur taille et de leur orientation "
        "(portrait ou paysage). Ensuite, choisis toi-même **combien de "
        "panneaux tu veux installer** et **comment les répartir** entre les "
        "pans, en cliquant directement sur la grille ci-dessous — chaque "
        "case cliquée représente un panneau réellement posé et compté dans "
        "la simulation."
    )

n_sections = st.number_input(
    "Nombre de pans de toiture exploités",
    min_value=1, max_value=4, value=2, step=1,
    key="n_sections",
)

defaults_roof = []
if cfg:
    for key_name in ("southwest", "northeast"):
        r = cfg.get("roof", {}).get(key_name, {})
        area = r.get("area", 20)
        side = round(math.sqrt(max(area, 1.0)), 1)
        defaults_roof.append((r.get("tilt", 15), r.get("azimuth", 180), side, side))
while len(defaults_roof) < 4:
    defaults_roof.append((15, 180, 4.5, 4.5))

section_geoms = []
for i in range(int(n_sections)):
    st.markdown(f"**Pan {i + 1} — géométrie**")
    gc1, gc2, gc3, gc4 = st.columns(4)
    tilt = gc1.number_input(
        "Inclinaison (°)", min_value=0, max_value=90,
        value=int(defaults_roof[i][0]), key=f"tilt_{i}",
    )
    azimuth = gc2.number_input(
        "Azimut (°)", min_value=0, max_value=360,
        value=int(defaults_roof[i][1]), key=f"az_{i}",
        help="0=Nord, 90=Est, 180=Sud, 270=Ouest",
    )
    width_m = gc3.number_input(
        "Largeur du pan (m)", min_value=0.5, max_value=30.0,
        value=float(defaults_roof[i][2]), step=0.1, key=f"width_{i}",
    )
    height_m = gc4.number_input(
        "Hauteur du pan (m)", min_value=0.5, max_value=30.0,
        value=float(defaults_roof[i][3]), step=0.1, key=f"height_{i}",
    )
    orientation = st.radio(
        "Orientation des panneaux sur ce pan",
        ["Portrait", "Paysage"], index=0, horizontal=True, key=f"orient_{i}",
    )
    cols_count, rows_count = panel_grid_dims(
        width_m, height_m, panel_width, panel_height, orientation
    )
    capped_cols = min(cols_count, MAX_GRID_COLS)
    capped_rows = min(rows_count, MAX_GRID_ROWS)
    section_geoms.append({
        "tilt": tilt, "azimuth": azimuth, "width": width_m, "height": height_m,
        "cols": cols_count, "rows": rows_count,
        "display_cols": capped_cols, "display_rows": capped_rows,
    })
    if cols_count == 0 or rows_count == 0:
        st.warning(
            "Aucun panneau ne tient sur ce pan avec ces dimensions — "
            "augmente la largeur/hauteur ou réduis la taille du panneau."
        )
    elif cols_count > MAX_GRID_COLS or rows_count > MAX_GRID_ROWS:
        st.caption(
            f"Pan capable d'accueillir {cols_count * rows_count} panneaux "
            f"({cols_count}×{rows_count}) — affichage limité à "
            f"{capped_cols}×{capped_rows} cases pour rester lisible."
        )
    st.divider()

total_slots = [g["display_cols"] * g["display_rows"] for g in section_geoms]

st.markdown("**Combien de panneaux veux-tu installer au total ?**")
dc1, dc2 = st.columns([2, 1])
desired_total_panels = dc1.number_input(
    "Nombre de panneaux souhaité (total)",
    min_value=0, max_value=max(sum(total_slots), 1),
    value=min(20, sum(total_slots)) if sum(total_slots) else 0,
    step=1,
)
if dc2.button("Répartir automatiquement sur les pans", use_container_width=True):
    alloc = auto_distribute(desired_total_panels, total_slots)
    for i, geom in enumerate(section_geoms):
        n_to_fill = alloc[i]
        idx = 0
        for r in range(geom["display_rows"]):
            for c in range(geom["display_cols"]):
                key = f"cell_{i}_{r}_{c}"
                st.session_state[key] = idx < n_to_fill
                idx += 1

st.markdown("**Clique sur les cases pour poser ou retirer un panneau, pan par pan :**")

roof_sections = []
for i, geom in enumerate(section_geoms):
    st.markdown(f"**Pan {i + 1} — placement** ({geom['cols']}×{geom['rows']} places possibles)")
    if geom["display_cols"] and geom["display_rows"]:
        bcol1, bcol2, _ = st.columns([1, 1, 3])
        if bcol1.button("Tout remplir", key=f"fill_{i}", use_container_width=True):
            for r in range(geom["display_rows"]):
                for c in range(geom["display_cols"]):
                    st.session_state[f"cell_{i}_{r}_{c}"] = True
        if bcol2.button("Tout vider", key=f"clear_{i}", use_container_width=True):
            for r in range(geom["display_rows"]):
                for c in range(geom["display_cols"]):
                    st.session_state[f"cell_{i}_{r}_{c}"] = False

        for r in range(geom["display_rows"]):
            row_cols = st.columns(geom["display_cols"])
            for c in range(geom["display_cols"]):
                key = f"cell_{i}_{r}_{c}"
                active = st.session_state.get(key, False)
                label = "🟦" if active else "⬜"
                if row_cols[c].button(label, key=f"btn_{key}", use_container_width=True):
                    st.session_state[key] = not active

    n_selected = sum(
        1
        for r in range(geom["display_rows"])
        for c in range(geom["display_cols"])
        if st.session_state.get(f"cell_{i}_{r}_{c}", False)
    )
    st.caption(f"{n_selected} panneau(x) sélectionné(s) sur ce pan.")
    roof_sections.append({
        "tilt": geom["tilt"], "azimuth": geom["azimuth"], "n_panels": n_selected,
    })
    st.divider()

total_panels_selected = sum(s["n_panels"] for s in roof_sections)
total_installed_kw = total_panels_selected * panel_power_kw
st.metric(
    "Total sélectionné",
    f"{total_panels_selected} panneaux — {total_installed_kw:.1f} kWc",
)

# ------------------------------------------------------------------
# Le reste (consommation, batterie, financement, tarifs) n'a pas besoin
# de reactivite immediate : ca reste dans un st.form valide par un
# bouton "Calculer".
# ------------------------------------------------------------------
with st.form("simulation"):

    st.subheader("\U0001F50C Consommation du foyer")
    with st.expander("ℹ️ Pourquoi ces informations ?"):
        st.markdown(
            "Le profil de consommation est reconstitué heure par heure à "
            "partir de quelques briques simples : une **charge de base** "
            "(éclairage, électroménager, veille), un **chauffe-eau** (souvent "
            "programmé la nuit ou en heures creuses), une **pompe à chaleur** "
            "(chauffage, avec un COP qui multiplie l'électricité consommée en "
            "chaleur produite), et un **véhicule électrique**. Plus la "
            "consommation coïncide avec les heures de production solaire "
            "(milieu de journée), plus le taux d'autoconsommation est élevé — "
            "c'est tout l'intérêt de décaler certains usages (lave-linge, "
            "recharge du véhicule...) vers la journée."
        )
    c1, c2, c3, c4 = st.columns(4)
    base_load_kw = c1.number_input("Charge de base (kW)", 0.0, 5.0, 0.35, step=0.05)
    include_wh = c2.checkbox("Chauffe-eau electrique", value=True)
    include_hp = c3.checkbox("Pompe a chaleur", value=True)
    include_ev = c4.checkbox("Vehicule electrique", value=True)
    annual_target = st.number_input(
        "Consommation annuelle connue (kWh) — laisser a 0 pour garder le profil "
        "modelise tel quel, sinon le profil est recale sur cette valeur "
        "(ex: releve de compteur Linky)",
        min_value=0, max_value=50000, value=0, step=100,
    )

    st.subheader("\U0001F50B Batterie (optionnel)")
    with st.expander("ℹ️ Pourquoi ces informations ?"):
        st.markdown(
            "Une batterie stocke le surplus produit en journée pour le "
            "restituer le soir : elle augmente mécaniquement le taux "
            "d'autoconsommation, mais a un coût d'achat et un **rendement "
            "aller-retour** imparfait (une partie de l'énergie stockée est "
            "perdue en chaleur). Laisser la capacité à 0 revient à simuler "
            "une installation sans batterie."
        )
    c1, c2, c3, c4 = st.columns(4)
    battery_capacity = c1.number_input(
        "Capacite utile (kWh) — 0 = pas de batterie",
        min_value=0.0, max_value=100.0, value=0.0, step=0.5,
    )
    battery_power = c2.number_input(
        "Puissance max. charge/decharge (kW)",
        min_value=0.5, max_value=30.0, value=3.0, step=0.5,
        help="Batteries residentielles courantes : 3 a 5 kW.",
    )
    battery_efficiency = c3.slider(
        "Rendement aller-retour", 0.70, 1.0, 0.90,
        help="Pertes de charge + decharge cumulees. Typique pour une batterie "
             "lithium domestique : 0.85 a 0.95.",
    )
    battery_price_per_kwh = c4.number_input(
        "Coût indicatif (€/kWh installe)",
        min_value=0, max_value=2000, value=500, step=50,
        help="Valeur indicative a verifier aupres d'un installateur — le prix "
             "au kWh baisse avec la capacite et varie selon la technologie.",
    )
    if battery_capacity > 0:
        st.caption(
            f"Coût batterie estime : {battery_capacity * battery_price_per_kwh:.0f} € "
            "(ajoute automatiquement au coût total de l'installation)."
        )

    st.subheader("\U0001F4B6 Investissement & financement")
    with st.expander("ℹ️ Pourquoi ces informations ?"):
        st.markdown(
            "Le **coût de l'installation** est le prix total avant aides "
            "(matériel + pose). Les **aides/subventions** viennent en "
            "déduction directe. Le reste peut être payé cash (**apport**) ou "
            "financé par un **prêt** (taux + durée) — un prêt étale la "
            "dépense mais ajoute des intérêts, ce qui retarde le moment où "
            "l'installation devient rentable."
        )
    c1, c2 = st.columns(2)
    capex_pv = c1.number_input(
        "Coût de l'installation PV, avant aides (€)",
        min_value=0, max_value=200000, value=15000, step=500,
    )
    subsidies = c2.number_input(
        "Aides / subventions (€)", min_value=0, max_value=50000, value=0, step=100,
    )
    c1, c2, c3 = st.columns(3)
    down_payment = c1.number_input(
        "Apport personnel (€)", min_value=0, max_value=200000, value=15000, step=500,
    )
    loan_rate = c2.number_input(
        "Taux du pret (%/an)", min_value=0.0, max_value=15.0, value=0.0, step=0.1,
    ) / 100
    loan_duration = c3.number_input(
        "Duree du pret (annees)", min_value=0, max_value=25, value=0, step=1,
    )

    st.subheader("\U0001F4A1 Tarifs & hypotheses economiques")
    with st.expander("ℹ️ Pourquoi ces informations ?"):
        st.markdown(
            "Le **prix évité** est ce que coûterait l'électricité autoconsommée "
            "si elle avait été achetée au réseau — c'est la vraie économie "
            "réalisée. Le **tarif de revente** dépend du contrat choisi : "
            "obligation d'achat réglementée (surplus vendu à EDF), "
            "autoconsommation collective (revente négociée dans une "
            "communauté locale), ou vente totale. L'**inflation électrique** "
            "et la **dégradation des panneaux** (environ 0.5%/an) affectent "
            "les économies futures. Le **taux d'actualisation** sert à "
            "calculer la VAN (valeur actuelle nette) : il traduit l'idée "
            "qu'un euro gagné demain vaut un peu moins qu'un euro gagné "
            "aujourd'hui."
        )
    c1, c2 = st.columns(2)
    price_self = c1.number_input(
        "Prix evite de l'electricite achetee (€/kWh)",
        min_value=0.0, max_value=1.0, value=0.2305, step=0.001, format="%.4f",
    )
    export_mode = c2.selectbox(
        "Configuration de revente du surplus",
        list(Investment.EXPORT_PRESETS.keys()),
        index=1,
        help="Le tarif de revente depend fortement de la configuration retenue "
             "(obligation d'achat reglementee, ou tarif negocie en autoconsommation "
             "collective). Valeurs indicatives a verifier selon votre contrat reel.",
    )
    if Investment.EXPORT_PRESETS[export_mode] is None:
        price_export = st.number_input(
            "Tarif de revente personnalise (€/kWh)",
            min_value=0.0, max_value=1.0, value=0.10, step=0.001, format="%.4f",
        )
    else:
        price_export = Investment.EXPORT_PRESETS[export_mode]
        st.caption(f"Tarif retenu : {price_export:.4f} €/kWh (valeur indicative).")

    c1, c2, c3, c4 = st.columns(4)
    price_inflation = c1.number_input(
        "Hausse annuelle du prix de l'elec. (%)", 0.0, 15.0, 2.0, step=0.5,
    ) / 100
    panel_degradation = c2.number_input(
        "Degradation annuelle des panneaux (%)", 0.0, 3.0, 0.5, step=0.1,
    ) / 100
    duration_years = c3.number_input(
        "Duree de projection (annees)", min_value=5, max_value=30, value=25, step=1,
    )
    discount_rate = c4.number_input(
        "Taux d'actualisation, VAN (%)", 0.0, 10.0, 3.0, step=0.5,
    ) / 100

    submitted = st.form_submit_button("Calculer", use_container_width=True)


if submitted:

    if total_panels_selected == 0:
        st.error(
            "Aucun panneau sélectionné sur la toiture — clique sur la grille "
            "ci-dessus (ou sur « Répartir automatiquement ») avant de calculer."
        )
        st.stop()

    with st.spinner("Simulation en cours..."):

        try:
            weather = get_weather(lat, lon)
        except Exception as exc:
            st.error(
                "Impossible de recuperer les donnees meteo aupres de PVGIS "
                f"(verifie la connexion internet et les coordonnees) : {exc}"
            )
            st.stop()

        total_production = None
        installed_kw_total = 0.0

        for section in roof_sections:
            installed_kw = section["n_panels"] * panel_power_kw
            installed_kw_total += installed_kw
            if installed_kw <= 0:
                continue

            roof = Roof(
                weather, lat, lon,
                section["tilt"], section["azimuth"],
                installed_kw, performance_ratio, inverter_efficiency,
                altitude,
            )
            prod = roof.simulate()
            total_production = prod if total_production is None else total_production + prod

        house = House(
            weather,
            base_load_kw=base_load_kw,
            include_water_heater=include_wh,
            include_heat_pump=include_hp,
            include_phev=include_ev,
            annual_target_kwh=annual_target if annual_target > 0 else None,
        )
        loads = house.total()

        battery = None
        if battery_capacity > 0:
            battery = Battery(
                capacity_kwh=battery_capacity,
                max_power_kw=battery_power,
                round_trip_efficiency=battery_efficiency,
            )

        balance = EnergyBalance(total_production, loads["Total"], battery=battery).compute()

        annual_production = total_production.sum()
        annual_consumption = loads["Total"].sum()
        self_consumption = balance["SelfConsumption"].sum()
        export_kwh = balance["CommunityExport"].sum()
        grid_import = balance["GridImport"].sum()
        battery_charge_kwh = balance["BatteryCharge"].sum()
        battery_discharge_kwh = balance["BatteryDischarge"].sum()
        self_consumption_rate = (self_consumption / annual_production) if annual_production else 0

        battery_capex = battery_capacity * battery_price_per_kwh
        total_capex = capex_pv + battery_capex

        investment = Investment(
            capex=total_capex, subsidies=subsidies, down_payment=down_payment,
            loan_rate=loan_rate, loan_duration_years=loan_duration,
            price_self_consumption=price_self, price_export=price_export,
            price_inflation=price_inflation, panel_degradation=panel_degradation,
            duration_years=duration_years, discount_rate=discount_rate,
        )
        cf = investment.cashflow(self_consumption, export_kwh)
        payback = investment.payback_period(cf)
        van = investment.npv(cf)

    st.success("Simulation terminee.")

    st.subheader("Résultats — énergie")
    with st.expander("ℹ️ Comment lire ces résultats ?"):
        st.markdown(
            "Le **taux d'autoconsommation** est la part de la production "
            "solaire réellement utilisée sur place (le reste est exporté/"
            "revendu). Plus il est élevé, plus l'installation « se suffit à "
            "elle-même » ; une batterie ou un décalage des usages vers la "
            "journée l'augmentent généralement."
        )
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Puissance installee", f"{installed_kw_total:.1f} kWc")
    k2.metric("Production annuelle", f"{annual_production:.0f} kWh")
    k3.metric("Consommation annuelle", f"{annual_consumption:.0f} kWh")
    k4.metric("Taux d'autoconsommation", f"{self_consumption_rate * 100:.0f} %")

    k1, k2, k3 = st.columns(3)
    k1.metric("Autoconsomme", f"{self_consumption:.0f} kWh")
    k2.metric("Exporte / revendu", f"{export_kwh:.0f} kWh")
    k3.metric("Achete au reseau", f"{grid_import:.0f} kWh")

    if battery is not None:
        k1, k2, k3 = st.columns(3)
        k1.metric("Énergie stockée / an", f"{battery_charge_kwh:.0f} kWh")
        k2.metric("Énergie restituée / an", f"{battery_discharge_kwh:.0f} kWh")
        cycles = battery_charge_kwh / battery_capacity if battery_capacity else 0
        k3.metric("Cycles équivalents / an", f"{cycles:.0f}")

    st.subheader("Résultats — investissement")
    with st.expander("ℹ️ Comment lire ces résultats ?"):
        st.markdown(
            "Le **temps de retour** est le nombre d'années nécessaires pour "
            "que les économies + revenus cumulés compensent le coût net de "
            "l'installation. La **VAN** (valeur actuelle nette) résume tout "
            "le projet en un seul chiffre en euros d'aujourd'hui : positive, "
            "elle signifie que le projet est rentable sur la durée choisie ; "
            "négative, qu'il ne l'est pas (ou pas encore, sur cette durée)."
        )
    k1, k2, k3 = st.columns(3)
    k1.metric("Coût net apres aides", f"{investment.net_cost:.0f} €")
    k2.metric(
        "Temps de retour",
        f"{payback:.1f} ans" if payback is not None else f"> {duration_years} ans",
    )
    k3.metric("VAN", f"{van:.0f} €")
    if battery is not None:
        st.caption(
            f"Dont coût batterie estimé : {battery_capex:.0f} € "
            f"({battery_capacity:.1f} kWh × {battery_price_per_kwh:.0f} €/kWh)."
        )

    monthly = total_production.resample("ME").sum()
    fig1 = go.Figure(go.Bar(x=monthly.index.strftime("%b %Y"), y=monthly.values))
    fig1.update_layout(title="Production mensuelle (kWh)", yaxis_title="kWh")
    st.plotly_chart(fig1, use_container_width=True)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=cf["Year"], y=cf["CumulativeNet"], mode="lines+markers", name="Cashflow cumule",
    ))
    fig2.add_hline(y=0, line_dash="dash", line_color="gray")
    fig2.update_layout(
        title="Cashflow cumule sur la duree du projet",
        xaxis_title="Année", yaxis_title="€",
    )
    st.plotly_chart(fig2, use_container_width=True)

    with st.expander("Détail du cashflow annuel"):
        st.dataframe(
            cf.style.format({
                "Savings": "{:.0f}", "Sales": "{:.0f}", "GrossBenefit": "{:.0f}",
                "LoanPayment": "{:.0f}", "NetCashflow": "{:.0f}", "CumulativeNet": "{:.0f}",
            }),
            use_container_width=True,
        )

else:
    st.info("Renseigne tes informations ci-dessus puis clique sur *Calculer*.")
