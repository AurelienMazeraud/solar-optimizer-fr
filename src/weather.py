from pvlib.iotools import get_pvgis_tmy


def load_weather(latitude,
                 longitude):

    weather, metadata = get_pvgis_tmy(
        latitude=latitude,
        longitude=longitude,
        outputformat="json"
    )

    weather.index = weather.index.tz_convert("Europe/Paris")

    return weather