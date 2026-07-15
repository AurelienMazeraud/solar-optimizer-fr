import base64
import datetime as dt
import math
import re

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
from src.contacts import save_contact
from src.community_db import (
    submit_producer, submit_consumer, list_producers, list_consumers,
    set_producer_status, set_consumer_status, get_approved_totals,
    get_targets, set_targets, get_acc_tariff_settings, set_acc_tariff_settings,
    update_producer, delete_producer, update_consumer, delete_consumer,
    compute_billing_period, get_billing_period_detail, list_billing_periods,
    set_consumer_line_paid, set_producer_line_paid,
    STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
)
from src.invoice_extraction import (
    extract_invoice_data, extract_production_data, InvoiceExtractionError,
)
from src.billing_pdf import generate_consumer_invoice_pdf, generate_producer_statement_pdf


st.set_page_config(
    page_title="Calculateur solaire & autoconsommation",
    page_icon="☀️",
    layout="wide",
)

SEGMENT_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bcf60c",
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

COMPASS_LABELS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]

METERS_PER_DEG_LAT = 111320.0

MARKER_RED = "#d62728"

CURSOR_DOT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
    '<circle cx="10" cy="10" r="7" fill="' + MARKER_RED + '" fill-opacity="0.9" '
    'stroke="white" stroke-width="2"/></svg>'
)
CURSOR_DOT_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    CURSOR_DOT_SVG.encode("utf-8")
).decode("ascii")


def compass_direction(azimuth_deg):
    """Convertit un azimut en degres (0=Nord, 90=Est, 180=Sud, 270=Ouest)
    en direction cardinale/inter-cardinale lisible (N, NE, E, SE, S, SO, O, NO)."""
    idx = int(((azimuth_deg % 360) + 22.5) // 45) % 8
    return COMPASS_LABELS[idx]


def offset_point(center, distance_m, bearing_deg):
    """Renvoie le point (lat, lon) situe a distance_m metres de center, dans
    la direction bearing_deg (0=Nord, 90=Est, 180=Sud, 270=Ouest, sens
    horaire comme une boussole). Approximation plane valable sur de petites
    distances (quelques dizaines de metres), largement suffisante pour
    positionner une fleche d'orientation sur un pan de toiture."""
    lat, lon = center
    bearing_rad = math.radians(bearing_deg)
    meters_per_deg_lon = METERS_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01)
    dn = distance_m * math.cos(bearing_rad)
    de = distance_m * math.sin(bearing_rad)
    return (lat + dn / METERS_PER_DEG_LAT, lon + de / meters_per_deg_lon)


