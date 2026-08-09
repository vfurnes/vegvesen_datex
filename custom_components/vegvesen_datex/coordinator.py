
from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_ITEM_TYPE,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_QUERY,
    CONF_SITE_ID,
    CONF_SITE_IDS,
    CONF_RADIUS_ZONE,
    CONF_RADIUS_KM,
    TYPE_WEATHER,
    TYPE_SITUATION,
    TYPE_RADIUS,
    TYPE_TRAVEL_TIME,
    ENTITY_TRAVEL_TIME,
    ENTITY_FREE_FLOW_TRAVEL_TIME,
    ENTITY_FREE_FLOW_SPEED,
    ENTITY_TRAFFIC_STATUS,
    ENTITY_TRAVEL_TIME_TREND,
    ENTITY_TRAVEL_TIME_TYPE,
)
from .datex_client import DatexClient, MeasuredValue

_LOGGER = logging.getLogger(__name__)

# Worst-to-best severity for "respect outliers" aggregation, taken from the real
# DATEX II enums (DATEXII_3_RoadTrafficData.xsd: TrafficStatusEnum /
# TravelTimeTrendTypeEnum) rather than invented - the aggregate should reflect the
# single worst stretch, not a majority vote or the first value seen.
_TRAFFIC_STATUS_SEVERITY = [
    "stationary", "queuing", "heavy", "slow", "unspecifiedAbnormal", "other", "freeFlow", "unknown",
]
_TREND_SEVERITY = ["increasing", "decreasing", "stable"]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def resolve_travel_time_site_ids(seg: dict[str, Any]) -> list[str]:
    """Location ids for a travel_time segment.

    CONF_SITE_IDS (list) is the current shape, written whenever an item is
    saved through the options flow. CONF_SITE_ID (single) is what the
    single-stretch-only version of this feature wrote, kept here as a fallback
    for anything saved before accumulation existed.
    """
    ids = seg.get(CONF_SITE_IDS)
    if ids:
        return [str(i) for i in ids]
    single = seg.get(CONF_SITE_ID)
    return [str(single)] if single else []


def travel_time_bucket_key(seg: dict[str, Any]) -> str | None:
    """The key data["travel_time"] (and the entities' device) is stored under.

    A single stretch keeps using its own DATEX location id, so existing
    single-stretch items keep their current entity/device identifiers exactly
    as before this feature existed. Several stretches combined have no one
    canonical id to key off, so they use the segment's own id instead.
    """
    site_ids = resolve_travel_time_site_ids(seg)
    if not site_ids:
        return None
    if len(site_ids) == 1:
        return site_ids[0]
    return str(seg.get(CONF_SEGMENT_ID) or site_ids[0])


def _worst(values: list[str], severity: list[str]) -> str | None:
    present = [v for v in values if v]
    if not present:
        return None
    return min(present, key=lambda v: severity.index(v) if v in severity else len(severity))


