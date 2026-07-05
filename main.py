from src.config import load_config

from src.weather import load_weather

from src.pv import Roof

from src.plots import monthly_energy

from src.house import House
from src.energy import EnergyBalance




config = load_config("config/maison.yaml")


weather = load_weather(

    config["site"]["latitude"],

    config["site"]["longitude"]

)


surface = (

    config["pv"]["panel_width"]

    *

    config["pv"]["panel_height"]

)

panel_power = config["pv"]["panel_power"] / 1000


# ---------- SOUTH WEST ----------

n_panels = int(

    config["roof"]["southwest"]["area"]

    /

    surface

)

installed_kw = n_panels * panel_power


roof_SW = Roof(

    weather,

    config["site"]["latitude"],

    config["site"]["longitude"],

    config["roof"]["southwest"]["tilt"],

    config["roof"]["southwest"]["azimuth"],

    installed_kw,

    config["pv"]["performance_ratio"],

    config["pv"]["inverter_efficiency"],

    config["site"]["altitude"]

)


prod_SW = roof_SW.simulate()


# ---------- NORTH EAST ----------

n_panels = int(

    config["roof"]["northeast"]["area"]

    /

    surface

)

installed_kw = n_panels * panel_power


roof_NE = Roof(

    weather,

    config["site"]["latitude"],

    config["site"]["longitude"],

    config["roof"]["northeast"]["tilt"],

    config["roof"]["northeast"]["azimuth"],

    installed_kw,

    config["pv"]["performance_ratio"],

    config["pv"]["inverter_efficiency"],

    config["site"]["altitude"]

)





prod_NE = roof_NE.simulate()


total = prod_SW + prod_NE

annual = total.sum()

print()

print("===========")

print(f"Production annuelle : {annual:.0f} kWh")

print("===========")

monthly_energy(total)




house=House(weather)

loads=house.total()

balance=EnergyBalance(

    total,

    loads["Total"]

).compute()

print()

print("Consommation annuelle")

print(loads["Total"].sum())

print()

print("Autoconsommation")

print(balance["SelfConsumption"].sum())

print()

print("Injection communauté")

print(balance["CommunityExport"].sum())

print()

print("Achat EDF")

print(balance["GridImport"].sum())

from src.economics import Economics

eco=Economics(balance)

print(eco.yearly())

