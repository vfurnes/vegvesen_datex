from __future__ import annotations

import re
from dataclasses import dataclass

import aiohttp
from defusedxml import ElementTree as DET
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    SITUATION_URL_DEFAULT,
    WEATHER_SITE_TABLE_URL_DEFAULT,
    MEASURED_WEATHER_URL_DEFAULT,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_GUST,
    ENTITY_WIND_DIRECTION,
    ENTITY_TEMPERATURE,
    ENTITY_HUMIDITY,
    ENTITY_PRESSURE,
    ENTITY_PRECIP_INTENSITY,
)


@dataclass
class DatexResult:
    status: str
    is_closed: bool
    message: str | None
    matched: bool
    source: str


class DatexClient:
    def __init__(self, hass, username: str, password: str, url: str = SITUATION_URL_DEFAULT) -> None:
        self._hass = hass
        self._username = username
        self._password = password
        self._url = url

    async def fetch_situation(self) -> bytes:
        session = async_get_clientsession(self._hass)
        async with session.get(
            self._url,
            auth=aiohttp.BasicAuth(self._username, self._password),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def fetch_weather_site_table(self) -> bytes:
        session = async_get_clientsession(self._hass)
        async with session.get(
            WEATHER_SITE_TABLE_URL_DEFAULT,
            auth=aiohttp.BasicAuth(self._username, self._password),
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def fetch_measured_weather(self) -> bytes:
        session = async_get_clientsession(self._hass)
        async with session.get(
            MEASURED_WEATHER_URL_DEFAULT,
            auth=aiohttp.BasicAuth(self._username, self._password),
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    @staticmethod
    def _flatten_text(xml_bytes: bytes) -> str:
        root = DET.fromstring(xml_bytes)
        txt = " ".join(t.strip() for t in root.itertext() if t and t.strip())
        return re.sub(r"\s+", " ", txt)

    @staticmethod
    def _first_number_under(node) -> float | None:
        if node is None:
            return None
        for child in node.iter():
            if child.text and re.match(r"^-?\d+(\.\d+)?$", child.text.strip()):
                return float(child.text.strip())
        return None

    async def get_status_for_query(self, query: str) -> DatexResult:
        xml_bytes = await self.fetch_situation()
        text = self._flatten_text(xml_bytes)
        low = text.lower()
        q = (query or "").strip().lower()

        matched = bool(q) and (q in low)

        closed_words = ("stengt", "closed", "stenging", "road closed", "bridge closed")
        restr_words = (
            "restriks",
            "restricted",
            "kolonne",
            "convoy",
            "høy",
            "high-sided",
            "fare for stengt",
            "wind",
        )

        status = "ukjent"
        is_closed = False
        msg = None

        if matched:
            if any(w in low for w in closed_words):
                status = "stengt"
                is_closed = True
            elif any(w in low for w in restr_words):
                status = "restriksjon"
            else:
                status = "åpen"

            idx = low.find(q)
            if idx >= 0:
                start = max(0, idx - 120)
                end = min(len(text), idx + 180)
                msg = text[start:end].strip()
        elif q:
            status = "åpen"

        return DatexResult(
            status=status,
            is_closed=is_closed,
            message=msg,
            matched=matched,
            source=self._url,
        )

    async def list_sites(self, filter_text: str | None = None, limit: int = 500) -> list[tuple[str, str]]:
        """Return [(site_id, site_name), ...] from GetMeasurementWeatherSiteTable.

        Filter uses case-insensitive 'contains' on site_name.
        """
        xml_bytes = await self.fetch_weather_site_table()
        root = DET.fromstring(xml_bytes)

        filter_l = (filter_text or "").strip().lower()
        out: list[tuple[str, str]] = []

        for site in root.findall(".//{*}measurementSite"):
            site_id = site.get("id")
            if not site_id:
                continue

            # pick display name
            name: str | None = None
            name_el = site.find(".//{*}measurementSiteName")
            if name_el is not None:
                candidates = name_el.findall(".//{*}value")
                if candidates:

                    def score(v):
                        lang = (v.get("lang") or "").lower()
                        if lang in ("nob", "nb", "no"):
                            return 0
                        if lang == "en":
                            return 1
                        return 2

                    best = sorted(candidates, key=score)[0]
                    if best.text:
                        name = best.text.strip()

            if not name:
                txt = site.findtext(".//{*}measurementSiteName")
                if txt:
                    name = txt.strip()

            if not name:
                continue

            if filter_l and filter_l not in name.lower() and filter_l not in site_id.lower():
                continue

            out.append((site_id, name))
            if len(out) >= limit:
                break

        out.sort(key=lambda x: x[1].lower())
        return out

    async def get_measurements_for_site(self, site_id: str) -> dict[str, float | None]:
        """Return a dict of detected measurements for a site_id."""
        xml_bytes = await self.fetch_measured_weather()
        root = DET.fromstring(xml_bytes)

        # Find siteMeasurements with matching reference id
        for sm in root.findall(".//{*}siteMeasurements"):
            ref = sm.find(".//{*}measurementSiteReference")
            if ref is None or (ref.get("id") or "").strip() != (site_id or "").strip():
                continue

            # Common tags. Keep resilient: if not present -> None
            wind_speed = self._first_number_under(sm.find(".//{*}windSpeed"))

            # Vindkast / maks vind: DATEX kan bruke "maximumWindSpeed" (og noen ganger andre varianter)
            wind_gust = (
                self._first_number_under(sm.find(".//{*}maximumWindSpeed"))
                or self._first_number_under(sm.find(".//{*}maximumWindSpeedOverInterval"))
                or self._first_number_under(sm.find(".//{*}maximumWindSpeedValue"))
            )

            wind_dir = self._first_number_under(sm.find(".//{*}windDirectionBearing"))

            temp = self._first_number_under(sm.find(".//{*}airTemperature"))
            rh = self._first_number_under(sm.find(".//{*}relativeHumidity"))
            pressure = self._first_number_under(sm.find(".//{*}atmosphericPressure"))
            precip = self._first_number_under(sm.find(".//{*}precipitationIntensity"))

            out = {
                ENTITY_WIND_SPEED: wind_speed,
                ENTITY_WIND_GUST: wind_gust,
                ENTITY_WIND_DIRECTION: wind_dir,
                ENTITY_TEMPERATURE: temp,
                ENTITY_HUMIDITY: rh,
                ENTITY_PRESSURE: pressure,
                ENTITY_PRECIP_INTENSITY: precip,
            }

            return out

        return {}
