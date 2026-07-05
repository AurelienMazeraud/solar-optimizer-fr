import streamlit as st
import plotly.graph_objects as go

from src.config import load_config
from src.weather import load_weather
from src.pv import Roof
from src.house import House
from src.energy import EnergyBalance, Battery
from src.finance import Investment
from src.solar_api import fetch_roof_segments, SolarApiError


st.set_page_config(
    page_title="Calculateur solaire & autoconsommation",
    page_icon="☀️",
    layout="wide",
)


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


cfg = load_defaults()

st.title("☀️ Calculateur d'efficacite de panneau solaire")
st.caption(
    "Simulation de production photovoltaique, autoconsommation, batterie et "
    "retour sur investissement, pour evaluer sa propre situation avant de "
    "rejoindre ou constituer une communaute d'autoconsommation collective."
)

# ------------------------------------------------------------------
# Localisation et nombre de pans de toiture : en dehors du formulaire
# pour que la recherche automatique du toit et la mise a jour du nombre
# de blocs soient immediates (les widgets dans un st.form ne
# redeclenchent pas de calcul avant validation).
# ------------------------------------------------------------------
st.subheader("\U0001F4CD Localisation")
c1, c2, c3 = st.columns(3)
lat = c1.number_input(
    "Latitude", min_value=-90.0, max_value=90.0,
    value=float(cfg["site"]["latitude"]) if cfg else 48.815, format="%.4f",
)
lon = c2.number_input(
    "Longitude", min_value=-180.0, max_value=180.0,
    value=float(cfg["site"]["longitude"]) if cfg else 2.385, format="%.4f",
)
altitude = c3.number_input(
    "Altitude (m)", min_value=0.0, max_value=4000.0,
    value=float(cfg["site"]["altitude"]) if cfg else 45.0,
)
st.caption("Coordonnees du site : via une carte (clic droit -> coordonnees GPS).")

with st.expander("\U0001F50E Reperage automatique du toit (Google Solar API, optionnel)"):
    st.caption(
        "Utilise la latitude/longitude ci-dessus pour recuperer automatiquement "
        "l'inclinaison, l'azimut et la surface de chaque pan de toiture detecte. "
        "10 000 requetes gratuites par mois chez Google — largement suffisant pour "
        "un usage ponctuel."
    )
    default_key = ""
    try:
        default_key = st.secrets.get("GOOGLE_SOLAR_API_KEY", "")
    except Exception:
        default_key = ""
    api_key = st.text_input(
        "Cle API Google Solar",
        value=default_key,
        type="password",
        help="Pour un usage durable/deploye, stocke plutot la cle dans "
             "`.streamlit/secrets.toml` (GOOGLE_SOLAR_API_KEY = \"...\") — "
             "ce fichier est deja exclu du depot Git.",
    )
    if st.button("Rechercher automatiquement mon toit"):
        try:
            segments = get_roof_segments(lat, lon, api_key)
        except SolarApiError as exc:
            st.error(str(exc))
        else:
            n_found = len(segments)
            st.session_state["n_sections"] = min(max(n_found, 1), 4)
            for i, seg in enumerate(segments):
                st.session_state[f"tilt_{i}"] = int(round(seg["tilt"]))
                st.session_state[f"az_{i}"] = int(round(seg["azimuth"]))
                st.session_state[f"area_{i}"] = round(seg["area"], 1)
            st.success(
                f"{n_found} pan(s) de toiture detecte(s) et pre-remplis ci-dessous "
                "(inclinaison, azimut, surface reelle du pan)."
            )

st.subheader("\U0001F3E0 Toiture(s)")
n_sections = st.number_input(
    "Nombre de pans de toiture exploites",
    min_value=1, max_value=4, value=2, step=1,
    key="n_sections",
)

defaults_roof = []
if cfg:
    for key_name in ("southwest", "northeast"):
        r = cfg.get("roof", {}).get(key_name, {})
        defaults_roof.append((r.get("tilt", 15), r.get("azimuth", 180), r.get("area", 20)))
while len(defaults_roof) < 4:
    defaults_roof.append((15, 180, 20))

with st.form("simulation"):

    roof_cols = st.columns(int(n_sections))
    roof_sections = []
    for i in range(int(n_sections)):
        with roof_cols[i]:
            st.markdown(f"**Pan {i + 1}**")
            tilt = st.number_input(
                "Inclinaison (°)", min_value=0, max_value=90,
                value=int(defaults_roof[i][0]), key=f"tilt_{i}",
            )
            azimuth = st.number_input(
                "Azimut (°)", min_value=0, max_value=360,
                value=int(defaults_roof[i][1]), key=f"az_{i}",
                help="0=Nord, 90=Est, 180=Sud, 270=Ouest",
            )
            area = st.number_input(
                "Surface exploitable (m²)", min_value=1.0, max_value=500.0,
                value=float(defaults_roof[i][2]), key=f"area_{i}",
            )
            roof_sections.append({"tilt": tilt, "azimuth": azimuth, "area": area})

    st.subheader("\U0001F527 Modules photovoltaiques")
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

    st.subheader("\U0001F50C Consommation du foyer")
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

    with st.spinner("Simulation en cours..."):

        try:
            weather = get_weather(lat, lon)
        except Exception as exc:
            st.error(
                "Impossible de recuperer les donnees meteo aupres de PVGIS "
                f"(verifie la connexion internet et les coordonnees) : {exc}"
            )
            st.stop()

        surface_panel = panel_width * panel_height
        panel_power_kw = panel_power / 1000

        total_production = None
        installed_kw_total = 0.0

        for section in roof_sections:
            n_panels = int(section["area"] / surface_panel)
            installed_kw = n_panels * panel_power_kw
            installed_kw_total += installed_kw

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
