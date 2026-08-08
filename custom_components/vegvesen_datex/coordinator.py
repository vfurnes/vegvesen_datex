
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
    CONF_RADIUS_ZONE,
    CONF_RADIUS_KM,
    TYPE_WEATHER,
    TYPE_SITUATION,
    TYPE_RADIUS,
    TYPE_TRAVEL_TIME,
)
from .datex_client import DatexClient

_LOGGER = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


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

        try:
            # WEATHER
            for seg in self.segments:
                if seg.get(CONF_ITEM_TYPE) != TYPE_WEATHER:
                    continue
                site_id = seg.get(CONF_SITE_ID)
                seg_id = seg.get(CONF_SEGMENT_ID)
                if not site_id or not seg_id:
                    continue
                values = await self.client.fetch_measured_weather_site(str(site_id))
                data["weather"][str(site_id)] = values

            # TRAVEL TIME: a single nationwide snapshot covering every predefined
            # location, so it's fetched once per cycle and parsed for all locations
            # at once rather than re-fetched per configured item (unlike weather
            # above, which only ever needs one site per call).
            if any(seg.get(CONF_ITEM_TYPE) == TYPE_TRAVEL_TIME for seg in self.segments):
                tt_xml = await self.client.fetch_travel_time_data()
                all_travel_times = self.client.parse_travel_time_data(tt_xml)
            else:
                all_travel_times = {}

            for seg in self.segments:
                if seg.get(CONF_ITEM_TYPE) != TYPE_TRAVEL_TIME:
                    continue
                site_id = seg.get(CONF_SITE_ID)
                if not site_id:
                    continue
                data["travel_time"][str(site_id)] = all_travel_times.get(str(site_id), {})

            # SITUATION (fetch once if needed)
            if any(seg.get(CONF_ITEM_TYPE) in (TYPE_SITUATION, TYPE_RADIUS) for seg in self.segments):
                xml = await self.client.fetch_situation()
                events = self.client.parse_situation_events(xml)
            else:
                events = []

            data["situation"]["_events"] = events

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