def render_pile(label, value_kwh, target_kwh):
    """Affiche une petite jauge en forme de pile/batterie (HTML/CSS), pour
    visualiser un chiffre annuel de la communaute par rapport a un objectif
    configurable par l'administrateur-ice."""
    pct = 0.0 if target_kwh <= 0 else max(0.0, min(value_kwh / target_kwh, 1.0)) * 100
    value_str = f"{value_kwh:,.0f}".replace(",", " ")
    target_str = f"{target_kwh:,.0f}".replace(",", " ")
    html = (
        '<div style="text-align:center;">'
        f'<div style="font-weight:600; margin-bottom:6px;">{label}</div>'
        '<div style="width:26px; height:10px; background:#1b5e20; margin:0 auto; '
        'border-radius:3px 3px 0 0;"></div>'
        '<div style="position:relative; width:80px; height:130px; margin:0 auto; '
        'border:3px solid #1b5e20; border-radius:8px; background:#eef7ee; overflow:hidden;">'
        f'<div style="position:absolute; bottom:0; left:0; right:0; height:{pct:.0f}%; '
        'background:linear-gradient(180deg,#66bb6a,#2e7d32);"></div>'
        '</div>'
        f'<div style="margin-top:8px; font-size:1.05rem; font-weight:600;">{value_str} kWh</div>'
        f'<div style="font-size:0.8rem; color:#888;">objectif {target_str} kWh -- {pct:.0f}%</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


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


def new_pan(tilt=30, azimuth=180, width=4.0, height=4.0, orientation="Portrait"):
    st.session_state["_pan_uid_counter"] = st.session_state.get("_pan_uid_counter", 0) + 1
    return {
        "uid": st.session_state["_pan_uid_counter"],
        "tilt": tilt, "azimuth": azimuth,
        "width": width, "height": height,
        "orientation": orientation,
    }


cfg = load_defaults()

st.markdown(
    """
    <div style="
        background: linear-gradient(135deg, #FFE9B8 0%, #FFB870 20%, #FF8F6B 40%,
                    #F2685F 58%, #C6456A 75%, #7A3568 90%, #4E2A54 100%);
        border-radius: 20px;
        padding: 28px 32px;
        margin-bottom: 4px;
        box-shadow: 0 10px 28px rgba(120, 40, 70, 0.28);
    ">
        <div style="font-size:2.5rem; font-weight:800; color:#fff; line-height:1.1;
                    text-shadow: 0 2px 10px rgba(0,0,0,0.18);">
            ☀️ Ivry Soleil Partage
        </div>
        <div style="font-size:1.05rem; color:#FFF3E6; margin-top:6px; font-weight:500;">
            Autoconsommation collective &amp; calculateur solaire
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()
st.subheader("\U0001F50B Ivry Soleil Partage -- la communaute en un coup d'oeil")
st.caption(
    "Chiffres annuels agreges a partir des membres dont les donnees ont ete "
    "validees par l'association (onglet Administration). Une vue plus "
    "detaillee (mensuelle, par membre...) viendra dans une prochaine version."
)
approved_production_kwh, approved_acc_kwh = get_approved_totals()
production_target_kwh, consumption_target_kwh = get_targets()
pile_col1, pile_col2, _pile_spacer = st.columns([1, 1, 3])
with pile_col1:
    render_pile("Production annuelle", approved_production_kwh, production_target_kwh)
with pile_col2:
    render_pile("Consommation echangee via l'ACC", approved_acc_kwh, consumption_target_kwh)
st.divider()

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #FFF8EC 0%, #FCEBDD 25%, #F8DCD3 50%,
                    #F2CDD3 75%, #E9C4D6 100%);
        background-attachment: fixed;
    }

    /* Cartes de section (relief autour des grands blocs de contenu) */
    .section-card {
        border-radius: 22px;
        padding: 22px 26px 6px 26px;
        margin: 6px 0 24px 0;
        box-shadow: 0 8px 24px rgba(122, 53, 104, 0.12);
        border: 1px solid rgba(198, 69, 106, 0.16);
    }
    .section-card--location {
        background: linear-gradient(160deg, #FFF6E9 0%, #FDEBDD 100%);
    }
    .section-card--energy {
        background: linear-gradient(160deg, #FFF3EA 0%, #FBE3DD 100%);
    }
    .section-card--finance {
        background: linear-gradient(160deg, #FCEAE6 0%, #F6DCE1 100%);
    }
    .section-card--join {
        background: linear-gradient(160deg, #F8E3E7 0%, #F0D3DE 100%);
    }

    /* Onglets */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        width: 100%;
    }
    .stTabs [data-baseweb="tab-list"] button {
        flex: 1 1 0;
        padding: 22px 24px !important;
        border-radius: 14px 14px 0 0 !important;
        background: linear-gradient(135deg, #FBE4CE 0%, #F6D2C4 100%) !important;
        transition: all 0.2s ease;
    }
    .stTabs [data-baseweb="tab-list"] button:hover {
        background: linear-gradient(135deg, #F7D2AE 0%, #F0B8A8 100%) !important;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #FF8F6B 0%, #C6456A 100%) !important;
    }
    .stTabs [aria-selected="true"] [data-testid="stMarkdownContainer"] p {
        color: white !important;
    }
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.7rem !important;
        font-weight: 700 !important;
        text-align: center;
        width: 100%;
    }

    /* Metriques (cartes) */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #ffffff 0%, #FFF5EC 100%);
        border-radius: 16px;
        padding: 16px 18px;
        box-shadow: 0 4px 14px rgba(198, 69, 106, 0.14);
        border: 1px solid #F6D9CB;
    }
    div[data-testid="stMetricValue"] {
        color: #C6456A;
    }

    /* Boutons (normaux, formulaires, telechargement) */
    div[data-testid="stButton"] button,
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stDownloadButton"] button {
        background: linear-gradient(135deg, #FF8F56 0%, #EF5F6B 40%, #B23E6E 72%, #632A56 100%);
        color: white;
        border: none;
        border-radius: 999px;
        padding: 0.55rem 1.4rem;
        font-weight: 600;
        box-shadow: 0 4px 14px rgba(99, 42, 86, 0.35);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    div[data-testid="stButton"] button:hover,
    div[data-testid="stFormSubmitButton"] button:hover,
    div[data-testid="stDownloadButton"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(99, 42, 86, 0.46);
        color: white;
    }

    /* Expanders */
    div[data-testid="stExpander"] {
        border-radius: 14px;
        border: 1px solid #F6D2C4;
        overflow: hidden;
    }

    /* Conteneurs avec bordure (cartes de pans, lignes admin...) */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

tab_producteur, tab_consommateur, tab_admin = st.tabs([
    "\U0001F506 Producteur", "\U0001F50C Consommateur", "\U0001F510 Administration",
])

# Rempli par les onglets Producteur/Consommateur quand une simulation ou une
# facture verifiee est disponible, et conserve en session_state (pas une
# simple variable locale) car le formulaire de contact plus bas est soumis
# via un rerun distinct, ou "submitted" (bouton de simulation) redevient
# False -- sans session_state la contribution disparaitrait avant meme
# d'atteindre le formulaire "Rejoindre Ivry Soleil Partage".
producer_contribution = st.session_state.get("_producer_contribution")
consumer_contribution = st.session_state.get("_consumer_contribution")

with tab_producteur:

    st.markdown('<div class="section-card section-card--location">', unsafe_allow_html=True)

    st.subheader("Quel est ton profil ?")
    mode = st.radio(
        "Choisis la situation qui te correspond",
        [
            "Je simule un nouveau projet (pas encore equipe)",
            "J'ai deja une installation -- j'entre mes donnees reelles",
        ],
        index=0,
        key="user_mode",
        help="Le premier mode simule la production a partir de la geometrie du "
             "toit. Le second mode saute la simulation physique et calcule "
             "directement tes economies a partir de tes vrais chiffres "
             "(facture EDF, appli de monitoring de l'onduleur, releve Linky...).",
    )
    is_existing_mode = mode.startswith("J'ai deja")

    # ------------------------------------------------------------------
    # Localisation : recherche d'adresse (avec suggestions a choisir) +
    # carte interactive. Simplifie au maximum : plus de champs
    # latitude/longitude/altitude visibles, la position se choisit
    # uniquement via l'adresse ou un clic sur la carte.
    # ------------------------------------------------------------------
    st.subheader("\U0001F4CD Localisation")

    with st.expander("Pourquoi ces informations ?"):
        st.markdown(
            "La position (latitude/longitude) determine l'ensoleillement annuel "
            "recu (plus on est au sud en France, plus il est important) : elle "
            "sert a interroger la base meteo europeenne PVGIS pour reconstituer "
            "une annee type heure par heure -- utile surtout si tu simules un "
            "nouveau projet."
        )

    # Position par defaut avant tout choix explicite de l'utilisateur-ice :
    # metro Mairie d'Ivry (Ivry-sur-Seine), plutot qu'une adresse personnelle
    # pre-configuree -- aucune detection de toit ne doit se lancer tant que
    # l'utilisateur-ice n'a pas lui-meme choisi une adresse ou clique sur la carte.
    default_lat = 48.8111
    default_lon = 2.3834
    default_altitude = float(cfg["site"]["altitude"]) if cfg else 45.0
    position_chosen = "lat" in st.session_state and "lon" in st.session_state

    current_lat = st.session_state.get("lat", default_lat)
    current_lon = st.session_state.get("lon", default_lon)

    st.caption(
        "Tape une adresse puis choisis-la dans la liste, ou clique directement "
        "sur la carte pour placer le point sur ta maison (le curseur devient un "
        "point rouge au survol de la carte). Des qu'une position est choisie, "
        "**la detection du toit se lance toute seule** (section ci-dessous) si "
        "une cle API est configuree. Bascule sur la vue satellite (icone en "
        "haut a droite de la carte) pour verifier que le toit detecte "
        "correspond bien a ta maison. Si l'adresse tapee ne remonte rien ou le "
        "mauvais endroit, essaie avec juste \"numero + rue + ville\" (sans code "
        "postal), ou clique directement sur la carte."
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
            "Resultats trouves -- selectionne la bonne adresse",
            labels, index=None, placeholder="Choisis une adresse...",
            key="_address_choice",
        )
        if choice:
            selected = candidates[labels.index(choice)]
            selected_point = (selected["lat"], selected["lon"])
            st.session_state["_selected_address_label"] = selected["label"]
            if st.session_state.get("_last_address_applied") != selected_point:
                st.session_state["_last_address_applied"] = selected_point
                st.session_state["lat"], st.session_state["lon"] = selected_point
                current_lat, current_lon = selected_point

    location_map = folium.Map(
        location=[current_lat, current_lon], zoom_start=17, max_zoom=22, tiles=None,
        control_scale=True,
    )

    # Curseur personnalise : un point rouge (meme couleur que le marqueur de
    # position choisie) suit la souris au survol de la carte.
    location_map.get_root().html.add_child(folium.Element(
        "<style>.leaflet-container { cursor: url('" + CURSOR_DOT_DATA_URI +
        "') 10 10, crosshair !important; }</style>"
    ))

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, Maxar, Earthstar Geographics",
        name="Vue satellite",
        overlay=False, control=True, show=True, max_zoom=22, max_native_zoom=19,
    ).add_to(location_map)
    folium.TileLayer(
        tiles="OpenStreetMap", name="Plan", overlay=False, control=True, show=False,
        max_zoom=22, max_native_zoom=19,
    ).add_to(location_map)

    folium.CircleMarker(
        location=[current_lat, current_lon],
        radius=9, color=MARKER_RED, weight=2,
        fill=True, fill_color=MARKER_RED, fill_opacity=0.85,
        tooltip="Position actuelle -- clique ailleurs pour la deplacer",
    ).add_to(location_map)

    folium.Circle(
        location=[current_lat, current_lon],
        radius=750, color="#2e7d32", weight=2, dash_array="6",
        fill=False, opacity=0.7,
        tooltip="Rayon de 750 m autour de la position actuelle",
    ).add_to(location_map)

    roof_overlay = st.session_state.get("_roof_overlay")
    if roof_overlay:
        building_bbox = roof_overlay.get("building_bbox")
        if building_bbox:
            folium.Rectangle(
                bounds=[building_bbox["sw"], building_bbox["ne"]],
                color="#888888", weight=1, fill=False, dash_array="4",
                tooltip="Emprise du batiment detecte par Google Solar API "
                         "(a comparer a la vue satellite pour verifier le bon batiment)",
            ).add_to(location_map)
        for i, seg in enumerate(roof_overlay.get("segments", [])):
            seg_center = seg.get("center")
            if not seg_center:
                continue
            color = SEGMENT_COLORS[i % len(SEGMENT_COLORS)]
            tooltip_text = (
                f"Pan {i + 1} -- inclinaison {seg['tilt']:.0f} deg, "
                f"azimut {seg['azimuth']:.0f} deg ({compass_direction(seg['azimuth'])}), "
                f"surface {seg['area']:.0f} m2"
            )
            side = math.sqrt(max(seg["area"], 1.0))
            arrow_len = max(4.0, side * 0.6)
            tip = offset_point(seg_center, arrow_len, seg["azimuth"])
            folium.PolyLine(
                locations=[seg_center, tip],
                color=color, weight=4, opacity=0.9,
                tooltip=tooltip_text,
            ).add_to(location_map)
            folium.CircleMarker(
                location=seg_center,
                radius=7, color=color, weight=2,
                fill=True, fill_color=color, fill_opacity=0.9,
                tooltip=tooltip_text,
            ).add_to(location_map)

    folium.LayerControl(collapsed=True).add_to(location_map)
    map_state = st_folium(
        location_map, height=400, width=None, key="location_map",
        returned_objects=["last_clicked"],
    )

    clicked = map_state.get("last_clicked") if map_state else None
    if clicked:
        click_point = (round(clicked["lat"], 6), round(clicked["lng"], 6))
        if st.session_state.get("_last_map_click") != click_point:
            st.session_state["_last_map_click"] = click_point
            st.session_state["lat"], st.session_state["lon"] = click_point
            st.rerun()

    lat = st.session_state.get("lat", current_lat)
    lon = st.session_state.get("lon", current_lon)
    altitude = default_altitude

    # ------------------------------------------------------------------
    # Les sections suivantes (detection du toit, modules PV, pans de
    # toiture) ne concernent que la simulation d'un nouveau projet : si
    # l'utilisateur a deja une installation, il entrera directement ses
    # chiffres reels plus bas, dans le formulaire.
    # ------------------------------------------------------------------
    panel_power_kw = 0.0
    roof_sections = []
    total_panels_selected = 0
    total_installed_kw = 0.0

    if not is_existing_mode:

        server_key = ""
        try:
            server_key = st.secrets.get("GOOGLE_SOLAR_API_KEY", "")
        except Exception:
            server_key = ""

        if server_key:
            api_key = server_key
        else:
            api_key = st.text_input(
                "Cle API Google Solar (test local uniquement)",
                value="",
                type="password",
                help="Pour un usage durable/deploye, stocke plutot la cle dans "
                     "`.streamlit/secrets.toml` (GOOGLE_SOLAR_API_KEY = \"...\") -- "
                     "ce fichier est deja exclu du depot Git.",
            )

        lookup_signature = (round(lat, 5), round(lon, 5), api_key)
        should_lookup = (
            bool(api_key) and position_chosen
            and st.session_state.get("_last_solar_lookup") != lookup_signature
        )

        if should_lookup:
            st.session_state["_last_solar_lookup"] = lookup_signature
            try:
                result = get_roof_segments(lat, lon, api_key)
            except SolarApiError as exc:
                st.session_state["_roof_overlay"] = None
                st.session_state["_roof_fetch_error"] = str(exc)
                st.session_state["_roof_fetch_summary"] = None
            else:
                segments = result["segments"]
                n_found = len(segments)

                new_pans = []
                for seg in segments:
                    side = math.sqrt(max(seg["area"], 1.0))
                    new_pans.append(new_pan(
                        tilt=int(round(seg["tilt"])),
                        azimuth=int(round(seg["azimuth"])),
                        width=round(side, 1), height=round(side, 1),
                    ))
                st.session_state["_pans"] = new_pans

                max_panels = result.get("max_panels_count")
                panel_w = result.get("panel_capacity_watts")
                panel_h_m = result.get("panel_height_m")
                panel_w_m = result.get("panel_width_m")
                ref_bits = []
                if panel_w:
                    ref_bits.append(f"{panel_w:.0f} Wc")
                if panel_h_m and panel_w_m:
                    ref_bits.append(f"{panel_h_m:.2f} x {panel_w_m:.2f} m")

                st.session_state["_roof_overlay"] = {
                    "segments": segments,
                    "building_bbox": result.get("building_bbox"),
                }
                st.session_state["_roof_fetch_error"] = None
                st.session_state["_roof_fetch_summary"] = {
                    "n_found": n_found, "max_panels": max_panels, "ref_bits": ref_bits,
                }
            st.rerun()

        if st.session_state.get("_roof_fetch_error"):
            st.error(st.session_state["_roof_fetch_error"])
        elif st.session_state.get("_roof_fetch_summary"):
            st.info(
                "Merci de bien verifier ces informations avant de valider la "
                "simulation de pose de panneaux solaire. A noter que la totalite "
                "du toit n'est pas toujours equipable, une visite technique par "
                "un professionnel agree permettra de valider ces informations."
            )

        st.subheader("\U0001F3E0 Pans de toiture")

        with st.expander("Pourquoi ces informations ?"):
            st.markdown(
                "Chaque carte ci-dessous represente un pan de toiture : "
                "**inclinaison** (0 deg = toit plat, 90 deg = mur vertical), "
                "**azimut** (0=Nord, 90=Est, 180=Sud, 270=Ouest -- un pan plein "
                "Sud recoit generalement le plus de soleil sur l'annee), et "
                "**largeur/hauteur** qui determinent combien de panneaux "
                "tiennent physiquement dessus. Modifie librement ces valeurs, "
                "supprime les pans qui ne conviennent pas avec la croix, ou "
                "ajoute-en manuellement. Une fois tes pans valides, choisis ton "
                "modele de panneau juste apres : le nombre de panneaux "
                "installables sur chaque pan s'affichera alors."
            )

        if "_pans" not in st.session_state:
            default_pans = []
            if cfg:
                for key_name in ("southwest", "northeast"):
                    r = cfg.get("roof", {}).get(key_name, {})
                    area = r.get("area", 20)
                    side = round(math.sqrt(max(area, 1.0)), 1)
                    default_pans.append(new_pan(
                        tilt=r.get("tilt", 15), azimuth=r.get("azimuth", 180),
                        width=side, height=side,
                    ))
            if not default_pans:
                default_pans = [new_pan()]
            st.session_state["_pans"] = default_pans

        pan_to_delete = None
        pans = st.session_state["_pans"]
        cols_per_row = 3
        for row_start in range(0, len(pans), cols_per_row):
            row_pans = pans[row_start: row_start + cols_per_row]
            row_cols = st.columns(cols_per_row)
            for col, pan in zip(row_cols, row_pans):
                uid = pan["uid"]
                idx = pans.index(pan)
                with col:
                    with st.container(border=True):
                        head_l, head_r = st.columns([5, 1])
                        head_l.markdown(f"**Pan {idx + 1}**")
                        if head_r.button("✕", key=f"del_pan_{uid}", help="Supprimer ce pan"):
                            pan_to_delete = uid
                        pan["tilt"] = st.number_input(
                            "Inclinaison (deg)", min_value=0, max_value=90,
                            value=int(pan["tilt"]), key=f"pan_tilt_{uid}",
                        )
                        pan["azimuth"] = st.number_input(
                            "Azimut (deg)", min_value=0, max_value=360,
                            value=int(pan["azimuth"]), key=f"pan_az_{uid}",
                            help="0=Nord, 90=Est, 180=Sud, 270=Ouest",
                        )
                        st.caption(f"-> oriente **{compass_direction(pan['azimuth'])}**")
                        wc1, wc2 = st.columns(2)
                        pan["width"] = wc1.number_input(
                            "Largeur (m)", min_value=0.5, max_value=30.0,
                            value=float(pan["width"]), step=0.1, key=f"pan_w_{uid}",
                        )
                        pan["height"] = wc2.number_input(
                            "Hauteur (m)", min_value=0.5, max_value=30.0,
                            value=float(pan["height"]), step=0.1, key=f"pan_h_{uid}",
                        )
                        pan["orientation"] = st.radio(
                            "Panneaux", ["Portrait", "Paysage"],
                            index=0 if pan["orientation"] == "Portrait" else 1,
                            horizontal=True, key=f"pan_orient_{uid}",
                        )

        if pan_to_delete is not None:
            st.session_state["_pans"] = [p for p in pans if p["uid"] != pan_to_delete]
            st.rerun()

        if st.button("+ Ajouter un pan"):
            st.session_state["_pans"].append(new_pan())
            st.rerun()

        st.subheader("\U0001F527 Modules photovoltaiques")

        with st.expander("Pourquoi ces informations ?"):
            st.markdown(
                "La **puissance crete (Wc)** est la puissance maximale du panneau "
                "dans des conditions de test standard (plein soleil, 25 degres) -- en "
                "usage reel, la production est toujours un peu inferieure. Les "
                "**dimensions** (largeur/hauteur) determinent combien de panneaux "
                "tiennent physiquement sur chaque pan de toit. Le **performance "
                "ratio** regroupe les pertes reelles (cablage, echauffement, "
                "salissures, ombrage partiel...) -- 0.85 est une valeur courante en "
                "France. Le **rendement onduleur** est la perte de conversion du "
                "courant continu (panneaux) vers le courant alternatif (maison) : "
                "environ 0.97 pour un onduleur recent."
            )

        c1, c2, c3 = st.columns(3)
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

        with st.expander("⚙️ Parametres avances"):
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

        for pan in st.session_state["_pans"]:
            cols_count, rows_count = panel_grid_dims(
                pan["width"], pan["height"], panel_width, panel_height, pan["orientation"]
            )
            pan["max_slots"] = cols_count * rows_count

        total_slots = [p.get("max_slots", 0) for p in st.session_state["_pans"]]

        st.markdown("**Combien de panneaux veux-tu installer au total ?**")
        dc1, dc2 = st.columns([2, 1])
        desired_total_panels = dc1.number_input(
            "Nombre de panneaux souhaite (total)",
            min_value=0, max_value=max(sum(total_slots), 1),
            value=min(20, sum(total_slots)) if sum(total_slots) else 0,
            step=1,
        )
        if dc2.button("Repartir automatiquement sur les pans", width="stretch"):
            alloc = auto_distribute(desired_total_panels, total_slots)
            for pan, n in zip(st.session_state["_pans"], alloc):
                st.session_state[f"panels_{pan['uid']}"] = n

        st.markdown("**Ajuste le nombre de panneaux pan par pan :**")

        roof_sections = []
        for i, pan in enumerate(st.session_state["_pans"]):
            uid = pan["uid"]
            slots = pan.get("max_slots", 0)
            if slots == 0:
                n_panels = 0
                st.caption(f"Pan {i + 1} : 0 panneau (aucune place disponible).")
            else:
                default_n = st.session_state.get(f"panels_{uid}", slots)
                n_panels = st.slider(
                    f"Pan {i + 1} -- nombre de panneaux (jusqu'a {slots} possibles)",
                    min_value=0, max_value=slots,
                    value=min(default_n, slots),
                    key=f"panels_{uid}",
                )
            roof_sections.append({
                "tilt": pan["tilt"], "azimuth": pan["azimuth"], "n_panels": n_panels,
            })

        total_panels_selected = sum(s["n_panels"] for s in roof_sections)
        total_installed_kw = total_panels_selected * panel_power_kw
        st.metric(
            "Total selectionne",
            f"{total_panels_selected} panneaux -- {total_installed_kw:.1f} kWc",
        )

    else:
        st.info(
            "Mode \"installation existante\" : les sections detection du toit / "
            "modules PV / pans de toiture sont masquees -- tu entreras "
            "directement tes chiffres reels de production/consommation plus bas."
        )

        with st.expander(
            "\U0001F4E4 Remplir automatiquement via une facture EDF et/ou un "
            "releve de production (optionnel)"
        ):
            st.caption(
                "Envoie ta facture EDF (consommation) et/ou un releve de "
                "production annuelle (export de ton app de suivi d'onduleur, "
                "certificat...) : une IA (Claude, Anthropic) en extrait les "
                "chiffres pour pre-remplir les champs ci-dessous, et calculer "
                "a la fois le gain lie a l'autoconsommation de l'electricite "
                "d'Ivry Soleil Partage et le gain lie a la revente du surplus. "
                "Rien n'est conserve par Ivry Soleil Partage au-dela de cette "
                "analyse ponctuelle."
            )

            server_anthropic_key_e = ""
            try:
                server_anthropic_key_e = st.secrets.get("ANTHROPIC_API_KEY", "")
            except Exception:
                server_anthropic_key_e = ""

            if server_anthropic_key_e:
                anthropic_api_key_e = server_anthropic_key_e
            else:
                st.warning(
                    "Aucune cle configuree cote serveur. Le champ ci-dessous est "
                    "uniquement pour un test local : ne l'utilise jamais sur une "
                    "app publique.",
                    icon="⚠️",
                )
                anthropic_api_key_e = st.text_input(
                    "Cle API Anthropic (test local uniquement)", value="",
                    type="password", key="_anthropic_key_existing",
                    help="Stocke plutot la cle dans `.streamlit/secrets.toml` "
                         "(ANTHROPIC_API_KEY = \"...\") pour un usage durable/deploye.",
                )

            ec1, ec2 = st.columns(2)
            invoice_file_e = ec1.file_uploader(
                "Facture EDF -- consommation (PDF, JPG ou PNG)",
                type=["pdf", "png", "jpg", "jpeg"], key="_invoice_file_existing",
            )
            production_file_e = ec2.file_uploader(
                "Releve de production annuelle (PDF, JPG ou PNG)",
                type=["pdf", "png", "jpg", "jpeg"], key="_production_file_existing",
            )

            if st.button(
                "Analyser les documents",
                disabled=not (anthropic_api_key_e and (invoice_file_e or production_file_e)),
                key="_analyze_existing",
            ):
                if invoice_file_e:
                    with st.spinner("Analyse de la facture en cours..."):
                        try:
                            extracted_inv_e = extract_invoice_data(
                                invoice_file_e.getvalue(), invoice_file_e.name,
                                anthropic_api_key_e,
                            )
                        except InvoiceExtractionError as exc:
                            st.session_state["_existing_invoice_error"] = str(exc)
                        else:
                            st.session_state["_existing_invoice_error"] = None
                            conso_e = extracted_inv_e.get("consommation_annuelle_kwh")
                            if conso_e:
                                st.session_state["annual_consumption_existing"] = int(conso_e)
                            full_name_e = (extracted_inv_e.get("titulaire_nom") or "").strip()
                            if full_name_e:
                                parts_e = full_name_e.split(None, 1)
                                st.session_state["contact_first_name"] = parts_e[0]
                                st.session_state["contact_last_name"] = (
                                    parts_e[1] if len(parts_e) > 1 else ""
                                )
                            adresse_e = extracted_inv_e.get("adresse")
                            if adresse_e:
                                st.session_state["contact_address"] = adresse_e

                if production_file_e:
                    with st.spinner("Analyse du releve de production en cours..."):
                        try:
                            extracted_prod_e = extract_production_data(
                                production_file_e.getvalue(), production_file_e.name,
                                anthropic_api_key_e,
                            )
                        except InvoiceExtractionError as exc:
                            st.session_state["_existing_production_error"] = str(exc)
                        else:
                            st.session_state["_existing_production_error"] = None
                            prod_e = extracted_prod_e.get("production_annuelle_kwh")
                            if prod_e:
                                st.session_state["annual_production_existing"] = int(prod_e)
                            export_e = extracted_prod_e.get("energie_exportee_kwh")
                            if export_e:
                                st.session_state["annual_export_existing"] = int(export_e)
                            periode_ref = (
                                extracted_prod_e.get("periode_fin")
                                or extracted_prod_e.get("periode_debut")
                            )
                            if periode_ref:
                                match_year = re.match(r"^(\d{4})", str(periode_ref))
                                if match_year:
                                    st.session_state["_production_reference_year"] = int(
                                        match_year.group(1)
                                    )

                st.success(
                    "Documents analyses -- verifie les valeurs pre-remplies "
                    "ci-dessous avant de calculer."
                )

            if st.session_state.get("_existing_invoice_error"):
                st.error(st.session_state["_existing_invoice_error"])
            if st.session_state.get("_existing_production_error"):
                st.error(st.session_state["_existing_production_error"])

    if not is_existing_mode:
        with st.expander("\U0001F4E4 Remplir automatiquement via une facture EDF (optionnel)"):
            st.caption(
                "Envoie ta facture EDF (PDF ou photo) : une IA (Claude, "
                "Anthropic) en extrait la consommation annuelle et tes "
                "coordonnees (nom, adresse), pour pre-remplir la consommation "
                "du foyer ci-dessous ainsi que le formulaire de contact tout "
                "en bas de la page. Rien n'est conserve par Ivry Soleil "
                "Partage au-dela de cette analyse ponctuelle."
            )

            server_anthropic_key_p = ""
            try:
                server_anthropic_key_p = st.secrets.get("ANTHROPIC_API_KEY", "")
            except Exception:
                server_anthropic_key_p = ""

            if server_anthropic_key_p:
                anthropic_api_key_p = server_anthropic_key_p
            else:
                st.warning(
                    "Aucune cle configuree cote serveur. Le champ ci-dessous est "
                    "uniquement pour un test local : ne l'utilise jamais sur une "
                    "app publique.",
                    icon="⚠️",
                )
                anthropic_api_key_p = st.text_input(
                    "Cle API Anthropic (test local uniquement)", value="",
                    type="password", key="_anthropic_key_producteur",
                    help="Stocke plutot la cle dans `.streamlit/secrets.toml` "
                         "(ANTHROPIC_API_KEY = \"...\") pour un usage durable/deploye.",
                )

            invoice_file_p = st.file_uploader(
                "Facture EDF (PDF, JPG ou PNG)", type=["pdf", "png", "jpg", "jpeg"],
                key="_invoice_file_producteur",
            )

            if st.button(
                "Analyser la facture",
                disabled=not (invoice_file_p and anthropic_api_key_p),
                key="_analyze_invoice_producteur",
            ):
                with st.spinner("Analyse de la facture en cours..."):
                    try:
                        extracted_p = extract_invoice_data(
                            invoice_file_p.getvalue(), invoice_file_p.name,
                            anthropic_api_key_p,
                        )
                    except InvoiceExtractionError as exc:
                        st.session_state["_invoice_error_producteur"] = str(exc)
                    else:
                        st.session_state["_invoice_error_producteur"] = None

                        conso = extracted_p.get("consommation_annuelle_kwh")
                        if conso:
                            st.session_state["annual_target_foyer"] = int(conso)

                        full_name = (extracted_p.get("titulaire_nom") or "").strip()
                        if full_name:
                            parts = full_name.split(None, 1)
                            st.session_state["contact_first_name"] = parts[0]
                            st.session_state["contact_last_name"] = parts[1] if len(parts) > 1 else ""

                        adresse_facture = extracted_p.get("adresse")
                        if adresse_facture:
                            st.session_state["contact_address"] = adresse_facture

                        st.success(
                            "Facture analysee -- la consommation annuelle "
                            "ci-dessous et tes coordonnees (formulaire de "
                            "contact tout en bas) ont ete pre-remplies : "
                            "verifie-les avant de calculer/envoyer."
                        )

            if st.session_state.get("_invoice_error_producteur"):
                st.error(st.session_state["_invoice_error_producteur"])

    st.markdown('</div>', unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Le reste (consommation ou donnees reelles, batterie, financement,
    # tarifs) n'a pas besoin de reactivite immediate : ca reste dans un
    # st.form valide par un bouton "Calculer".
    # ------------------------------------------------------------------
    with st.form("simulation"):

        base_load_kw = 0.35
        include_wh = include_hp = include_ev = False
        annual_target = 0
        annual_consumption_real = 0
        annual_production_real = 0
        annual_export_real_input = 0

        if not is_existing_mode:
            st.subheader("\U0001F50C Consommation du foyer")
            with st.expander("Pourquoi ces informations ?"):
                st.markdown(
                    "Le profil de consommation est reconstitue heure par heure a "
                    "partir de quelques briques simples : une **charge de base** "
                    "(eclairage, electromenager, veille), un **chauffe-eau** (souvent "
                    "programme la nuit ou en heures creuses), une **pompe a chaleur** "
                    "(chauffage, avec un COP qui multiplie l'electricite consommee en "
                    "chaleur produite), et un **vehicule electrique**. Plus la "
                    "consommation coincide avec les heures de production solaire "
                    "(milieu de journee), plus le taux d'autoconsommation est eleve -- "
                    "c'est tout l'interet de decaler certains usages (lave-linge, "
                    "recharge du vehicule...) vers la journee."
                )
            c1, c2, c3, c4 = st.columns(4)
            base_load_kw = c1.number_input("Charge de base (kW)", 0.0, 5.0, 0.35, step=0.05)
            include_wh = c2.checkbox("Chauffe-eau electrique", value=True)
            include_hp = c3.checkbox("Pompe a chaleur", value=True)
            include_ev = c4.checkbox("Vehicule electrique", value=True)
            annual_target = st.number_input(
                "Consommation annuelle connue (kWh) -- laisser a 0 pour garder le profil "
                "modelise tel quel, sinon le profil est recale sur cette valeur "
                "(ex: releve de compteur Linky, ou pre-rempli depuis une facture "
                "ci-dessus)",
                min_value=0, max_value=50000,
                value=st.session_state.get("annual_target_foyer", 0), step=100,
                key="annual_target_foyer",
            )
        else:
            st.subheader("\U0001F4CA Vos donnees reelles (installation existante)")
            with st.expander("Pourquoi ces informations ?"):
                st.markdown(
                    "Puisque l'installation existe deja, inutile de la simuler : "
                    "ces chiffres se trouvent sur ta **facture annuelle** (EDF ou "
                    "autre fournisseur), sur l'**appli de monitoring** de ton "
                    "onduleur (Enphase, SolarEdge, Huawei...), ou sur ton "
                    "**releve Linky**. Si tu ne connais pas precisement l'energie "
                    "injectee/revendue, laisse ce champ a 0 : une estimation "
                    "raisonnable sera calculee (production moins consommation, "
                    "bornee a 0)."
                )
            c1, c2 = st.columns(2)
            annual_consumption_real = c1.number_input(
                "Consommation annuelle du foyer (kWh)",
                min_value=0, max_value=100000,
                value=st.session_state.get("annual_consumption_existing", 6000), step=100,
                key="annual_consumption_existing",
            )
            annual_production_real = c2.number_input(
                "Production annuelle de l'installation (kWh)",
                min_value=0, max_value=100000,
                value=st.session_state.get("annual_production_existing", 6000), step=100,
                key="annual_production_existing",
            )
            annual_export_real_input = st.number_input(
                "Energie injectee/revendue sur le reseau (kWh/an) -- laisser a 0 si "
                "inconnue",
                min_value=0, max_value=100000,
                value=st.session_state.get("annual_export_existing", 0), step=100,
                key="annual_export_existing",
            )

        st.subheader("\U0001F50B Batterie (optionnel)")
        battery_capacity = 0.0
        battery_power = 3.0
        battery_efficiency = 0.90
        battery_price_per_kwh = 500
        if not is_existing_mode:
            with st.expander("Pourquoi ces informations ?"):
                st.markdown(
                    "Une batterie stocke le surplus produit en journee pour le "
                    "restituer le soir : elle augmente mecaniquement le taux "
                    "d'autoconsommation, mais a un cout d'achat et un **rendement "
                    "aller-retour** imparfait (une partie de l'energie stockee est "
                    "perdue en chaleur). Laisser la capacite a 0 revient a simuler "
                    "une installation sans batterie."
                )
            c1, c2, c3, c4 = st.columns(4)
            battery_capacity = c1.number_input(
                "Capacite utile (kWh) -- 0 = pas de batterie",
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
                "Cout indicatif (euros/kWh installe)",
                min_value=0, max_value=2000, value=500, step=50,
                help="Valeur indicative a verifier aupres d'un installateur -- le prix "
                     "au kWh baisse avec la capacite et varie selon la technologie.",
            )
            if battery_capacity > 0:
                st.caption(
                    f"Cout batterie estime : {battery_capacity * battery_price_per_kwh:.0f} euros "
                    "(ajoute automatiquement au cout total de l'installation)."
                )
        else:
            st.caption(
                "Non applicable en mode \"installation existante\" -- si tu as deja "
                "une batterie, son effet est deja inclus dans tes chiffres reels "
                "de consommation/production/injection ci-dessus."
            )

        capex_pv = 0
        subsidies = 0
        down_payment = 0
        loan_rate = 0.0
        loan_duration = 0
        if not is_existing_mode:
            st.markdown('<div class="section-card section-card--finance">', unsafe_allow_html=True)
            st.subheader("\U0001F4B6 Investissement & financement")
            with st.expander("Pourquoi ces informations ?"):
                st.markdown(
                    "Le **cout de l'installation** est le prix total avant aides "
                    "(materiel + pose). Les **aides/subventions** viennent en "
                    "deduction directe. Le reste peut etre paye cash (**apport**) ou "
                    "finance par un **pret** (taux + duree) -- un pret etale la "
                    "depense mais ajoute des interets, ce qui retarde le moment ou "
                    "l'installation devient rentable."
                )
            c1, c2 = st.columns(2)
            capex_pv = c1.number_input(
                "Cout de l'installation PV, avant aides (euros)",
                min_value=0, max_value=200000, value=15000, step=500,
            )
            subsidies = c2.number_input(
                "Aides / subventions (euros)", min_value=0, max_value=50000, value=0, step=100,
            )
            c1, c2, c3 = st.columns(3)
            down_payment = c1.number_input(
                "Apport personnel (euros)", min_value=0, max_value=200000, value=15000, step=500,
            )
            loan_rate = c2.number_input(
                "Taux du pret (%/an)", min_value=0.0, max_value=15.0, value=0.0, step=0.1,
            ) / 100
            loan_duration = c3.number_input(
                "Duree du pret (annees)", min_value=0, max_value=25, value=0, step=1,
            )
            st.markdown('</div>', unsafe_allow_html=True)

        st.subheader("\U0001F4A1 Tarifs & hypotheses economiques")
        with st.expander("Pourquoi ces informations ?"):
            st.markdown(
                "Le **prix evite** est ce que couterait l'electricite autoconsommee "
                "si elle avait ete achetee au reseau -- c'est la vraie economie "
                "realisee. Le **tarif de revente** depend du contrat choisi : "
                "obligation d'achat reglementee (surplus vendu a EDF), "
                "autoconsommation collective (revente negociee dans une "
                "communaute locale), ou vente totale. L'**inflation electrique** "
                "et la **degradation des panneaux** (environ 0.5%/an) affectent "
                "les economies futures. Le **taux d'actualisation** sert a "
                "calculer la VAN (valeur actuelle nette) : il traduit l'idee "
                "qu'un euro gagne demain vaut un peu moins qu'un euro gagne "
                "aujourd'hui."
            )
        c1, c2 = st.columns(2)
        price_self = c1.number_input(
            "Tarif moyen de votre fournisseur d'electricite (euros/kWh)",
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

        acc_price_gross, acc_turpe_reduced, acc_pmo_fee_pct = get_acc_tariff_settings()
        is_acc_mode = export_mode == "Autoconsommation collective (tarif libre negocie)"

        if Investment.EXPORT_PRESETS[export_mode] is None:
            price_export = st.number_input(
                "Tarif de revente personnalise (euros/kWh)",
                min_value=0.0, max_value=1.0, value=0.10, step=0.001, format="%.4f",
            )
            turpe_reduced = 0.0
            pmo_fee_pct = 0.0
        elif is_acc_mode:
            price_export = acc_price_gross
            turpe_reduced = acc_turpe_reduced
            pmo_fee_pct = acc_pmo_fee_pct
            net_export_preview = max(price_export - turpe_reduced, 0.0)
            st.markdown(
                f"""
                <div style="background-color:#eaf7ec; border-left:6px solid #2e7d32;
                            border-radius:6px; padding:14px 18px; margin:10px 0 4px 0;">
                    <div style="font-size:1.15rem; font-weight:700; color:#1b5e20;">
                        Tarif fixe par Ivry Soleil Partage : {price_export:.4f} euros/kWh brut,
                        dont {turpe_reduced:.4f} euros/kWh de TURPE reduit ACC -- non
                        modifiable ici (voir onglet Administration).
                    </div>
                    <div style="font-size:1.15rem; font-weight:700; color:#1b5e20; margin-top:6px;">
                        Prix net effectif apres TURPE : {net_export_preview:.4f} euros/kWh
                        (au lieu de {price_export:.4f} euros/kWh brut).
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            price_export = Investment.EXPORT_PRESETS[export_mode]
            turpe_reduced = 0.0
            pmo_fee_pct = 0.0
            st.caption(f"Tarif retenu : {price_export:.4f} euros/kWh (valeur indicative).")

        if not is_acc_mode and (turpe_reduced > 0 or pmo_fee_pct > 0):
            net_export_preview = max(price_export * (1 - pmo_fee_pct) - turpe_reduced, 0.0)
            st.caption(
                f"Prix net effectif apres TURPE/PMO : {net_export_preview:.4f} euros/kWh "
                f"(au lieu de {price_export:.4f} euros/kWh brut)."
            )

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

        submitted = st.form_submit_button("Calculer", width="stretch")


    if submitted:

        if not is_existing_mode and total_panels_selected == 0:
            st.error(
                "Aucun panneau selectionne sur la toiture -- utilise les curseurs "
                "ci-dessus (ou \"Repartir automatiquement\") avant de calculer."
            )
            st.stop()

        if is_existing_mode and (annual_consumption_real <= 0 or annual_production_real <= 0):
            st.error(
                "Renseigne une consommation et une production annuelles reelles "
                "superieures a 0 pour calculer tes economies."
            )
            st.stop()

        with st.spinner("Calcul en cours..."):

            battery = None
            battery_charge_kwh = None
            battery_discharge_kwh = None
            total_production = None
            installed_kw_total = None

            if is_existing_mode:
                annual_production = float(annual_production_real)
                annual_consumption = float(annual_consumption_real)
                if annual_export_real_input > 0:
                    export_kwh = min(float(annual_export_real_input), annual_production)
                else:
                    export_kwh = max(annual_production - annual_consumption, 0.0)
                self_consumption = annual_production - export_kwh
                grid_import = max(annual_consumption - self_consumption, 0.0)
                self_consumption_rate = (self_consumption / annual_production) if annual_production else 0
            else:
                try:
                    weather = get_weather(lat, lon)
                except Exception as exc:
                    st.error(
                        "Impossible de recuperer les donnees meteo aupres de PVGIS "
                        f"(verifie la connexion internet et les coordonnees) : {exc}"
                    )
                    st.stop()

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
                turpe_reduced_eur_per_kwh=turpe_reduced, pmo_fee_ratio=pmo_fee_pct,
            )
            cf = investment.cashflow(self_consumption, export_kwh)
            payback = investment.payback_period(cf)
            van = investment.npv(cf)

        st.success("Calcul termine.")

        st.markdown('<div class="section-card section-card--energy">', unsafe_allow_html=True)
        st.subheader("Resultats -- energie")
        with st.expander("Comment lire ces resultats ?"):
            st.markdown(
                "Le **taux d'autoconsommation** est la part de la production "
                "solaire reellement utilisee sur place (le reste est exporte/"
                "revendu). Plus il est eleve, plus l'installation \"se suffit a "
                "elle-meme\" ; une batterie ou un decalage des usages vers la "
                "journee l'augmentent generalement."
            )
        k1, k2, k3, k4 = st.columns(4)
        if installed_kw_total is not None:
            k1.metric("Puissance installee", f"{installed_kw_total:.1f} kWc")
        else:
            k1.metric("Puissance installee", "non renseignee")
        k2.metric("Production annuelle", f"{annual_production:.0f} kWh")
        if is_existing_mode:
            reference_year = st.session_state.get(
                "_production_reference_year", dt.date.today().year
            )
            k2.caption(f"Base sur l'annee {reference_year}")
        k3.metric("Consommation annuelle", f"{annual_consumption:.0f} kWh")
        k4.metric("Taux d'autoconsommation", f"{self_consumption_rate * 100:.0f} %")

        k1, k2, k3 = st.columns(3)
        k1.metric("Autoconsomme", f"{self_consumption:.0f} kWh")
        k2.metric("Exporte / revendu", f"{export_kwh:.0f} kWh")
        k3.metric("Achete au reseau", f"{grid_import:.0f} kWh")
        if is_existing_mode and annual_export_real_input <= 0:
            st.caption(
                "L'energie injectee/revendue n'etait pas renseignee : elle a ete "
                "estimee ici comme (production - consommation), bornee a 0 -- "
                "renseigne-la ci-dessus si tu la connais precisement pour un "
                "resultat plus fiable."
            )

        if battery_charge_kwh is not None:
            k1, k2, k3 = st.columns(3)
            k1.metric("Energie stockee / an", f"{battery_charge_kwh:.0f} kWh")
            k2.metric("Energie restituee / an", f"{battery_discharge_kwh:.0f} kWh")
            cycles = battery_charge_kwh / battery_capacity if battery_capacity else 0
            k3.metric("Cycles equivalents / an", f"{cycles:.0f}")

        st.markdown('</div>', unsafe_allow_html=True)

        if not is_existing_mode:
            st.markdown('<div class="section-card section-card--finance">', unsafe_allow_html=True)
            st.subheader("Resultats -- investissement")
            with st.expander("Comment lire ces resultats ?"):
                st.markdown(
                    "Le **temps de retour** est le nombre d'annees necessaires pour "
                    "que les economies + revenus cumules compensent le cout net de "
                    "l'installation. La **VAN** (valeur actuelle nette) resume tout "
                    "le projet en un seul chiffre en euros d'aujourd'hui : positive, "
                    "elle signifie que le projet est rentable sur la duree choisie ; "
                    "negative, qu'il ne l'est pas (ou pas encore, sur cette duree)."
                )
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Cout total avant aides", f"{total_capex:.0f} euros")
            k2.metric("Cout net apres aides", f"{investment.net_cost:.0f} euros")
            k3.metric(
                "Temps de retour",
                f"{payback:.1f} ans" if payback is not None else f"> {duration_years} ans",
            )
            k4.metric("VAN", f"{van:.0f} euros")
            if battery_capacity > 0:
                st.caption(
                    f"Le cout total avant aides inclut le PV ({capex_pv:.0f} euros) et la "
                    f"batterie estimee a {battery_capex:.0f} euros "
                    f"({battery_capacity:.1f} kWh x {battery_price_per_kwh:.0f} euros/kWh)."
                )
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("**Repartition du gain annuel (annee 1)**")
        gain_autoconsommation = float(cf["Savings"].iloc[0])
        gain_revente = float(cf["Sales"].iloc[0])
        g1, g2 = st.columns(2)
        g1.metric(
            "Gain autoconsommation",
            f"{gain_autoconsommation:.0f} euros/an",
            help="Economie realisee car cette energie n'a pas eu besoin d'etre "
                 "achetee au reseau (autoconsommation x tarif fournisseur).",
        )
        g2.metric(
            "Gain revente du surplus",
            f"{gain_revente:.0f} euros/an",
            help="Revenu de l'energie exportee/revendue (Ivry Soleil Partage ou "
                 "obligation d'achat), net des frais TURPE/PMO le cas echeant.",
        )
        st.caption(
            "Ces deux gains sont complementaires : le premier vient de "
            "l'electricite que tu n'as plus besoin d'acheter, le second de la "
            "vente du surplus non autoconsomme. Leur somme constitue le "
            "benefice brut annuel utilise dans le calcul du temps de retour "
            "et de la VAN ci-dessus."
        )

        if total_production is not None:
            monthly = total_production.resample("ME").sum()
            fig1 = go.Figure(go.Bar(x=monthly.index.strftime("%b"), y=monthly.values))
            fig1.update_layout(
                title="Production mensuelle (kWh) -- annee meteo type",
                yaxis_title="kWh", xaxis_title="Mois",
            )
            st.plotly_chart(fig1, width="stretch")
            st.caption(
                "Base sur une \"annee meteo type\" PVGIS (Typical Meteorological "
                "Year) : une annee de reference reconstituee a partir de plusieurs "
                "annees reelles pour representer un climat moyen -- l'axe des mois "
                "ne correspond donc pas a une annee calendaire precise (l'annee "
                "affichee par les donnees brutes, ex. 1990, est une convention "
                "technique sans signification)."
            )
        else:
            st.caption(
                "Pas de repartition mensuelle disponible en mode \"installation "
                "existante\" (donnees annuelles uniquement)."
            )

        if not is_existing_mode:
            st.markdown('<div class="section-card section-card--finance">', unsafe_allow_html=True)
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=cf["Year"], y=cf["CumulativeNet"], mode="lines+markers", name="Cashflow cumule",
            ))
            fig2.add_hline(y=0, line_dash="dash", line_color="gray")
            fig2.update_layout(
                title="Cashflow cumule sur la duree du projet",
                xaxis_title="Annee", yaxis_title="euros",
            )
            st.plotly_chart(fig2, width="stretch")

            with st.expander("Detail du cashflow annuel"):
                cf_display = cf.copy()
                for _col in ("Savings", "Sales", "GrossBenefit", "LoanPayment", "NetCashflow", "CumulativeNet"):
                    if _col in cf_display.columns:
                        cf_display[_col] = cf_display[_col].round(0)
                st.dataframe(cf_display, width="stretch")
            st.markdown('</div>', unsafe_allow_html=True)

        producer_contribution = {
            "annual_production_kwh": float(annual_production),
            "installed_kw": installed_kw_total if installed_kw_total else None,
            "address": st.session_state.get("_selected_address_label", ""),
            "lat": lat, "lon": lon,
        }
        st.session_state["_producer_contribution"] = producer_contribution
        st.caption(
            "Ta production annuelle simulee ci-dessus peut etre ajoutee au "
            "total affiche en haut de page -- rejoins Ivry Soleil Partage "
            "tout en bas de la page pour la soumettre."
        )

    else:
        st.info("Renseigne tes informations ci-dessus puis clique sur *Calculer*.")


