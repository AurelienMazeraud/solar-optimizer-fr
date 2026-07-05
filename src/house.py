import numpy as np
import pandas as pd


class House:
    """
    Modele de consommation domestique synthetique.

    La forme des courbes (base, chauffe-eau, PAC, VE) est un modele
    simplifie par usage. Chaque poste peut etre active/desactive et ses
    puissances ajustees. Si une consommation annuelle cible est connue
    (par exemple un releve Linky), le profil entier peut etre recale
    dessus via annual_target_kwh, en conservant la forme des courbes.
    """

    def __init__(
        self,
        weather,
        base_load_kw=0.35,
        morning_boost_kw=0.7,
        evening_boost_kw=1.1,
        include_water_heater=True,
        water_heater_kw=1.5,
        include_heat_pump=True,
        heat_pump_cop=3,
        include_phev=True,
        phev_kw=1.5,
        annual_target_kwh=None,
    ):
        self.weather = weather
        self.base_load_kw = base_load_kw
        self.morning_boost_kw = morning_boost_kw
        self.evening_boost_kw = evening_boost_kw
        self.include_water_heater = include_water_heater
        self.water_heater_kw = water_heater_kw
        self.include_heat_pump = include_heat_pump
        self.heat_pump_cop = heat_pump_cop
        self.include_phev = include_phev
        self.phev_kw = phev_kw
        self.annual_target_kwh = annual_target_kwh

    def base_load(self):

        h = self.weather.index.hour

        load = np.ones(len(h)) * self.base_load_kw

        # matin
        load[(h >= 6) & (h <= 8)] += self.morning_boost_kw

        # soir
        load[(h >= 18) & (h <= 22)] += self.evening_boost_kw

        return pd.Series(load, index=self.weather.index)

    def water_heater(self):

        h = self.weather.index.hour

        load = np.zeros(len(h))

        if self.include_water_heater:
            load[(h >= 2) & (h < 4)] = self.water_heater_kw

        return pd.Series(load, index=self.weather.index)

    def heat_pump(self):

        if not self.include_heat_pump:
            return pd.Series(0.0, index=self.weather.index)

        temp = self.weather["temp_air"]

        demand = np.maximum(0, 18 - temp)

        hp = demand / 10 / self.heat_pump_cop

        return pd.Series(hp, index=self.weather.index)

    def phev(self):

        h = self.weather.index.hour

        load = np.zeros(len(h))

        if self.include_phev:
            # recharge nocturne
            load[(h >= 1) & (h < 3)] = self.phev_kw

        return pd.Series(load, index=self.weather.index)

    def total(self):

        base = self.base_load()
        hp = self.heat_pump()
        wh = self.water_heater()
        ev = self.phev()

        total = base + hp + wh + ev

        if self.annual_target_kwh is not None and total.sum() > 0:
            scale = self.annual_target_kwh / total.sum()
            base = base * scale
            hp = hp * scale
            wh = wh * scale
            ev = ev * scale
            total = total * scale

        return pd.DataFrame({
            "Base": base,
            "PAC": hp,
            "WaterHeater": wh,
            "PHEV": ev,
            "Total": total,
        })
