"""Weather from Open-Meteo (no API key), cached per city/units for 15 minutes."""

import time

import aiohttp

from .i18n import _, lang

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FC = "https://api.open-meteo.com/v1/forecast"
TTL = 900

_cache = {}
_geo = {}
MAX_ENTRIES = 64  # anyone can ask for any city: keep the caches bounded


def _put(d, key, value):
    d[key] = value
    while len(d) > MAX_ENTRIES:
        d.pop(next(iter(d)))


def kind(code):
    if code in (0, 1):
        return "clear"
    if code == 2:
        return "partly"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if code in range(95, 100):
        return "thunder"
    if code in range(71, 78) or code in (85, 86):
        return "snow"
    return "rain"




async def get(city, units="c"):
    key = (city.lower(), units, lang.get())
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        geo_key = (city.lower(), lang.get())
        if geo_key not in _geo:
            async with s.get(GEO, params={"name": city, "count": 1, "language": lang.get()}) as r:
                res = (await r.json()).get("results") or []
            if not res:
                raise ValueError(_("city_not_found", city=city))
            _put(_geo, geo_key, res[0])
        g = _geo[geo_key]
        params = {
            "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto",
            "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 4,
        }
        if units == "f":
            params.update(temperature_unit="fahrenheit", wind_speed_unit="mph")
        else:
            params["wind_speed_unit"] = "ms"
        async with s.get(FC, params=params) as r:
            d = await r.json()
    cur, daily = d["current"], d["daily"]
    k = kind(cur["weather_code"])
    data = {
        "city": g.get("name", city),
        "units": units,
        "kind": k,
        "temp": round(cur["temperature_2m"]),
        "wind": round(cur["wind_speed_10m"]),
        "humidity": cur["relative_humidity_2m"],
        "is_day": bool(cur["is_day"]),
        "days": [
            {"date": daily["time"][i], "kind": kind(daily["weather_code"][i]),
             "max": round(daily["temperature_2m_max"][i]), "min": round(daily["temperature_2m_min"][i])}
            for i in range(1, len(daily["time"]))
        ],
    }
    _put(_cache, key, (time.time(), data))
    return data