with tab_consommateur:

    st.subheader("\U0001F4C4 Estime tes economies avec Ivry Soleil Partage")
    st.caption(
        "Envoie ta facture EDF (PDF ou photo) : une IA (Claude, Anthropic) en "
        "extrait automatiquement les informations utiles (adresse, point de "
        "livraison, consommation annuelle...). Verifie/corrige les valeurs "
        "extraites avant de calculer tes economies potentielles."
    )

    with st.expander("Pourquoi une IA, et que devient ma facture ?"):
        st.markdown(
            "Les factures EDF ont des mises en page variables (fournisseur, "
            "option tarifaire, ancien/nouveau design...) : un modele de "
            "langage capable de lire des documents (Claude, modele Sonnet "
            "d'Anthropic) permet d'en extraire les champs utiles sans regles "
            "de mise en page figees. Ta facture est envoyee a l'API "
            "d'Anthropic uniquement pour cette analyse ponctuelle -- elle "
            "n'est pas stockee par Ivry Soleil Partage ; seuls les champs "
            "extraits (et que tu corriges) sont conserves si tu choisis de "
            "les soumettre a la communaute plus bas."
        )

    server_anthropic_key = ""
    try:
        server_anthropic_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        server_anthropic_key = ""

    if server_anthropic_key:
        anthropic_api_key = server_anthropic_key
        st.caption("Cle API Anthropic configuree cote serveur (non visible des visiteurs).")
    else:
        st.warning(
            "Aucune cle configuree cote serveur. Le champ ci-dessous est "
            "uniquement pour un test local : ne l'utilise jamais sur une app "
            "publique.",
            icon="⚠️",
        )
        anthropic_api_key = st.text_input(
            "Cle API Anthropic (test local uniquement)", value="", type="password",
            help="Stocke plutot la cle dans `.streamlit/secrets.toml` "
                 "(ANTHROPIC_API_KEY = \"...\") pour un usage durable/deploye.",
        )

    invoice_file = st.file_uploader(
        "Facture EDF (PDF, JPG ou PNG)", type=["pdf", "png", "jpg", "jpeg"],
    )

    if st.button("Analyser la facture", disabled=not (invoice_file and anthropic_api_key)):
        with st.spinner("Analyse de la facture en cours..."):
            try:
                extracted_data = extract_invoice_data(
                    invoice_file.getvalue(), invoice_file.name, anthropic_api_key,
                )
            except InvoiceExtractionError as exc:
                st.session_state["_invoice_error"] = str(exc)
                st.session_state["_invoice_extract"] = None
            else:
                st.session_state["_invoice_error"] = None
                st.session_state["_invoice_extract"] = extracted_data

    if st.session_state.get("_invoice_error"):
        st.error(st.session_state["_invoice_error"])

    extracted = st.session_state.get("_invoice_extract")
    if extracted:
        st.success("Facture analysee -- verifie/corrige les valeurs ci-dessous avant de continuer.")
        with st.form("invoice_review"):
            ic1, ic2 = st.columns(2)
            inv_address = ic1.text_input("Adresse", value=extracted.get("adresse") or "")
            inv_pdl = ic2.text_input("Point de livraison (PDL)", value=extracted.get("point_de_livraison") or "")
            ic3, ic4 = st.columns(2)
            inv_identity = ic3.text_input("Titulaire (nom ou raison sociale)", value=extracted.get("titulaire_nom") or "")
            inv_type = ic4.selectbox(
                "Type", ["particulier", "professionnel"],
                index=0 if (extracted.get("titulaire_type") or "particulier") != "professionnel" else 1,
            )
            ic5, ic6 = st.columns(2)
            inv_conso = ic5.number_input(
                "Consommation annuelle (kWh)", min_value=0.0, max_value=200000.0,
                value=float(extracted.get("consommation_annuelle_kwh") or 0.0), step=100.0,
            )
            inv_prix = ic6.number_input(
                "Prix moyen du kWh (euros) -- si connu",
                min_value=0.0, max_value=1.0,
                value=float(extracted.get("prix_moyen_kwh_eur") or 0.25), step=0.005, format="%.4f",
            )
            confiance = extracted.get("confiance")
            if confiance:
                st.caption(f"Confiance de l'IA sur ces valeurs : {confiance}.")
            if extracted.get("autres_infos_utiles"):
                with st.expander("Autres informations detectees sur la facture"):
                    st.json(extracted["autres_infos_utiles"])
            review_submitted = st.form_submit_button("Calculer mes economies potentielles")

        if review_submitted:
            st.session_state["_invoice_reviewed"] = {
                "address": inv_address, "pdl": inv_pdl, "identity": inv_identity,
                "type": inv_type, "consumption": inv_conso, "grid_price": inv_prix,
            }

    reviewed = st.session_state.get("_invoice_reviewed")
    if reviewed and reviewed["consumption"] > 0:
        st.subheader("\U0001F4B0 Economies potentielles avec l'autoconsommation collective")
        with st.expander("Comment ce calcul est fait ?"):
            st.markdown(
                "Faute de cle de repartition ACC reelle pour l'instant, on "
                "suppose qu'une partie de ta consommation annuelle pourrait "
                "etre couverte par l'energie solaire partagee de la "
                "communaute (taux ajustable ci-dessous). L'economie = "
                "(consommation couverte par l'ACC) x (prix reseau actuel - "
                "prix ACC propose). A affiner une fois les conventions de "
                "l'association et les donnees d'allocation reelles connues."
            )
        ec1, ec2 = st.columns(2)
        taux_couverture = ec1.slider(
            "Part de ta consommation couvrable par l'ACC (%)",
            0, 100, 30,
            help="Hypothese temporaire, en l'absence de cle de repartition reelle.",
        ) / 100
        prix_acc = ec2.number_input(
            "Prix propose pour l'energie ACC (euros/kWh)",
            min_value=0.0, max_value=1.0, value=0.15, step=0.005, format="%.4f",
            help="Tarif indicatif -- a fixer par la convention de l'association.",
        )
        energie_acc_kwh = reviewed["consumption"] * taux_couverture
        economie_eur = energie_acc_kwh * max(reviewed["grid_price"] - prix_acc, 0.0)

        k1, k2, k3 = st.columns(3)
        k1.metric("Consommation annuelle", f"{reviewed['consumption']:.0f} kWh")
        k2.metric("Energie couverte par l'ACC", f"{energie_acc_kwh:.0f} kWh")
        k3.metric("Economie annuelle estimee", f"{economie_eur:.0f} euros")

        consumer_contribution = {
            "identity": reviewed["identity"], "address": reviewed["address"],
            "pdl": reviewed["pdl"], "annual_consumption_kwh": float(reviewed["consumption"]),
            "annual_acc_kwh": float(energie_acc_kwh),
            "estimated_savings_eur": float(economie_eur),
            "invoice_extract": extracted,
        }
        st.session_state["_consumer_contribution"] = consumer_contribution
        st.caption(
            "Tes donnees peuvent etre ajoutees au total affiche en haut de "
            "page -- rejoins Ivry Soleil Partage tout en bas de la page pour "
            "les soumettre."
        )
    elif invoice_file and not anthropic_api_key:
        st.info("Renseigne une cle API Anthropic (ci-dessus) pour analyser la facture.")


