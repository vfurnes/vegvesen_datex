from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN,
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    TYPE_RADIUS,
)
from .coordinator import DatexCoordinator


def group_events(events: list[Any]) -> list[dict[str, Any]]:
    """Merge situations that share a road and an exact position.

    DATEX regularly publishes several situation records for one physical piece
    of roadwork – "Vedlikeholdsarbeid" and "Vei-/feltregulering" at the same
    coordinate, for instance. Without merging they become markers stacked on
    top of each other, so they are collapsed into one entry whose `what_list`
    carries every description.

    The result is sorted with closures first, then by distance, so the caller
    can take the top N and get the entries that matter most.
    """
    grouped: dict[tuple, dict[str, Any]] = {}

    for ev in events:
        if not isinstance(ev, dict):
            continue

        lat = ev.get("lat")
        lon = ev.get("lon")
        road = ev.get("road") or ev.get("label") or "Hendelse"

        if lat is None or lon is None:
            continue

        key = (road, round(float(lat), 6), round(float(lon), 6))

        if key not in grouped:
            grouped[key] = {
                # A stable handle for this position, so a marker keeps its
                # identity across updates for as long as the incident lasts.
                "group_key": hashlib.md5(
                    f"{road}|{key[1]}|{key[2]}".encode()
                ).hexdigest()[:12],
                "id": ev.get("id"),
                "label": ev.get("label"),
                "road": ev.get("road"),
                "road_number": ev.get("road_number"),
                "road_name": ev.get("road_name"),
                "location_for_display": ev.get("location_for_display"),
                "lat": lat,
                "lon": lon,
                "distance_km": ev.get("distance_km"),
                "closed": bool(ev.get("closed")),
                "what_list": [],
                "event_ids": [],
                "events": [],
                "last_update": ev.get("last_update"),
                "start_time": ev.get("start_time"),
                "expected_end_time": ev.get("expected_end_time"),
            }

        g = grouped[key]
        what = ev.get("what")
        if what and what not in g["what_list"]:
            g["what_list"].append(what)

        if ev.get("id"):
            g["event_ids"].append(ev.get("id"))

        g["events"].append(ev)

        if ev.get("closed"):
            g["closed"] = True

    grouped_list = list(grouped.values())

    def sort_key(item: dict[str, Any]) -> tuple:
        dist = item.get("distance_km")
        return (
            0 if item.get("closed") else 1,
            float(dist) if dist is not None else 9999.0,
            str(item.get("road") or ""),
        )

    grouped_list.sort(key=sort_key)
    return grouped_list


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DatexCoordinator = entry_data["coordinator"]
    segments = entry.options.get(CONF_SEGMENTS, [])

    for seg in segments:
        if seg.get(CONF_ITEM_TYPE) != TYPE_RADIUS:
            continue
        seg_id = seg.get(CONF_SEGMENT_ID)
        if not seg_id:
            continue
        name = seg.get(CONF_SEGMENT_NAME) or "DATEX radius"
        manager = _RadiusMarkerManager(
            hass, coordinator, str(seg_id), name, async_add_entities
        )
        entry.async_on_unload(manager.async_start())


