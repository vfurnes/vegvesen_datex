from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import aiohttp
import xml.etree.ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    MEASURED_WEATHER_URL_DEFAULT,
    SITUATION_URL_DEFAULT,
    WEATHER_SITE_TABLE_URL_DEFAULT,
    TRAVEL_TIME_DATA_URL_DEFAULT,
    TRAVEL_TIME_LOCATIONS_URL_DEFAULT,
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
        travel_time_locations_url: str = TRAVEL_TIME_LOCATIONS_URL_DEFAULT,
        travel_time_data_url: str = TRAVEL_TIME_DATA_URL_DEFAULT,
        request_timeout: int = 30,
    ) -> None:
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)
        self._auth = aiohttp.BasicAuth(username, password)
        self._measured_weather_url = measured_weather_url
        self._situation_url = situation_url
        self._weather_site_table_url = weather_site_table_url
        self._travel_time_locations_url = travel_time_locations_url
        self._travel_time_data_url = travel_time_data_url
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

        ft = str(filter_text or "").strip().lower()
        if ft:
            sites = [(sid, name) for sid, name in sites if ft in sid.lower() or ft in name.lower()]

        # stable ordering: name then id
        sites.sort(key=lambda x: (x[1].lower(), x[0]))
        return sites

    async def list_travel_time_locations(self, filter_text: str = "") -> list[tuple[str, str]]:
        """List predefined travel time locations (id, name) from GetPredefinedTravelTimeLocations.

        Returns a list of tuples suitable for dropdowns.
        """
        xml_text = await self._get_text(self._travel_time_locations_url)
        locations = self._parse_travel_time_locations(xml_text)

        ft = str(filter_text or "").strip().lower()
        if ft:
            locations = [(lid, name) for lid, name in locations if ft in lid.lower() or ft in name.lower()]

        # stable ordering: name then id
        locations.sort(key=lambda x: (x[1].lower(), x[0]))
        return locations

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
        async with asyncio.timeout(self._timeout):
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
        """Parse GetSituation snapshot into lightweight event dicts.

        Returns a list of events with fields suited for Home Assistant dashboards:
        - id, label, road, what, closed
        - last_update, start_time, expected_end_time
        - road_number, road_name, location_for_display
        - lat, lon
        - comments (list) and text (combined)
        """
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        def _clean(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip())

        def _find_text(elem: ET.Element, names: tuple[str, ...]) -> str:
            for sub in elem.iter():
                if _local(sub.tag) in names and (sub.text or "").strip():
                    return _clean(sub.text)
            return ""

        def _find_attr_xsi_type(elem: ET.Element) -> str:
            # xsi:type may be namespaced
            for k, v in elem.attrib.items():
                if k.endswith("}type") or k == "xsi:type":
                    return v or ""
            return ""

        def _find_time(elem: ET.Element, names: tuple[str, ...]) -> str:
            # DATEX times are usually ISO strings
            return _find_text(elem, names)

        def _what_from_xsi(xsi_type: str) -> str:
            # Map common DATEX record types to nicer labels
            t = (xsi_type or "").split(":")[-1]
            mapping = {
                "Accident": "Ulykke",
                "Roadworks": "Vegararbeid",
                "MaintenanceWorks": "Vedlikeholdsarbeid",
                "GeneralNetworkManagement": "Trafikkregulering",
                "PoorRoadConditions": "Dårlige kjøreforhold",
                "AbnormalTraffic": "Avvikende trafikk",
                "AnimalPresenceObstruction": "Dyr i vegbanen",
                "Obstruction": "Hinder i vegen",
                "RoadOrCarriagewayOrLaneManagement": "Vei-/feltregulering",
                "WeatherRelatedRoadConditions": "Værrelatert",
            }
            return mapping.get(t, t or "Hendelse")

        events: list[dict] = []
        for rec in root.iter():
            if _local(rec.tag) != "situationRecord":
                continue

            ev_id = rec.attrib.get("id") or ""
            xsi_type = _find_attr_xsi_type(rec)
            what = _what_from_xsi(xsi_type)

            location_for_display = _find_text(rec, ("locationForDisplay",))
            road_number = _find_text(rec, ("roadNumber",))
            road_name = _find_text(rec, ("roadName",))

            comments: list[str] = []
            for sub in rec.iter():
                if _local(sub.tag) in ("comment", "generalPublicComment", "description") and (sub.text or "").strip():
                    comments.append(_clean(sub.text))
                    if len(comments) >= 3:
                        break

            # Times (best effort)
            last_update = _find_time(rec, ("situationRecordVersionTime", "versionTime", "publicationTime"))
            start_time = _find_time(rec, ("overallStartTime", "startTime", "overallStart", "start"))
            expected_end_time = _find_time(rec, ("overallEndTime", "endTime", "overallEnd", "end"))

            # Location (best effort)
            lat = lon = None
            lat_text = _find_text(rec, ("latitude",))
            lon_text = _find_text(rec, ("longitude",))
            try:
                if lat_text and lon_text:
                    lat = float(lat_text)
                    lon = float(lon_text)
            except Exception:
                lat = lon = None

            # Closed heuristic (best effort)
            closed = False
            # Look for typical DATEX terms indicating closure
            for sub in rec.iter():
                if (sub.text or "").strip():
                    txt = (sub.text or "").lower()
                    if "closed" in txt or "stengt" in txt or "blocked" in txt:
                        closed = True
                        break

            # Build label / road
            label_parts = []
            if road_number:
                label_parts.append(road_number)
            if location_for_display:
                label_parts.append(location_for_display)
            elif road_name:
                label_parts.append(road_name)

            label = _clean(" – ".join([p for p in label_parts if p]))
            road = label  # road = same as label for now (but kept as separate field)

            text_combined = _clean(" | ".join([p for p in [label, what, *comments] if p]))

            events.append(
                {
                    "id": ev_id,
                    "label": label or "Hendelse",
                    "road": road or "",
                    "what": what,
                    "closed": closed,
                    "text": text_combined,
                    "comments": comments,
                    "last_update": last_update,
                    "start_time": start_time,
                    "expected_end_time": expected_end_time,
                    "location_for_display": location_for_display,
                    "road_number": road_number,
                    "road_name": road_name,
                    "xsi_type": xsi_type,
                    "lat": lat,
                    "lon": lon,
                }
            )

        return events

    async def fetch_situation(self) -> str:
        """Fetch raw GetSituation XML (used for credential verification)."""
        return await self._get_text(self._situation_url)

    async def fetch_travel_time_data(self) -> str:
        """Fetch raw GetTravelTimeData XML.

        This is a single nationwide snapshot covering every predefined location, not
        just the ones configured in Home Assistant, so it is fetched once per poll
        and parsed for all locations at once (see parse_travel_time_data) rather than
        re-fetched per configured item.
        """
        return await self._get_text(self._travel_time_data_url)

    def parse_travel_time_data(self, xml_text: str) -> dict[str, dict[str, MeasuredValue]]:
        """Parse GetTravelTimeData into a dict of location id -> measurement dict.

        Each predefinedLocationReference id can carry up to two physicalQuantity
        records: one with basicData xsi:type="TravelTimeData" (duration, free-flow
        duration/speed, trend, type) and one with xsi:type="TrafficStatus" (a text
        status enum). Both are merged into the same per-location dict.
        """
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

        def _find_attr_xsi_type(elem: ET.Element) -> str:
            for k, v in elem.attrib.items():
                if k.endswith("}type") or k == "xsi:type":
                    return v or ""
            return ""

        def _txt(node: ET.Element | None) -> str | None:
            if node is None:
                return None
            t = (node.text or "").strip()
            return t or None

        def _float(node: ET.Element | None) -> float | None:
            t = _txt(node)
            if t is None:
                return None
            try:
                return float(t)
            except ValueError:
                return None

        results: dict[str, dict[str, MeasuredValue]] = {}

        for pq in root.iter():
            if _local(pq.tag) != "physicalQuantity":
                continue

            pertinent = find_path(pq, "pertinentLocation")
            loc_ref = find_path(pertinent, "predefinedLocationReference") if pertinent is not None else None
            location_id = (loc_ref.attrib.get("id") or "").strip() if loc_ref is not None else ""
            if not location_id:
                continue

            basic = find_path(pq, "basicData")
            if basic is None:
                continue

            kind = _find_attr_xsi_type(basic).split(":")[-1]
            bucket = results.setdefault(location_id, {})

            if kind == "TravelTimeData":
                period_start = _txt(find_path(basic, "measurementOrCalculationTime/period/startOfPeriod"))
                period_end = _txt(find_path(basic, "measurementOrCalculationTime/period/endOfPeriod"))
                time_value = period_end or period_start

                duration = _float(find_path(basic, "travelTime/duration"))
                if duration is not None:
                    bucket["travel_time"] = MeasuredValue(
                        duration, time_value=time_value,
                        period_start=period_start, period_end=period_end,
                    )

                free_flow_duration = _float(find_path(basic, "freeFlowTravelTime/duration"))
                if free_flow_duration is not None:
                    bucket["free_flow_travel_time"] = MeasuredValue(free_flow_duration, time_value=time_value)

                free_flow_speed = _float(find_path(basic, "freeFlowSpeed/speed"))
                if free_flow_speed is not None:
                    bucket["free_flow_speed"] = MeasuredValue(free_flow_speed, time_value=time_value)

                trend = _txt(find_path(basic, "travelTimeTrendType"))
                if trend is not None:
                    bucket["travel_time_trend"] = MeasuredValue(trend, time_value=time_value)

                tt_type = _txt(find_path(basic, "travelTimeType"))
                if tt_type is not None:
                    bucket["travel_time_type"] = MeasuredValue(tt_type, time_value=time_value)

            elif kind == "TrafficStatus":
                status = _txt(find_path(basic, "trafficStatus/trafficStatusValue"))
                if status is not None:
                    bucket["traffic_status"] = MeasuredValue(status)

        return results

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
        #
        # NOTE: In DATEX feeds, measurementSiteReference may appear as:
        #   <measurementSiteReference id="3000064" />
        # or with text content:
        #   <measurementSiteReference>3000064</measurementSiteReference>
        # or as an xlink href:
        #   <measurementSiteReference xlink:href="#3000064" />
        # We therefore match on id-attribute, text, or href (suffix/fragment).
        site_measurements = None
        wanted = str(site_id)

        for sm in root.iter():
            if _local(sm.tag) != "siteMeasurements":
                continue

            ref = find_path(sm, "measurementSiteReference")
            if ref is None:
                continue

            ref_id = (ref.attrib.get("id") or "").strip()
            if not ref_id and (ref.text or "").strip():
                ref_id = ref.text.strip()

            href = (
                ref.attrib.get("{http://www.w3.org/1999/xlink}href")
                or ref.attrib.get("href")
                or ""
            ).strip()

            # Normalize href fragments like "#3000064"
            href_norm = href.lstrip("#")
            if href_norm:
                # Some feeds use full URIs ending with the id
                if href_norm == wanted or href_norm.endswith(wanted):
                    site_measurements = sm
                    break

            if ref_id == wanted:
                site_measurements = sm
                break

        if site_measurements is None:
            _LOGGER.debug("No siteMeasurements found for site_id=%s", site_id)
            return {}

        default_time_el = find_path(site_measurements, "measurementTimeDefault/timeValue")
        default_time = default_time_el.text.strip() if default_time_el is not None and (default_time_el.text or "").strip() else None

        results: dict[str, MeasuredValue] = {}

        def _txt(node: ET.Element | None) -> str | None:
            if node is None:
                return None
            t = (node.text or "").strip()
            return t or None

        def _float(node: ET.Element | None) -> float | None:
            t = _txt(node)
            if t is None:
                return None
            try:
                return float(t)
            except ValueError:
                return None

        # Iterate physicalQuantity blocks
        for pq_outer in list(site_measurements):
            if _local(pq_outer.tag) != "physicalQuantity":
                continue

            # DATEX wraps each measurement in an outer <physicalQuantity index="N">
            # containing an inner <physicalQuantity type="..."> that holds <basicData>.
            # find_path must reach basicData through the inner wrapper.
            pq = find_path(pq_outer, "physicalQuantity") or pq_outer

            # Prefer measurementOrCalculationTime/timeValue if present, else fallback to measurementTimeDefault
            moc = find_path(pq, "basicData/measurementOrCalculationTime/timeValue")
            time_value = _txt(moc) or default_time

            # Period (only when present – used for wind gust)
            period_start = _txt(find_path(pq, "basicData/measurementOrCalculationTime/period/startOfPeriod"))
            period_end   = _txt(find_path(pq, "basicData/measurementOrCalculationTime/period/endOfPeriod"))

            # ── HUMIDITY ────────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/humidity/relativeHumidity/percentage"))
            if v is not None:
                results["humidity"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── AIR TEMPERATURE ─────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/temperature/airTemperature/temperature"))
            if v is not None:
                results["temperature"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── DEW POINT ───────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/temperature/dewPointTemperature/temperature"))
            if v is not None:
                results["dew_point_temperature"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── WIND DIRECTION ──────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/wind/windDirectionBearing/directionBearing"))
            if v is not None:
                results["wind_direction"] = MeasuredValue(int(v), time_value=time_value)
                continue

            # ── WIND GUST (maximumWindSpeed) ─────────────────────────────────────
            # A station sends this twice: once carrying a 10-minute period, which
            # is the maximum within that window and the figure vegvesen.no shows,
            # and once with no time element at all, which is the current reading.
            # Verified against every one of the 243 stations that send both.
            # They used to overwrite each other, and whichever came last won.
            v = _float(find_path(pq, "basicData/wind/maximumWindSpeed/windSpeed"))
            if v is not None:
                key = "wind_gust" if period_start else "wind_gust_current"
                results[key] = MeasuredValue(
                    v, time_value=time_value,
                    period_start=period_start, period_end=period_end,
                )
                continue

            # ── WIND SPEED ───────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/wind/windSpeed/windSpeed"))
            if v is not None:
                results["wind_speed"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── PRECIPITATION INTENSITY ──────────────────────────────────────────
            # index 2501 / 1401 / 1301 – pick first non-None, prefer 2501 (instant)
            # We only store one value; if already stored we keep the first.
            v = _float(find_path(pq, "basicData/precipitationDetail/precipitationIntensity/millimetresPerHourIntensity"))
            if v is not None and "precipitation_intensity" not in results:
                results["precipitation_intensity"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── ROAD SURFACE CONDITION (text enum) ──────────────────────────────
            cond_node = find_path(pq, "basicData/weatherRelatedRoadConditionType")
            if cond_node is not None and _txt(cond_node) is not None:
                if "road_surface_condition" not in results:
                    results["road_surface_condition"] = MeasuredValue(
                        _txt(cond_node), time_value=time_value
                    )
                continue

            # ── ROAD SURFACE TEMPERATURE ─────────────────────────────────────────
            v = _float(find_path(pq, "basicData/roadSurfaceConditionMeasurements/roadSurfaceTemperature/temperature"))
            if v is not None and "road_surface_temperature" not in results:
                results["road_surface_temperature"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── FRICTION ─────────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/roadSurfaceConditionMeasurements/friction/friction"))
            if v is not None and "road_surface_friction" not in results:
                results["road_surface_friction"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── WATER FILM ───────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/roadSurfaceConditionMeasurements/waterFilmThickness/distance"))
            if v is not None and "road_surface_water_film" not in results:
                results["road_surface_water_film"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── ICE LAYER ────────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/roadSurfaceConditionMeasurements/iceLayerThickness/distance"))
            if v is not None and "road_surface_ice_layer" not in results:
                results["road_surface_ice_layer"] = MeasuredValue(v, time_value=time_value)
                continue

            # ── SNOW DEPTH ───────────────────────────────────────────────────────
            v = _float(find_path(pq, "basicData/roadSurfaceConditionMeasurements/depthOfSnow/distance"))
            if v is not None and "road_surface_snow_depth" not in results:
                results["road_surface_snow_depth"] = MeasuredValue(v, time_value=time_value)
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

    def _parse_travel_time_locations(self, xml_text: str) -> list[tuple[str, str]]:
        """Parse GetPredefinedTravelTimeLocations into (location_id, location_name).

        Each <predefinedLocationReference id="..."> that carries a
        predefinedLocationName is a usable travel-time location. The same element
        name is used in GetTravelTimeData as a bare reference pointer (no name) -
        those are skipped here since this parser only ever sees the locations feed.
        """
        root = ET.fromstring(xml_text)

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        locations: dict[str, str] = {}

        for ref in root.iter():
            if _local(ref.tag) != "predefinedLocationReference":
                continue

            lid = (ref.attrib.get("id") or "").strip()
            if not lid:
                continue

            name: str | None = None
            for ch in list(ref):
                if _local(ch.tag) != "predefinedLocationName":
                    continue
                for sub in ch.iter():
                    if _local(sub.tag) == "value" and (sub.text or "").strip():
                        name = sub.text.strip()
                        break
                break

            if not name:
                continue

            locations[lid] = name

        return list(locations.items())

