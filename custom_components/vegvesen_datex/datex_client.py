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
)


@dataclass
class DatexResult:
    status: str               # "åpen" | "stengt" | "restriksjon" | "ukjent"
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

    # -------------------------
    # HTTP fetchers
    # -------------------------
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

    # -------------------------
    # Helpers / parsing
    # -------------------------
    @staticmethod
    def _flatten_text(xml_bytes: bytes) -> str:
        root = DET.fromstring(xml_bytes)
        txt = " ".join(t.strip() for t in root.itertext() if t and t.strip())
        return re.sub(r"\s+", " ", txt)

    @staticmethod
    def _first_number_under(node) -> float | None:
        """Find the first numeric text under a node (best-effort)."""
        if node is None:
            return None
        for child in node.iter():
            if child.text and re.match(r"^-?\d+(\.\d+)?$", child.text.strip()):
                return float(child.text.strip())
        return None

    # -------------------------
    # Public API
    # -------------------------
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

    async def list_sites(self, filter_text: str | None = None, limit: int = 200) -> list[tuple[str, str]]:
        """Return a list of (site_id, site_name) filtered by name (case-insensitive)."""
        xml_bytes = await self.fetch_weather_site_table()
        root = DET.fromstring(xml_bytes)

        filter_l = (filter_text or "").strip().lower()
        out: list[tuple[str, str]] = []

        # Typical DATEX structure: measurementSiteRecord id + measurementSiteName
        for rec in root.findall(".//{*}measurementSiteRecord"):
            site_id = rec.get("id")
            name_el = rec.find(".//{*}measurementSiteName")
            site_name = name_el.text.strip() if (name_el is not None and name_el.text) else None

            if not site_id or not site_name:
                continue
            if filter_l and filter_l not in site_name.lower():
                continue

            out.append((site_id, site_name))
            if len(out) >= limit:
                break

        return out

    async def get_wind_for_site(self, site_id: str) -> tuple[float | None, float | None]:
        """Return (wind_speed_ms, wind_dir_deg) for a given site_id, if present."""
        xml_bytes = await self.fetch_measured_weather()
        root = DET.fromstring(xml_bytes)

        for sm in root.findall(".//{*}siteMeasurements"):
            ref = sm.find(".//{*}measurementSiteReference")
            if ref is None or ref.get("id") != site_id:
                continue

            ws = sm.find(".//{*}windSpeed")
            wd = sm.find(".//{*}windDirectionBearing")

            wind_ms = self._first_number_under(ws)
            wind_deg = self._first_number_under(wd)
            return wind_ms, wind_deg

        return None, None
