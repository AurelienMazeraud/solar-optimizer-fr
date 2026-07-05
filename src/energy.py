import numpy as np
import pandas as pd


class Battery:
    """
    Modele simplifie de batterie stationnaire (domicile).

    capacity_kwh : capacite utile totale (kWh).
    max_power_kw : puissance maximale de charge/decharge (kW). Par defaut,
        environ C/2 (regime courant des batteries residentielles LFP).
    round_trip_efficiency : rendement aller-retour (charge + decharge),
        typiquement 0.85-0.95 pour une batterie lithium domestique.
    min_soc / max_soc : bornes de l'etat de charge utilisable, en fraction
        de la capacite (protege la duree de vie de la batterie).
    initial_soc : etat de charge de depart, en fraction de la capacite.
    """

    def __init__(
        self,
        capacity_kwh,
        max_power_kw=None,
        round_trip_efficiency=0.90,
        min_soc=0.10,
        max_soc=1.00,
        initial_soc=0.5,
    ):
        self.capacity_kwh = capacity_kwh
        self.max_power_kw = max_power_kw if max_power_kw is not None else capacity_kwh / 2
        self.round_trip_efficiency = round_trip_efficiency
        self.min_soc = min_soc
        self.max_soc = max_soc
        self.initial_soc = initial_soc


class EnergyBalance:
    """
    Bilan energetique horaire entre production PV et consommation du foyer.

    Sans batterie (battery=None) : autoconsommation directe = min(PV, Load)
    a chaque pas de temps (calcul vectorise, identique au comportement
    d'origine).

    Avec batterie : simulation heure par heure de la charge (sur le
    surplus PV) et de la decharge (sur le manque), avec pertes de
    rendement, pour deplacer une partie du surplus de journee vers les
    heures de manque (matin/soir), ce qui augmente l'autoconsommation.
    """

    def __init__(self, pv, load, battery=None):

        self.pv = pv
        self.load = load
        self.battery = battery

    def compute(self):

        if self.battery is None or self.battery.capacity_kwh <= 0:
            return self._compute_without_battery()

        return self._compute_with_battery()

    def _compute_without_battery(self):

        df = pd.DataFrame(index=self.pv.index)

        df["PV"] = self.pv

        df["Load"] = self.load

        df["SelfConsumption"] = df[["PV", "Load"]].min(axis=1)

        df["GridImport"] = (df["Load"] - df["PV"]).clip(lower=0)

        df["CommunityExport"] = (df["PV"] - df["Load"]).clip(lower=0)

        df["BatteryCharge"] = 0.0
        df["BatteryDischarge"] = 0.0
        df["BatterySOC"] = 0.0

        return df

    def _compute_with_battery(self):

        pv = self.pv.to_numpy(dtype=float)
        load = self.load.to_numpy(dtype=float)
        n = len(pv)

        battery = self.battery
        capacity = battery.capacity_kwh
        max_power = battery.max_power_kw

        # rendement reparti pour moitie a la charge, moitie a la decharge
        leg_efficiency = battery.round_trip_efficiency ** 0.5

        max_energy = capacity * battery.max_soc
        min_energy = capacity * battery.min_soc
        soc = capacity * battery.initial_soc
        soc = min(max(soc, min_energy), max_energy)

        self_consumption = np.zeros(n)
        grid_import = np.zeros(n)
        community_export = np.zeros(n)
        battery_charge = np.zeros(n)
        battery_discharge = np.zeros(n)
        soc_series = np.zeros(n)

        for i in range(n):

            production = pv[i]
            demand = load[i]

            direct = min(production, demand)
            surplus = production - direct
            deficit = demand - direct

            charge = 0.0
            discharge = 0.0

            if surplus > 0:
                room = max(max_energy - soc, 0.0)
                max_charge_for_room = room / leg_efficiency if leg_efficiency > 0 else 0.0
                charge = min(surplus, max_power, max_charge_for_room)
                soc += charge * leg_efficiency
                surplus -= charge

            if deficit > 0:
                available = max(soc - min_energy, 0.0)
                max_discharge_available = available * leg_efficiency
                discharge = min(deficit, max_power, max_discharge_available)
                soc -= discharge / leg_efficiency if leg_efficiency > 0 else 0.0
                deficit -= discharge

            self_consumption[i] = direct + discharge
            community_export[i] = surplus
            grid_import[i] = deficit
            battery_charge[i] = charge
            battery_discharge[i] = discharge
            soc_series[i] = soc

        df = pd.DataFrame({
            "PV": self.pv,
            "Load": self.load,
            "SelfConsumption": self_consumption,
            "GridImport": grid_import,
            "CommunityExport": community_export,
            "BatteryCharge": battery_charge,
            "BatteryDischarge": battery_discharge,
            "BatterySOC": soc_series,
        }, index=self.pv.index)

        return df