def _aggregate_travel_time(buckets: list[dict[str, MeasuredValue]]) -> dict[str, MeasuredValue]:
    """Combine one or more stretches' travel-time data into a single bucket.

    Duration fields (travel time, free-flow travel time) add up, since
    consecutive stretches make one longer journey. Free-flow speed is
    averaged. Traffic status and trend pick the single worst value present
    (see the severity lists above) rather than a majority vote, so one bad
    stretch out of several isn't smoothed away. Fed a single bucket, this
    reproduces it unchanged - aggregation is a strict generalization of the
    single-stretch case, not a special case of it.
    """

    def _sum(key: str) -> float | None:
        vals = [b[key].value for b in buckets if b.get(key) is not None and b[key].value is not None]
        return sum(vals) if vals else None

    def _avg(key: str) -> float | None:
        vals = [b[key].value for b in buckets if b.get(key) is not None and b[key].value is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    times = [b[ENTITY_TRAVEL_TIME].time_value for b in buckets if b.get(ENTITY_TRAVEL_TIME) and b[ENTITY_TRAVEL_TIME].time_value]
    time_value = max(times) if times else None
    starts = [b[ENTITY_TRAVEL_TIME].period_start for b in buckets if b.get(ENTITY_TRAVEL_TIME) and b[ENTITY_TRAVEL_TIME].period_start]
    ends = [b[ENTITY_TRAVEL_TIME].period_end for b in buckets if b.get(ENTITY_TRAVEL_TIME) and b[ENTITY_TRAVEL_TIME].period_end]
    period_start = min(starts) if starts else None
    period_end = max(ends) if ends else None

    out: dict[str, MeasuredValue] = {}

    travel_time = _sum(ENTITY_TRAVEL_TIME)
    if travel_time is not None:
        out[ENTITY_TRAVEL_TIME] = MeasuredValue(
            travel_time, time_value=time_value, period_start=period_start, period_end=period_end
        )

    free_flow_travel_time = _sum(ENTITY_FREE_FLOW_TRAVEL_TIME)
    if free_flow_travel_time is not None:
        out[ENTITY_FREE_FLOW_TRAVEL_TIME] = MeasuredValue(free_flow_travel_time, time_value=time_value)

    free_flow_speed = _avg(ENTITY_FREE_FLOW_SPEED)
    if free_flow_speed is not None:
        out[ENTITY_FREE_FLOW_SPEED] = MeasuredValue(free_flow_speed, time_value=time_value)

    status = _worst(
        [b[ENTITY_TRAFFIC_STATUS].value for b in buckets if b.get(ENTITY_TRAFFIC_STATUS)], _TRAFFIC_STATUS_SEVERITY
    )
    if status is not None:
        out[ENTITY_TRAFFIC_STATUS] = MeasuredValue(status, time_value=time_value)

    trend = _worst(
        [b[ENTITY_TRAVEL_TIME_TREND].value for b in buckets if b.get(ENTITY_TRAVEL_TIME_TREND)], _TREND_SEVERITY
    )
    if trend is not None:
        out[ENTITY_TRAVEL_TIME_TREND] = MeasuredValue(trend, time_value=time_value)

    # A calculation-method tag, not a value that can be summed/averaged/
    # outlier-picked - it doesn't mean anything once stretches are combined, so
    # it's only carried through for a genuinely single stretch.
    if len(buckets) == 1 and buckets[0].get(ENTITY_TRAVEL_TIME_TYPE) is not None:
        out[ENTITY_TRAVEL_TIME_TYPE] = buckets[0][ENTITY_TRAVEL_TIME_TYPE]

    return out


class DatexCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass,
        client: DatexClient,
        segments: list[dict[str, Any]],
        scan_interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.client = client
        self.segments = segments
        self.config_entry_id: str | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"weather": {}, "situation": {}, "travel_time": {}}

        # Each data source below is fetched independently and failures are caught
        # locally: one bad fetch (e.g. the travel-time feed timing out) must not
        # mark the whole update as failed, or every entity - weather, situations,
        # radius incidents included - would go unavailable together even though
        # their own data sources fetched fine. The whole update only fails if
        # every source that was actually needed this cycle failed.
        attempted = 0
        succeeded = 0

        # WEATHER
        for seg in self.segments:
            if seg.get(CONF_ITEM_TYPE) != TYPE_WEATHER:
                continue
            site_id = seg.get(CONF_SITE_ID)
            seg_id = seg.get(CONF_SEGMENT_ID)
            if not site_id or not seg_id:
                continue
            attempted += 1
            try:
                data["weather"][str(site_id)] = await self.client.fetch_measured_weather_site(str(site_id))
                succeeded += 1
            except Exception as err:
                _LOGGER.warning("vegvesen_datex: weather fetch failed for site %s: %s", site_id, err)

        # TRAVEL TIME: a single nationwide snapshot covering every predefined
        # location, so it's fetched once per cycle and parsed for all locations
        # at once rather than re-fetched per configured item (unlike weather
        # above, which only ever needs one site per call).
        all_travel_times: dict[str, Any] = {}
        if any(seg.get(CONF_ITEM_TYPE) == TYPE_TRAVEL_TIME for seg in self.segments):
            attempted += 1
            try:
                tt_xml = await self.client.fetch_travel_time_data()
                all_travel_times = self.client.parse_travel_time_data(tt_xml)
                succeeded += 1
            except Exception as err:
                _LOGGER.warning("vegvesen_datex: travel time fetch failed: %s", err)

        for seg in self.segments:
            if seg.get(CONF_ITEM_TYPE) != TYPE_TRAVEL_TIME:
                continue
            key = travel_time_bucket_key(seg)
            if not key:
                continue
            site_ids = resolve_travel_time_site_ids(seg)
            buckets = [all_travel_times.get(sid, {}) for sid in site_ids]
            data["travel_time"][key] = _aggregate_travel_time(buckets)

        # SITUATION (fetch once if needed)
        events: list[dict] = []
        if any(seg.get(CONF_ITEM_TYPE) in (TYPE_SITUATION, TYPE_RADIUS) for seg in self.segments):
            attempted += 1
            try:
                xml = await self.client.fetch_situation()
                events = self.client.parse_situation_events(xml)
                succeeded += 1
            except Exception as err:
                _LOGGER.warning("vegvesen_datex: situation fetch failed: %s", err)

        if attempted and not succeeded:
            raise UpdateFailed("All DATEX data sources failed this update - see warnings above")

        data["situation"]["_events"] = events

        try:
            for seg in self.segments:
                seg_id = seg.get(CONF_SEGMENT_ID)
                if not seg_id:
                    continue

                item_type = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION

                if item_type == TYPE_SITUATION:
                    query = (seg.get(CONF_SEGMENT_QUERY) or "").strip().lower()
                    matches: list[dict] = []
                    if query:
                        for ev in events:
                            hay = " ".join([
                                str(ev.get("text") or ""),
                                str(ev.get("label") or ""),
                                str(ev.get("road") or ""),
                                str(ev.get("what") or ""),
                            ]).lower()
                            if query in hay:
                                matches.append(ev)
                    data["situation"][str(seg_id)] = {
                        "type": TYPE_SITUATION,
                        "query": seg.get(CONF_SEGMENT_QUERY) or "",
                        "count": len(matches),
                        "active": len(matches) > 0,
                        "first": matches[0] if matches else None,
                        "events": matches[:25],
                    }

                elif item_type == TYPE_RADIUS:
                    zone_entity = (seg.get(CONF_RADIUS_ZONE) or "zone.home").strip()
                    radius_km = float(seg.get(CONF_RADIUS_KM) or 0)
                    st = self.hass.states.get(zone_entity)
                    lat0 = lon0 = None
                    if st:
                        lat0 = st.attributes.get("latitude")
                        lon0 = st.attributes.get("longitude")
                    nearby: list[dict] = []
                    if lat0 is not None and lon0 is not None and radius_km > 0:
                        for ev in events:
                            lat = ev.get("lat")
                            lon = ev.get("lon")
                            if lat is None or lon is None:
                                continue
                            dkm = _haversine_km(float(lat0), float(lon0), float(lat), float(lon))
                            if dkm <= radius_km:
                                nearby.append({**ev, "distance_km": round(dkm, 2)})
                        nearby.sort(key=lambda e: e.get("distance_km", 9e9))
                    data["situation"][str(seg_id)] = {
                        "type": TYPE_RADIUS,
                        "zone": zone_entity,
                        "radius_km": radius_km,
                        "center": {"lat": lat0, "lon": lon0},
                        "count": len(nearby),
                        "active": len(nearby) > 0,
                        "first": nearby[0] if nearby else None,
                        "events": nearby[:25],
                    }

        except Exception as err:
            raise UpdateFailed(str(err)) from err

        return data