with tab_admin:

    st.subheader("\U0001F510 Espace administrateur -- Ivry Soleil Partage")
    st.caption(
        "Validation des soumissions de production/consommation avant qu'elles "
        "ne comptent dans les totaux de la communaute affiches en haut de "
        "page, et reglage des objectifs annuels des deux piles."
    )

    server_admin_password = ""
    try:
        server_admin_password = st.secrets.get("ADMIN_PASSWORD", "")
    except Exception:
        server_admin_password = ""

    admin_password_input = st.text_input(
        "Mot de passe administrateur", type="password", key="_admin_pw",
    )
    is_admin = bool(server_admin_password) and admin_password_input == server_admin_password

    if not server_admin_password:
        st.warning(
            "Aucun mot de passe administrateur configure cote serveur "
            "(`ADMIN_PASSWORD` dans `.streamlit/secrets.toml`) -- cet onglet "
            "reste inaccessible tant qu'il n'est pas defini.",
            icon="⚠️",
        )
    elif not admin_password_input:
        st.info("Saisis le mot de passe administrateur pour acceder a cet espace.")
    elif not is_admin:
        st.error("Mot de passe incorrect.")

    if is_admin:
        st.success("Acces administrateur confirme.")

        st.markdown("### \U0001F3AF Objectifs annuels des piles")
        cur_prod_target, cur_conso_target = get_targets()
        with st.form("targets_form"):
            gt1, gt2 = st.columns(2)
            new_prod_target = gt1.number_input(
                "Objectif production annuelle (kWh)", min_value=1.0,
                value=float(cur_prod_target), step=500.0,
            )
            new_conso_target = gt2.number_input(
                "Objectif consommation ACC annuelle (kWh)", min_value=1.0,
                value=float(cur_conso_target), step=500.0,
            )
            if st.form_submit_button("Mettre a jour les objectifs"):
                set_targets(new_prod_target, new_conso_target)
                st.success("Objectifs mis a jour.")
                st.rerun()

        st.markdown("### \U0001F4B6 Tarif de revente ACC (fixe pour tous les membres)")
        st.caption(
            "Ces valeurs remplacent les champs TURPE/PMO qui etaient auparavant "
            "editables dans le formulaire de simulation (onglet Producteur) -- "
            "elles s'appliquent des qu'un-e utilisateur-ice choisit la "
            "configuration \"Autoconsommation collective\" pour la revente."
        )
        cur_acc_price, cur_turpe, cur_pmo = get_acc_tariff_settings()
        with st.form("tariff_form"):
            tf1, tf2, tf3 = st.columns(3)
            new_acc_price = tf1.number_input(
                "Prix brut ACC (euros/kWh)", min_value=0.0, max_value=1.0,
                value=float(cur_acc_price), step=0.005, format="%.4f",
            )
            new_turpe = tf2.number_input(
                "TURPE reduit ACC (euros/kWh)", min_value=0.0, max_value=0.5,
                value=float(cur_turpe), step=0.005, format="%.4f",
            )
            new_pmo_pct = tf3.number_input(
                "Frais de gestion PMO (%)", min_value=0.0, max_value=50.0,
                value=float(cur_pmo * 100), step=1.0,
            )
            if st.form_submit_button("Mettre a jour le tarif ACC"):
                set_acc_tariff_settings(new_acc_price, new_turpe, new_pmo_pct / 100)
                st.success("Tarif ACC mis a jour.")
                st.rerun()

        STATUS_LABELS = {
            STATUS_PENDING: "en attente", STATUS_APPROVED: "approuve",
            STATUS_REJECTED: "rejete",
        }

        st.markdown("### \U0001F506 Soumissions producteurs")
        sort_prod = st.selectbox(
            "Trier par",
            ["Date (recent d'abord)", "Production (decroissant)", "Production (croissant)"],
            key="_sort_producers",
        )
        all_producers_admin = list_producers()
        if sort_prod == "Production (decroissant)":
            all_producers_admin.sort(key=lambda s: s["annual_production_kwh"], reverse=True)
        elif sort_prod == "Production (croissant)":
            all_producers_admin.sort(key=lambda s: s["annual_production_kwh"])

        if not all_producers_admin:
            st.caption("Aucune soumission producteur.")
        for sub in all_producers_admin:
            with st.container(border=True):
                title = f"**{sub['name'] or '(sans nom)'}** -- {sub['annual_production_kwh']:.0f} kWh/an"
                if sub["installed_kw"]:
                    title += f", {sub['installed_kw']:.1f} kWc"
                title += f" -- *{STATUS_LABELS.get(sub['status'], sub['status'])}*"
                st.markdown(title)
                st.caption(
                    f"{sub['email']} -- {sub['address']} -- soumis le {sub['created_at'][:10]}"
                )
                bcol1, bcol2, bcol3, bcol4 = st.columns(4)
                if sub["status"] != STATUS_APPROVED:
                    if bcol1.button("Approuver", key=f"approve_prod_{sub['id']}"):
                        set_producer_status(sub["id"], STATUS_APPROVED)
                        st.rerun()
                if sub["status"] != STATUS_REJECTED:
                    if bcol2.button("Rejeter", key=f"reject_prod_{sub['id']}"):
                        set_producer_status(sub["id"], STATUS_REJECTED)
                        st.rerun()
                edit_clicked = bcol3.button("Modifier", key=f"edit_prod_{sub['id']}")
                if bcol4.button("Supprimer", key=f"delete_prod_{sub['id']}"):
                    delete_producer(sub["id"])
                    st.rerun()

                editing_key = f"_editing_prod_{sub['id']}"
                if edit_clicked:
                    st.session_state[editing_key] = True
                if st.session_state.get(editing_key):
                    with st.form(f"edit_prod_form_{sub['id']}"):
                        e1, e2 = st.columns(2)
                        edit_name = e1.text_input("Nom", value=sub["name"] or "")
                        edit_email = e2.text_input("Email", value=sub["email"] or "")
                        e3, e4 = st.columns(2)
                        edit_phone = e3.text_input("Telephone", value=sub["phone"] or "")
                        edit_address = e4.text_input("Adresse", value=sub["address"] or "")
                        e5, e6 = st.columns(2)
                        edit_prod_kwh = e5.number_input(
                            "Production annuelle (kWh)", min_value=0.0,
                            value=float(sub["annual_production_kwh"]), step=100.0,
                        )
                        edit_kw = e6.number_input(
                            "Puissance installee (kWc)", min_value=0.0,
                            value=float(sub["installed_kw"] or 0.0), step=0.5,
                        )
                        save_col, cancel_col = st.columns(2)
                        save_clicked = save_col.form_submit_button("Enregistrer")
                        cancel_clicked = cancel_col.form_submit_button("Annuler")
                    if save_clicked:
                        try:
                            update_producer(
                                sub["id"], name=edit_name, email=edit_email,
                                phone=edit_phone, address=edit_address,
                                annual_production_kwh=edit_prod_kwh,
                                installed_kw=edit_kw if edit_kw else None,
                            )
                        except Exception as exc:
                            st.error(f"Erreur : {exc}")
                        else:
                            st.session_state[editing_key] = False
                            st.rerun()
                    if cancel_clicked:
                        st.session_state[editing_key] = False
                        st.rerun()

        st.markdown("### \U0001F50C Soumissions consommateurs")
        sort_cons = st.selectbox(
            "Trier par",
            ["Date (recent d'abord)", "Consommation (decroissant)", "Consommation (croissant)"],
            key="_sort_consumers",
        )
        all_consumers_admin = list_consumers()
        if sort_cons == "Consommation (decroissant)":
            all_consumers_admin.sort(key=lambda s: s["annual_consumption_kwh"], reverse=True)
        elif sort_cons == "Consommation (croissant)":
            all_consumers_admin.sort(key=lambda s: s["annual_consumption_kwh"])

        if not all_consumers_admin:
            st.caption("Aucune soumission consommateur.")
        for sub in all_consumers_admin:
            with st.container(border=True):
                title = f"**{sub['name'] or '(sans nom)'}** -- {sub['annual_consumption_kwh']:.0f} kWh/an"
                if sub["annual_acc_kwh"]:
                    title += f", {sub['annual_acc_kwh']:.0f} kWh via ACC"
                title += f" -- *{STATUS_LABELS.get(sub['status'], sub['status'])}*"
                st.markdown(title)
                st.caption(
                    f"{sub['email']} -- {sub['address']} -- "
                    f"PDL {sub['pdl'] or 'non renseigne'} -- "
                    f"soumis le {sub['created_at'][:10]}"
                )
                bcol1, bcol2, bcol3, bcol4 = st.columns(4)
                if sub["status"] != STATUS_APPROVED:
                    if bcol1.button("Approuver", key=f"approve_cons_{sub['id']}"):
                        set_consumer_status(sub["id"], STATUS_APPROVED)
                        st.rerun()
                if sub["status"] != STATUS_REJECTED:
                    if bcol2.button("Rejeter", key=f"reject_cons_{sub['id']}"):
                        set_consumer_status(sub["id"], STATUS_REJECTED)
                        st.rerun()
                edit_clicked = bcol3.button("Modifier", key=f"edit_cons_{sub['id']}")
                if bcol4.button("Supprimer", key=f"delete_cons_{sub['id']}"):
                    delete_consumer(sub["id"])
                    st.rerun()

                editing_key = f"_editing_cons_{sub['id']}"
                if edit_clicked:
                    st.session_state[editing_key] = True
                if st.session_state.get(editing_key):
                    with st.form(f"edit_cons_form_{sub['id']}"):
                        e1, e2 = st.columns(2)
                        edit_name = e1.text_input("Nom", value=sub["name"] or "")
                        edit_email = e2.text_input("Email", value=sub["email"] or "")
                        e3, e4 = st.columns(2)
                        edit_phone = e3.text_input("Telephone", value=sub["phone"] or "")
                        edit_address = e4.text_input("Adresse", value=sub["address"] or "")
                        e5, e6 = st.columns(2)
                        edit_pdl = e5.text_input("PDL", value=sub["pdl"] or "")
                        edit_identity = e6.text_input("Titulaire", value=sub["identity"] or "")
                        e7, e8 = st.columns(2)
                        edit_conso_kwh = e7.number_input(
                            "Consommation annuelle (kWh)", min_value=0.0,
                            value=float(sub["annual_consumption_kwh"]), step=100.0,
                        )
                        edit_acc_kwh = e8.number_input(
                            "Energie ACC (kWh)", min_value=0.0,
                            value=float(sub["annual_acc_kwh"] or 0.0), step=100.0,
                        )
                        save_col, cancel_col = st.columns(2)
                        save_clicked = save_col.form_submit_button("Enregistrer")
                        cancel_clicked = cancel_col.form_submit_button("Annuler")
                    if save_clicked:
                        try:
                            update_consumer(
                                sub["id"], name=edit_name, email=edit_email,
                                phone=edit_phone, address=edit_address,
                                pdl=edit_pdl, identity=edit_identity,
                                annual_consumption_kwh=edit_conso_kwh,
                                annual_acc_kwh=edit_acc_kwh,
                            )
                        except Exception as exc:
                            st.error(f"Erreur : {exc}")
                        else:
                            st.session_state[editing_key] = False
                            st.rerun()
                    if cancel_clicked:
                        st.session_state[editing_key] = False
                        st.rerun()

        st.markdown("### \U0001F4B6 Facturation mensuelle (mandataire)")
        st.caption(
            "Ivry Soleil Partage agit comme mandataire de facturation pour le "
            "compte des producteurs : elle facture chaque consommateur au "
            "tarif ACC brut defini ci-dessus, preleve le TURPE reduit et sa "
            "commission de gestion, puis redistribue le solde aux producteurs "
            "au prorata de leur production du mois. Ce montage doit etre "
            "valide par un-e expert-comptable/juriste avant toute facturation "
            "reelle (mandat de facturation explicite de chaque producteur, "
            "mentions TVA a verifier)."
        )

        today = dt.date.today()
        bc1, bc2 = st.columns(2)
        billing_year = bc1.selectbox(
            "Annee", [today.year - 1, today.year, today.year + 1], index=1,
            key="_billing_year",
        )
        billing_month = bc2.selectbox(
            "Mois", list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: f"{m:02d}", key="_billing_month",
        )
        billing_period = f"{billing_year}-{billing_month:02d}"

        approved_producers_billing = [p for p in list_producers() if p["status"] == STATUS_APPROVED]
        approved_consumers_billing = [c for c in list_consumers() if c["status"] == STATUS_APPROVED]

        existing_billing_detail = get_billing_period_detail(billing_period)
        existing_cons_kwh = (
            {l["consumer_submission_id"]: l["kwh_acc"] for l in existing_billing_detail["consumers"]}
            if existing_billing_detail else {}
        )
        existing_prod_kwh = (
            {l["producer_submission_id"]: l["kwh_produced"] for l in existing_billing_detail["producers"]}
            if existing_billing_detail else {}
        )

        if not approved_producers_billing or not approved_consumers_billing:
            st.info(
                "Il faut au moins un producteur et un consommateur approuves "
                "pour calculer une periode de facturation."
            )
        else:
            with st.form(f"billing_form_{billing_period}"):
                st.markdown(
                    f"**kWh ACC consommes en {billing_period}** "
                    "(pre-rempli : moyenne annuelle / 12, a corriger avec les "
                    "vraies donnees du mois -- releve manuel ou, une fois "
                    "disponible, l'API Datahub Enedis)"
                )
                cons_kwh_inputs = {}
                for c in approved_consumers_billing:
                    base_kwh = c["annual_acc_kwh"] or c["annual_consumption_kwh"] or 0.0
                    default_kwh = existing_cons_kwh.get(c["id"], round(base_kwh / 12, 1))
                    cons_kwh_inputs[c["id"]] = st.number_input(
                        f"{c['name'] or '(sans nom)'} -- kWh ACC du mois",
                        min_value=0.0, value=float(default_kwh), step=10.0,
                        key=f"billing_cons_{billing_period}_{c['id']}",
                    )

                st.markdown(
                    f"**kWh produits en {billing_period}** "
                    "(pre-rempli : moyenne annuelle / 12, a corriger)"
                )
                prod_kwh_inputs = {}
                for p in approved_producers_billing:
                    default_kwh = existing_prod_kwh.get(
                        p["id"], round((p["annual_production_kwh"] or 0.0) / 12, 1),
                    )
                    prod_kwh_inputs[p["id"]] = st.number_input(
                        f"{p['name'] or '(sans nom)'} -- kWh produits du mois",
                        min_value=0.0, value=float(default_kwh), step=10.0,
                        key=f"billing_prod_{billing_period}_{p['id']}",
                    )

                billing_submitted = st.form_submit_button(
                    f"Calculer la facturation de {billing_period}"
                )

            if billing_submitted:
                try:
                    compute_billing_period(billing_period, cons_kwh_inputs, prod_kwh_inputs)
                except Exception as exc:
                    st.error(f"Erreur : {exc}")
                else:
                    st.success(f"Facturation de {billing_period} calculee.")
                    st.rerun()

        billing_detail = get_billing_period_detail(billing_period)
        if billing_detail:
            total_collected = sum(l["amount_eur"] for l in billing_detail["consumers"])
            total_paid_out = sum(l["amount_eur"] for l in billing_detail["producers"])
            retained = max(total_collected - total_paid_out, 0.0)

            s1, s2, s3 = st.columns(3)
            s1.metric("Facture aux consommateurs", f"{total_collected:.2f} euros")
            s2.metric("Redistribue aux producteurs", f"{total_paid_out:.2f} euros")
            s3.metric("TURPE + commission PMO retenus", f"{retained:.2f} euros")

            st.markdown(f"**Factures consommateurs -- {billing_period}**")
            for line in billing_detail["consumers"]:
                lc1, lc2, lc3, lc4, lc5 = st.columns([3, 2, 2, 2, 2])
                lc1.markdown(f"**{line['name'] or '(sans nom)'}**")
                lc2.caption(f"{line['kwh_acc']:.1f} kWh ACC")
                lc3.caption(f"{line['amount_eur']:.2f} euros")
                new_paid = lc4.checkbox(
                    "Payee", value=bool(line["paid"]), key=f"paid_cons_line_{line['id']}",
                )
                if new_paid != bool(line["paid"]):
                    set_consumer_line_paid(line["id"], new_paid)
                    st.rerun()
                lc5.download_button(
                    "PDF", data=generate_consumer_invoice_pdf(billing_period, line),
                    file_name=f"facture_{billing_period}_{(line['name'] or 'membre').replace(' ', '_')}.pdf",
                    mime="application/pdf", key=f"pdf_cons_line_{line['id']}",
                )

            st.markdown(f"**Versements producteurs -- {billing_period}**")
            for line in billing_detail["producers"]:
                lp1, lp2, lp3, lp4, lp5 = st.columns([3, 2, 2, 2, 2])
                lp1.markdown(f"**{line['name'] or '(sans nom)'}**")
                lp2.caption(f"{line['kwh_produced']:.1f} kWh produits")
                lp3.caption(f"{line['amount_eur']:.2f} euros")
                new_paid_p = lp4.checkbox(
                    "Versee", value=bool(line["paid"]), key=f"paid_prod_line_{line['id']}",
                )
                if new_paid_p != bool(line["paid"]):
                    set_producer_line_paid(line["id"], new_paid_p)
                    st.rerun()
                lp5.download_button(
                    "PDF", data=generate_producer_statement_pdf(billing_period, line),
                    file_name=f"releve_{billing_period}_{(line['name'] or 'membre').replace(' ', '_')}.pdf",
                    mime="application/pdf", key=f"pdf_prod_line_{line['id']}",
                )
        else:
            st.caption(f"Aucune facturation calculee pour {billing_period}.")

        past_periods = [p["period"] for p in list_billing_periods()]
        if past_periods:
            st.caption("Periodes deja facturees : " + ", ".join(past_periods))

        with st.expander("Historique complet (tableau brut, toutes colonnes)"):
            st.markdown("**Producteurs**")
            all_producers = list_producers()
            if all_producers:
                st.dataframe(all_producers, width="stretch")
            else:
                st.caption("Aucune soumission producteur.")
            st.markdown("**Consommateurs**")
            all_consumers = list_consumers()
            if all_consumers:
                st.dataframe(all_consumers, width="stretch")
            else:
                st.caption("Aucune soumission consommateur.")

