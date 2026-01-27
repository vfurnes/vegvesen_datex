from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp
import async_timeout
import xml.etree.ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    MEASURED_WEATHER_URL_DEFAULT,
    SITUATION_URL_DEFAULT,
    WEATHER_SITE_TABLE_URL_DEFAULT,
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
        hass: HomeAssistant,
        username: str,
        password: str,
        measured_weather_url: str = MEASURED_WEATHER_URL_DEFAULT,
        situation_url: str = SITUATION_URL_DEFAULT,
        weather_site_table_url: str = WEATHER_SITE_TABLE_URL_DEFAULT,
        request_timeout: int = 30,
    ) -> None:
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)
        self._auth = aiohttp.BasicAuth(username, password)
        self._measured_weather_url = measured_weather_url
        self._situation_url = situation_url
        self._weather_site_table_url = weather_site_table_url
        self._timeout = request_timeout

    # -------------------------
    # Convenience methods used by config_flow
    # -------------------------

    async def list_sites(self, filter_text: str = "") -> list[tuple[str, str]]:
        """List measurement sites (id, name) from GetMeasurementWeatherSiteTable.

        Returns a list of tuples suitable for dropdowns.
        """
        xml_text = await self._get_text(self._weather_site_table_url)
        sites = self._parse_site_table(xml_text)

        ft = (filter_text or "").strip().lower()
        if ft:
            sites = [(sid, name) for sid, name in sites if ft in sid.lower() or ft in name.lower()]

        # stable ordering: name then id
        sites.sort(key=lambda x: (x[1].lower(), x[0]))
        return sites

    async def get_measurements_for_site(self, site_id: str) -> dict[str, float | int | None]:
        """Return the latest numeric values for a site (used by options flow previews)."""
        measured = await self.fetch_measured_weather_site(site_id)
        return {k: (v.value if v else None) for k, v in measured.items()}

    @dataclass
    class _Status:
        status: str
        is_closed: bool

    async def get_status_for_query(self, query: str) -> "DatexClient._Status":
        """Very lightweight status helper for situation options.

        We keep this deliberately simple to avoid failing the whole options flow
        if situation parsing changes upstream.
        """
        try:
            _ = await self.fetch_situation()
        except Exception:
            return self._Status(status="ukjent", is_closed=False)
        return self._Status(status="ok", is_closed=False)

    async def _get_text(self, url: str) -> str:
        async with async_timeout.timeout(self._timeout):
            async with self._session.get(url, auth=self._auth) as resp:
                resp.raise_for_status()
                return await resp.text()

    async def fetch_situation(self) -> str:
        """Fetch raw GetSituation XML (used for credential verification)."""
        return await self._get_text(self._situation_url)

    async def fetch_measured_weather_site(self, site_id: str) -> dict[str, MeasuredValue]:
        """Fetch and parse GetMeasuredWeatherData for one measurement site id."""
        xml_text = await self._get_text(self._measured_weather_url)
        return self._parse_measured_weather_site(xml_text, site_id)

    def _parse_measured_weather_site(self, xml_text: str, site_id: str) -> dict[str, MeasuredValue]:
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        def find_path(elem: ET.Element, path: str) -> ET.Element | None:
            parts = path.split("/")
            cur = elem
            for part in parts:
                found = None
                for ch in list(cur):
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

        default_time_el = find_path(site_measurements, "measurementTimeDefault/timeValue")
        default_time = default_time_el.text.strip() if default_time_el is not None and (default_time_el.text or "").strip() else None

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
                    results["humidity"] = MeasuredValue(float(perc.text.strip()), time_value=time_value)
                except ValueError:
                    pass
                continue

            # AIR TEMPERATURE
            temp = find_path(pq, "basicData/temperature/airTemperature/temperature")
            if temp is not None and (temp.text or "").strip():
                try:
                    results["temperature"] = MeasuredValue(float(temp.text.strip()), time_value=time_value)
                except ValueError:
                    pass
                continue

            # WIND DIRECTION
            dirb = find_path(pq, "basicData/wind/windDirectionBearing/directionBearing")
            if dirb is not None and (dirb.text or "").strip():
                try:
                    results["wind_direction"] = MeasuredValue(int(float(dirb.text.strip())), time_value=time_value)
                except ValueError:
                    pass
                continue

            # WIND GUST (maximumWindSpeed)
            gust = find_path(pq, "basicData/wind/maximumWindSpeed/windSpeed")
            if gust is not None and (gust.text or "").strip():
                try:
                    results["wind_gust"] = MeasuredValue(
                        float(gust.text.strip()),
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
                    results["wind_speed"] = MeasuredValue(float(ws.text.strip()), time_value=time_value)
                except ValueError:
                    pass
                continue

        return results

    # -------------------------
    # Parsers
    # -------------------------

    def _parse_site_table(self, xml_text: str) -> list[tuple[str, str]]:
        """Parse GetMeasurementWeatherSiteTable into (site_id, site_name)."""
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        sites: dict[str, str] = {}

        # We don't rely on exact namespace/prefixes; just walk and find records.
        for rec in root.iter():
            # Common element names in DATEX: measurementSiteRecord / measurementSiteTable
            if _local(rec.tag) not in ("measurementSiteRecord", "measurementSite"):  # be tolerant
                continue

            sid: str | None = None
            name: str | None = None

            # Find measurementSiteReference with id
            for ch in list(rec):
                if _local(ch.tag) == "measurementSiteReference":
                    sid = ch.attrib.get("id")
                    break

            if not sid:
                continue

            # Try a few known-ish paths for name
            # Some feeds use <measurementSiteName><values><value>..</value></values></measurementSiteName>
            # Others: <measurementSiteName>..</measurementSiteName>
            # Others: <name>..</name>
            def _find_text_under(node: ET.Element, wanted_local: str) -> str | None:
                for sub in node.iter():
                    if _local(sub.tag) == wanted_local and (sub.text or "").strip():
                        return sub.text.strip()
                return None

            # Search within this record for likely name tags
            for candidate in ("measurementSiteName", "name", "siteName"):
                n = _find_text_under(rec, candidate)
                if n:
                    name = n
                    break

            sites[sid] = name or sid

        return list(sites.items())
