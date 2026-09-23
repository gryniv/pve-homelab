"""Weather from Open-Meteo (no API key), cached per city/units for 15 minutes."""

import time

import aiohttp

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FC = "https://api.open-meteo.com/v1/forecast"
TTL = 900

_cache = {}
_geo = {}


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


TEXT = {"clear": "ясно", "partly": "мінлива хмарність", "overcast": "хмарно", "fog": "туман",
        "rain": "дощ", "snow": "сніг", "thunder": "гроза"}


async def get(city, units="c"):
    key = (city.lower(), units)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        if city.lower() not in _geo:
            async with s.get(GEO, params={"name": city, "count": 1, "language": "uk"}) as r:
                res = (await r.json()).get("results") or []
            if not res:
                raise ValueError(f"Місто «{city}» не знайдено")
            _geo[city.lower()] = res[0]
        g = _geo[city.lower()]
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
        "text": TEXT[k],
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
    _cache[key] = (time.time(), data)
    return data