class _RadiusMarkerManager:
    """Create one marker per incident and drop it again when the incident ends.

    There is deliberately no fixed number of slots. An earlier design kept ten
    numbered markers whether or not there were ten incidents, which meant the
    eleventh was silently lost and the empty ones sat around as unavailable
    entities.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DatexCoordinator,
        segment_id: str,
        base_name: str,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.segment_id = segment_id
        self.base_name = base_name
        self._async_add_entities = async_add_entities
        self._markers: dict[str, _DatexEventMarker] = {}

    @callback
    def async_start(self):
        """Subscribe to the coordinator and seed the current incidents."""
        unsub = self.coordinator.async_add_listener(self._handle_update)
        self._handle_update()
        return unsub

    def _current_groups(self) -> dict[str, dict[str, Any]]:
        data = ((self.coordinator.data or {}).get("situation") or {}).get(
            self.segment_id
        ) or {}
        return {g["group_key"]: g for g in group_events(data.get("events") or [])}

    @callback
    def _handle_update(self) -> None:
        groups = self._current_groups()

        gone = set(self._markers) - set(groups)
        for key in gone:
            marker = self._markers.pop(key)
            self.hass.async_create_task(self._async_drop(marker))

        new: list[_DatexEventMarker] = []
        for key, group in groups.items():
            if marker := self._markers.get(key):
                marker.async_update_group(group)
            else:
                marker = _DatexEventMarker(
                    self.coordinator, self.segment_id, self.base_name, group
                )
                self._markers[key] = marker
                new.append(marker)

        if new:
            self._async_add_entities(new)

    async def _async_drop(self, marker: _DatexEventMarker) -> None:
        """Remove a marker and its registry entry.

        Removing the entity alone would leave the registry entry behind, and it
        would come back after a restart as an unavailable ghost – which is
        exactly how this integration accumulated two generations of orphaned
        trackers before.
        """
        entity_id = marker.entity_id
        await marker.async_remove(force_remove=True)
        registry = er.async_get(self.hass)
        if entity_id and registry.async_get(entity_id):
            registry.async_remove(entity_id)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class _DatexEventMarker(GeolocationEvent):
    """One incident on the map.

    `source`, `distance`, `latitude` and `longitude` are cached properties on
    GeolocationEvent, so they are fed through their `_attr_` fields rather than
    overridden – override them and the cache never sees a change. `state` and
    `state_attributes` are final in the base class: the distance becomes the
    state on its own, and everything else goes via extra_state_attributes.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_source = DOMAIN

    def __init__(
        self,
        coordinator: DatexCoordinator,
        segment_id: str,
        base_name: str,
        group: dict[str, Any],
    ) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self.base_name = base_name

        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_{segment_id}_marker_{group['group_key']}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"radius_{segment_id}")},
            name=base_name,
            manufacturer="Statens vegvesen",
            model="DATEX radius",
        )
        self._apply(group)

    @callback
    def async_update_group(self, group: dict[str, Any]) -> None:
        """Take fresh data for the same incident and refresh the state."""
        self._apply(group)
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def _apply(self, group: dict[str, Any]) -> None:
        self._group = group

        road = group.get("road") or group.get("label") or "Hendelse"
        what_list = group.get("what_list") or []
        parts = [str(road)]
        if what_list:
            parts.append("–")
            parts.append(", ".join(str(w) for w in what_list if w))
        self._attr_name = " ".join(parts)

        self._attr_icon = (
            "mdi:road-variant-off"
            if group.get("closed") is True
            else "mdi:map-marker-alert"
        )

        # Kilometres – the platform renders this as round(distance, 1)
        self._attr_distance = _as_float(group.get("distance_km"))
        self._attr_latitude = _as_float(group.get("lat"))
        self._attr_longitude = _as_float(group.get("lon"))

        attrs: dict[str, Any] = {
            k: group.get(k)
            for k in (
                "id",
                "label",
                "road",
                "road_number",
                "road_name",
                "closed",
                "last_update",
                "start_time",
                "expected_end_time",
                "distance_km",
                "location_for_display",
            )
            if group.get(k) is not None
        }
        if what_list:
            attrs["what_list"] = what_list
            attrs["what"] = ", ".join(str(w) for w in what_list if w)
        if group.get("event_ids"):
            attrs["event_ids"] = group["event_ids"]
        attrs["event_count"] = len(group.get("events") or [])

        # A ready-made display string, so a dashboard can list incidents
        # without reassembling road, descriptions and distance itself.
        text = str(road)
        if what_list:
            text += " | " + ", ".join(str(w) for w in what_list if w)
        distance_km = group.get("distance_km")
        if distance_km is not None:
            text += f" ({distance_km} km)"
        attrs["event_text"] = text

        self._attr_extra_state_attributes = attrs

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