# ------------------------------------------------------------------
# Rejoindre Ivry Soleil Partage : recueil de coordonnees volontaire,
# stockees UNIQUEMENT en local (base sqlite), jamais transmises a un
# tiers sans autorisation specifique et distincte de la personne.
# Reste hors des onglets : signal d'interet general, independant du
# volet producteur/consommateur utilise.
# ------------------------------------------------------------------
st.divider()
st.markdown('<div class="section-card section-card--join">', unsafe_allow_html=True)
st.subheader("\U0001F91D Rejoindre Ivry Soleil Partage")
st.caption(
    "Tu veux rejoindre Ivry Soleil Partage et contribuer a sa production et "
    "a sa consommation ? Laisse tes coordonnees ci-dessous -- entierement "
    "facultatif. Si tu as simule une production (onglet Producteur) ou "
    "verifie une facture (onglet Consommateur) plus haut, tu peux aussi "
    "cocher les cases correspondantes pour les ajouter aux totaux de la "
    "communaute, apres validation par un-e administrateur-ice."
)

with st.expander("Mentions RGPD -- a lire avant de transmettre tes donnees"):
    st.markdown(
        "**Qui recueille ces donnees ?** L'association *Ivry Soleil Partage* "
        "(en cours de constitution), responsable du traitement.\n\n"
        "**Pourquoi ?** Uniquement pour te recontacter dans le cadre de ce "
        "projet d'autoconsommation collective -- aucune prospection "
        "commerciale, aucune revente de donnees.\n\n"
        "**Base legale :** ton consentement explicite (article 6.1.a du "
        "RGPD), donne en cochant la case dediee ci-dessous.\n\n"
        "**Ou sont conservees ces donnees ?** Uniquement dans une base de "
        "donnees locale a cette application -- pas de service tiers, pas de "
        "cloud commercial.\n\n"
        "**Transmission a des partenaires :** tes coordonnees ne sont "
        "**jamais transmises a des partenaires** (installateurs, "
        "operateurs, collectivites...) sans une autorisation *specifique* "
        "et distincte de ta part (seconde case, decochee par defaut).\n\n"
        "**Duree de conservation :** 3 ans a compter du dernier contact, ou "
        "jusqu'a une demande de suppression de ta part.\n\n"
        "**Tes droits :** acces, rectification, effacement, limitation et "
        "opposition, a exercer a tout moment aupres de "
        "contact@ivrysoleilpartage.fr *(adresse a adapter)*. Tu peux aussi "
        "deposer une reclamation aupres de la CNIL (cnil.fr).\n\n"
        "_Ce texte est un point de depart, pas un avis juridique : a faire "
        "relire par un professionnel du droit avant toute collecte reelle, "
        "notamment pour confirmer la duree de conservation et le nom legal "
        "du responsable de traitement._"
    )

