from __future__ import annotations

import logging
import re
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

    
    # -------------------------
    # Situation "learning" helpers
    # -------------------------

    def extract_situation_candidates(self, xml_text: str) -> list[dict[str, str]]:
        """Extract 'strekning/sted' candidates from a GetSituation snapshot.

        Returns list of dicts:
          - id: normalized key
          - label: human label
          - token1/token2: matching tokens (stored separately in storage layer)
        We stay conservative: if we can't find good location hints, we skip.
        """
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        def _clean(s: str) -> str:
            s = re.sub(r"\s+", " ", (s or "").strip())
            return s

        # Collect from each situationRecord
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        for rec in root.iter():
            if _local(rec.tag) != "situationRecord":
                continue

            # Try to find locationForDisplay (often contains road + place)
            loc_display = None
            for sub in rec.iter():
                if _local(sub.tag) == "locationForDisplay" and (sub.text or "").strip():
                    loc_display = _clean(sub.text)
                    break

            # Try road number/name if present
            road_number = None
            road_name = None
            for sub in rec.iter():
                if _local(sub.tag) == "roadNumber" and (sub.text or "").strip():
                    road_number = _clean(sub.text)
                    break
            for sub in rec.iter():
                if _local(sub.tag) == "roadName" and (sub.text or "").strip():
                    road_name = _clean(sub.text)
                    break

            # Build label preference: "road_number – loc_display" else loc_display else road_number+road_name
            label_parts = []
            if road_number:
                label_parts.append(road_number)
            if loc_display:
                # avoid duplicating road number if already inside loc_display
                label_parts.append(loc_display)
            elif road_name:
                label_parts.append(road_name)

            label = " – ".join([p for p in label_parts if p])
            label = _clean(label)

            if not label:
                continue

            # Tokenization for matching later
            tokens = []
            if road_number:
                tokens.append(road_number.lower())
            # use a simplified place token: strip road prefix from loc_display if possible
            if loc_display:
                simplified = loc_display
                if road_number and road_number.lower() in simplified.lower():
                    simplified = re.sub(re.escape(road_number), "", simplified, flags=re.I)
                simplified = _clean(simplified).lower()
                if simplified:
                    tokens.append(simplified)

            # Require at least one token
            if not tokens:
                continue

            key = "|".join(tokens[:2])  # stable enough
            key = re.sub(r"[^a-z0-9\|æøå_-]", "", key, flags=re.I)

            if key in seen:
                continue
            seen.add(key)

            out.append(
                {
                    "id": key,
                    "label": label,
                    "token1": tokens[0] if len(tokens) > 0 else "",
                    "token2": tokens[1] if len(tokens) > 1 else "",
                }
            )

        return out

    def parse_situation_events(self, xml_text: str) -> list[dict]:
        """Parse GetSituation snapshot into lightweight event dicts."""
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        def _clean(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip())

        events: list[dict] = []
        for rec in root.iter():
            if _local(rec.tag) != "situationRecord":
                continue

            ev_id = rec.attrib.get("id") or ""
            location_for_display = ""
            road_number = ""
            road_name = ""
            for sub in rec.iter():
                if _local(sub.tag) == "locationForDisplay" and (sub.text or "").strip():
                    location_for_display = _clean(sub.text)
                    break
            for sub in rec.iter():
                if _local(sub.tag) == "roadNumber" and (sub.text or "").strip():
                    road_number = _clean(sub.text)
                    break
            for sub in rec.iter():
                if _local(sub.tag) == "roadName" and (sub.text or "").strip():
                    road_name = _clean(sub.text)
                    break

            comments: list[str] = []
            for sub in rec.iter():
                if _local(sub.tag) in ("comment", "generalPublicComment", "description") and (sub.text or "").strip():
                    comments.append(_clean(sub.text))
                    if len(comments) >= 2:
                        break

            lat = lon = None
            lat_text = lon_text = None
            for sub in rec.iter():
                if _local(sub.tag) == "latitude" and (sub.text or "").strip():
                    lat_text = _clean(sub.text)
                    break
            for sub in rec.iter():
                if _local(sub.tag) == "longitude" and (sub.text or "").strip():
                    lon_text = _clean(sub.text)
                    break
            try:
                if lat_text is not None and lon_text is not None:
                    lat = float(lat_text)
                    lon = float(lon_text)
            except Exception:
                lat = lon = None

            label_parts = []
            if road_number:
                label_parts.append(road_number)
            if location_for_display:
                label_parts.append(location_for_display)
            elif road_name:
                label_parts.append(road_name)
            label = _clean(" – ".join(label_parts))
            text_combined = _clean(" | ".join([p for p in [label, *comments] if p]))

            events.append(
                {
                    "id": ev_id,
                    "label": label,
                    "text": text_combined,
                    "location_for_display": location_for_display,
                    "road_number": road_number,
                    "road_name": road_name,
                    "lat": lat,
                    "lon": lon,
                }
            )
        return events

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
        """Parse GetMeasurementWeatherSiteTable into (site_id, site_name).

        NPRA/Statens vegvesen feeds typically use:
          - <measurementSiteIdentification>3000064</measurementSiteIdentification>
          - <measurementSiteName><values><value lang="nob">Rv 15 Måløybrua</value></values></measurementSiteName>

        Some other DATEX feeds may use <measurementSiteReference id="...">.
        We therefore support both, and we don't depend on namespaces/prefixes.
        """
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        def _text(node: ET.Element | None) -> str | None:
            if node is None:
                return None
            t = (node.text or "").strip()
            return t or None

        sites: dict[str, str] = {}

        # In NPRA feed, each <measurementSite> is a station
        for site in root.iter():
            if _local(site.tag) not in ("measurementSite", "measurementSiteRecord"):
                continue

            sid: str | None = None
            name: str | None = None

            # 1) Try NPRA-style: <measurementSiteIdentification>
            for ch in list(site):
                if _local(ch.tag) == "measurementSiteIdentification":
                    sid = _text(ch)
                    break

            # 2) Fallback: <measurementSiteReference id="...">
            if not sid:
                for ch in site.iter():
                    if _local(ch.tag) == "measurementSiteReference":
                        sid = ch.attrib.get("id")
                        break

            if not sid:
                continue

            # Name: NPRA-style value under measurementSiteName/values/value
            for ch in list(site):
                if _local(ch.tag) == "measurementSiteName":
                    v = None
                    # prefer first <value> that has text
                    for sub in ch.iter():
                        if _local(sub.tag) == "value" and (sub.text or "").strip():
                            v = sub.text.strip()
                            break
                    name = v
                    break

            # Fallback name tags
            if not name:
                for sub in site.iter():
                    if _local(sub.tag) in ("name", "siteName") and (sub.text or "").strip():
                        name = sub.text.strip()
                        break

            sites[sid] = name or sid

        return list(sites.items())

