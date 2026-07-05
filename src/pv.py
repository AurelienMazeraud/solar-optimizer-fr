import numpy as np
import pandas as pd

import pvlib


class Roof:

    def __init__(self,
                 weather,
                 latitude,
                 longitude,
                 tilt,
                 azimuth,
                 installed_power_kw,
                 performance_ratio=1.0,
                 inverter_efficiency=1.0,
                 altitude=0.0):

        self.weather = weather
        self.latitude = latitude
        self.longitude = longitude
        self.tilt = tilt
        self.azimuth = azimuth
        self.installed_power_kw = installed_power_kw
        self.performance_ratio = performance_ratio
        self.inverter_efficiency = inverter_efficiency
        self.altitude = altitude

    def simulate(self):

        solar_position = pvlib.solarposition.get_solarposition(
            self.weather.index,
            self.latitude,
            self.longitude,
            altitude=self.altitude
        )

        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt=self.tilt,
            surface_azimuth=self.azimuth,
            dni=self.weather["dni"],
            ghi=self.weather["ghi"],
            dhi=self.weather["dhi"],
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )

        irradiance = poa["poa_global"]

        power = self.installed_power_kw * irradiance / 1000

        power = power * self.performance_ratio * self.inverter_efficiency

        power = power.clip(lower=0)

        return power
