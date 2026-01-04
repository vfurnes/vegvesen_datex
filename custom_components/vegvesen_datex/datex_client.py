from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
import async_timeout
import xml.etree.ElementTree as ET

from .const import (
    MEASURED_WEATHER_URL_DEFAULT,
    SITUATION_URL_DEFAULT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class MeasuredValue:
    value: float | int | None
    time_value: str | None = None
    period_start: str | None = None
    period_end: str | None = None


class DatexClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        measured_weather_url: str = MEASURED_WEATHER_URL_DEFAULT,
        situation_url: str = SITUATION_URL_DEFAULT,
        request_timeout: int = 30,
    ) -> None:
        self._session = session
        self._auth = aiohttp.BasicAuth(username, password)
        self._measured_weather_url = measured_weather_url
        self._situation_url = situation_url
        self._timeout = request_timeout

    async def _get_text(self, url: str) -> str:
        async with async_timeout.timeout(self._timeout):
            async with self._session.get(url, auth=self._auth) as resp:
                resp.raise_for_status()
                return await resp.text()

    async def fetch_measured_weather_site(self, site_id: str) -> dict[str, MeasuredValue]:
        """Fetch and parse GetMeasuredWeatherData for one measurement site id."""
        xml_text = await self._get_text(self._measured_weather_url)
        return self._parse_measured_weather_site(xml_text, site_id)

    def _parse_measured_weather_site(self, xml_text: str, site_id: str) -> dict[str, MeasuredValue]:
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        def find_first_text(elem: ET.Element, wanted: list[str]) -> str | None:
            # wanted = ["measurementTimeDefault/timeValue"] etc (localname path)
            parts = wanted[0].split("/")
            cur = elem
            for part in parts:
                found = None
                for ch in cur:
                    if _local(ch.tag) == part:
                        found = ch
                        break
                if found is None:
                    return None
                cur = found
            return (cur.text or "").strip() or None

        def find_path(elem: ET.Element, path: str) -> ET.Element | None:
            parts = path.split("/")
            cur = elem
            for part in parts:
                found = None
                for ch in cur:
                    if _local(ch.tag) == part:
                        found = ch
                        break
                if found is None:
                    return None
                cur = found
            return cur

        # Find correct <siteMeasurements> for this site_id
        site_measurements = None
        for sm in root.iter():
            if _local(sm.tag) != "siteMeasurements":
                continue
            ref = find_path(sm, "measurementSiteReference")
            if ref is None:
                continue
            if ref.attrib.get("id") == str(site_id):
                site_measurements = sm
                break

        if site_measurements is None:
            _LOGGER.debug("No siteMeasurements found for site_id=%s", site_id)
            return {}

        default_time = find_first_text(site_measurements, ["measurementTimeDefault/timeValue"])

        results: dict[str, MeasuredValue] = {}

        # Iterate physicalQuantity blocks
        for pq in list(site_measurements):
            if _local(pq.tag) != "physicalQuantity":
                continue

            # Prefer measurementOrCalculationTime/timeValue if present, else fallback to measurementTimeDefault
            time_value = None
            moc = find_path(pq, "basicData/measurementOrCalculationTime/timeValue")
            if moc is not None and (moc.text or "").strip():
                time_value = moc.text.strip()
            else:
                time_value = default_time

            # Period (only when present)
            period_start = None
            period_end = None
            ps = find_path(pq, "basicData/measurementOrCalculationTime/period/startOfPeriod")
            pe = find_path(pq, "basicData/measurementOrCalculationTime/period/endOfPeriod")
            if ps is not None and (ps.text or "").strip():
                period_start = ps.text.strip()
            if pe is not None and (pe.text or "").strip():
                period_end = pe.text.strip()

            # HUMIDITY
            perc = find_path(pq, "basicData/humidity/relativeHumidity/percentage")
            if perc is not None and (perc.text or "").strip():
                try:
                    results["humidity"] = MeasuredValue(
                        value=float(perc.text.strip()),
                        time_value=time_value,
                    )
                except ValueError:
                    pass
                continue

            # AIR TEMPERATURE
            temp = find_path(pq, "basicData/temperature/airTemperature/temperature")
            if temp is not None and (temp.text or "").strip():
                try:
                    results["temperature"] = MeasuredValue(
                        value=float(temp.text.strip()),
                        time_value=time_value,
                    )
                except ValueError:
                    pass
                continue

            # WIND DIRECTION
            dirb = find_path(pq, "basicData/wind/windDirectionBearing/directionBearing")
            if dirb is not None and (dirb.text or "").strip():
                try:
                    results["wind_direction"] = MeasuredValue(
                        value=int(float(dirb.text.strip())),
                        time_value=time_value,
                    )
                except ValueError:
                    pass
                continue

            # WIND GUST (maximumWindSpeed)
            gust = find_path(pq, "basicData/wind/maximumWindSpeed/windSpeed")
            if gust is not None and (gust.text or "").strip():
                try:
                    results["wind_gust"] = MeasuredValue(
                        value=float(gust.text.strip()),
                        time_value=time_value,
                        period_start=period_start,
                        period_end=period_end,
                    )
                except ValueError:
                    pass
                continue

            # WIND SPEED (windSpeed)
            ws = find_path(pq, "basicData/wind/windSpeed/windSpeed")
            if ws is not None and (ws.text or "").strip():
                try:
                    results["wind_speed"] = MeasuredValue(
                        value=float(ws.text.strip()),
                        time_value=time_value,
                    )
                except ValueError:
                    pass
                continue

        return results

    async def fetch_situation_snapshot(self) -> str:
        """Raw GetSituation XML (used by coordinator)."""
        return await self._get_text(self._situation_url)