default_contact_address = st.session_state.get(
    "contact_address", st.session_state.get("_selected_address_label", "")
)

with st.form("contact_form", clear_on_submit=True):
    cf1, cf2 = st.columns(2)
    contact_first_name = cf1.text_input(
        "Prenom", value=st.session_state.get("contact_first_name", ""),
        key="contact_first_name",
    )
    contact_last_name = cf2.text_input(
        "Nom", value=st.session_state.get("contact_last_name", ""),
        key="contact_last_name",
    )
    cf3, cf4 = st.columns(2)
    contact_email = cf3.text_input(
        "Email", value=st.session_state.get("contact_email", ""), key="contact_email",
    )
    contact_phone = cf4.text_input(
        "Telephone", value=st.session_state.get("contact_phone", ""), key="contact_phone",
    )
    contact_address = st.text_input(
        "Adresse",
        value=default_contact_address,
        key="contact_address",
        help="Pre-remplie depuis la recherche d'adresse ci-dessus, ou depuis "
             "une facture analysee -- modifiable.",
    )

    contribute_production = False
    contribute_consumption = False
    if producer_contribution:
        contribute_production = st.checkbox(
            "Ajouter ma production annuelle simulee "
            f"({producer_contribution['annual_production_kwh']:.0f} kWh) a la "
            "pile de production de la communaute (onglet Producteur)."
        )
    if consumer_contribution:
        contribute_consumption = st.checkbox(
            "Ajouter ma consommation verifiee "
            f"({consumer_contribution['annual_consumption_kwh']:.0f} kWh, dont "
            f"{consumer_contribution['annual_acc_kwh']:.0f} kWh estimes couverts "
            "par l'ACC) a la pile de consommation de la communaute (onglet "
            "Consommateur)."
        )

    storage_consent = st.checkbox(
        "J'accepte que Ivry Soleil Partage conserve mes coordonnees (nom, "
        "prenom, email, telephone, adresse), et le cas echeant les chiffres "
        "de production/consommation coches ci-dessus, dans les conditions "
        "decrites ci-dessus -- ces derniers ne comptant dans les totaux de "
        "la communaute qu'apres validation par un-e administrateur-ice. "
        "(obligatoire pour envoyer le formulaire)"
    )
    partner_sharing_consent = st.checkbox(
        "J'autorise en plus Ivry Soleil Partage a transmettre mes "
        "coordonnees a des partenaires du projet si cela devient "
        "necessaire. (facultatif, decoche par defaut -- revocable a tout moment)"
    )
    contact_submitted = st.form_submit_button("Envoyer mes coordonnees", width="stretch")

