"""Weather source via Open-Meteo (free, no API key).

Only runs when a location is configured: either `location: "City"` (geocoded
once through Open-Meteo's geocoding API) or explicit `latitude`/`longitude`.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from benchpet.events import EventBus, WeatherUpdated
from benchpet.sources.base import Source

log = logging.getLogger(__name__)

FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"

# WMO weather interpretation codes → short description.
DESCRIPTIONS = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle",
    57: "Freezing drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}
ICONS = {"storm": "⛈", "snow": "🌨", "windy_rain": "🌧", "rain": "🌧", "drizzle": "🌦",
         "windy": "💨", "hot": "🥵", "sunny": "☀", "clear_night": "🌙", "cloudy": "☁", "cold": "🥶"}

WINDY_KMH = 40
HOT_C = 28
COLD_C = 3


def condition(code: int, temp: float, wind_kmh: float, is_day: bool) -> str:
    """Map current weather to one of the pet's weather moods."""
    if code >= 95:
        return "storm"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    raining = 61 <= code <= 67 or 80 <= code <= 82
    if raining and wind_kmh >= WINDY_KMH:
        return "windy_rain"
    if raining:
        return "rain"
    if 51 <= code <= 57:
        return "drizzle"
    if wind_kmh >= WINDY_KMH:
        return "windy"
    if temp >= HOT_C:
        return "hot"
    if temp <= COLD_C:
        return "cold"
    if code <= 1:
        return "sunny" if is_day else "clear_night"
    return "cloudy"


def _get_json(url: str, params: dict) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": "bench-pet"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


class _Relay(QObject):
    loaded = Signal(object)


class WeatherSource(Source):
    name = "weather"

    def __init__(self, bus: EventBus, config: dict):
        super().__init__(bus)
        self.config = config
        self._coords: tuple[float, float] | None = None
        if config.get("latitude") is not None and config.get("longitude") is not None:
            self._coords = (float(config["latitude"]), float(config["longitude"]))
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="weather")
        self._relay = _Relay()
        self._relay.loaded.connect(self.bus.publish)
        self._timer = QTimer()
        self._timer.timeout.connect(self.reload)

    def start(self) -> None:
        if not self._coords and not self.config.get("location"):
            log.info("weather: no location configured (weather.location in config.yaml)")
            return
        self.reload()
        self._timer.start(self.config.get("refresh_minutes", 30) * 60_000)

    def stop(self) -> None:
        self._timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def reload(self) -> None:
        self._pool.submit(self._load)

    def _load(self) -> None:  # worker thread
        try:
            if self._coords is None:
                found = _get_json(GEOCODE, {"name": self.config["location"], "count": 1})
                if not found.get("results"):
                    log.warning("weather: couldn't find location %r", self.config["location"])
                    return
                place = found["results"][0]
                self._coords = (place["latitude"], place["longitude"])
            lat, lon = self._coords
            data = _get_json(FORECAST, {
                "latitude": lat, "longitude": lon, "wind_speed_unit": "kmh",
                "current": "temperature_2m,weather_code,wind_speed_10m,is_day"})
            cur = data["current"]
            code, temp = int(cur["weather_code"]), float(cur["temperature_2m"])
            wind, is_day = float(cur["wind_speed_10m"]), bool(cur["is_day"])
        except Exception as e:
            log.warning("weather: %s", e)
            return
        self._relay.loaded.emit(WeatherUpdated(
            condition=condition(code, temp, wind, is_day),
            temperature=temp,
            description=DESCRIPTIONS.get(code, "Unknown"),
        ))