if contact_submitted:
    missing = []
    if not contact_first_name.strip():
        missing.append("le prenom")
    if not contact_last_name.strip():
        missing.append("le nom")
    if not contact_email.strip() or not EMAIL_RE.match(contact_email.strip()):
        missing.append("un email valide")
    if not contact_phone.strip():
        missing.append("le telephone")
    if not storage_consent:
        missing.append("la case de consentement RGPD (obligatoire)")

    if missing:
        st.error("Merci de renseigner/cocher : " + ", ".join(missing) + ".")
    else:
        try:
            save_contact(
                contact_first_name, contact_last_name, contact_email,
                contact_phone, contact_address, lat, lon,
                storage_consent, partner_sharing_consent,
            )
        except Exception as exc:
            st.error(f"Erreur lors de l'enregistrement : {exc}")
        else:
            messages = ["Tes coordonnees ont ete enregistrees localement."]
            contact_full_name = f"{contact_first_name} {contact_last_name}".strip()

            if contribute_production and producer_contribution:
                try:
                    submit_producer(
                        contact_full_name, contact_email, contact_phone,
                        producer_contribution["address"] or contact_address,
                        producer_contribution["lat"], producer_contribution["lon"],
                        producer_contribution["annual_production_kwh"],
                        producer_contribution["installed_kw"],
                    )
                except Exception as exc:
                    st.error(f"Erreur lors de la soumission de ta production : {exc}")
                else:
                    messages.append(
                        "Ta production a ete soumise a la pile de la communaute."
                    )

            if contribute_consumption and consumer_contribution:
                try:
                    submit_consumer(
                        contact_full_name, contact_email, contact_phone,
                        consumer_contribution["address"] or contact_address,
                        consumer_contribution["pdl"], consumer_contribution["identity"],
                        consumer_contribution["annual_consumption_kwh"],
                        annual_acc_kwh=consumer_contribution["annual_acc_kwh"],
                        estimated_savings_eur=consumer_contribution["estimated_savings_eur"],
                        invoice_extract=consumer_contribution["invoice_extract"],
                    )
                except Exception as exc:
                    st.error(f"Erreur lors de la soumission de ta consommation : {exc}")
                else:
                    messages.append(
                        "Ta consommation a ete soumise a la pile de la communaute."
                    )

            messages.append("Ivry Soleil Partage te recontactera bientot.")
            st.success("Merci ! " + " ".join(messages))

st.markdown('</div>', unsafe_allow_html=True)
