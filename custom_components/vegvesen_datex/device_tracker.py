from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN,
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    TYPE_RADIUS,
    DEFAULT_RADIUS_MARKERS,
)
from .coordinator import DatexCoordinator


@dataclass
class _Slot:
    index: int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DatexCoordinator = entry_data["coordinator"]
    segments = entry.options.get(CONF_SEGMENTS, [])

    entities: list[TrackerEntity] = []
    for seg in segments:
        if seg.get(CONF_ITEM_TYPE) != TYPE_RADIUS:
            continue
        seg_id = seg.get(CONF_SEGMENT_ID)
        if not seg_id:
            continue
        name = seg.get(CONF_SEGMENT_NAME) or "DATEX radius"
        for i in range(1, DEFAULT_RADIUS_MARKERS + 1):
            entities.append(_DatexRadiusEventTracker(coordinator, str(seg_id), name, _Slot(i)))

    async_add_entities(entities, True)


class _DatexRadiusEventTracker(TrackerEntity):
    _attr_has_entity_name = True
    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:map-marker-alert"
    _attr_location_accuracy = 100.0

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, base_name: str, slot: _Slot) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self.base_name = base_name
        self.slot = slot

        self._attr_unique_id = f"{coordinator.config_entry_id}_{segment_id}_event_{slot.index}"
        self._attr_name = f"{base_name} #{slot.index}"

    def _get_event(self) -> dict[str, Any] | None:
        d = ((self.coordinator.data or {}).get("situation") or {}).get(self.segment_id) or {}
        events = d.get("events") or []
        idx0 = self.slot.index - 1
        if idx0 < 0 or idx0 >= len(events):
            return None
        return events[idx0]

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._get_event() is not None

    @property
    def latitude(self) -> float | None:
        ev = self._get_event()
        if not ev:
            return None
        lat = ev.get("lat")
        return float(lat) if lat is not None else None

    @property
    def longitude(self) -> float | None:
        ev = self._get_event()
        if not ev:
            return None
        lon = ev.get("lon")
        return float(lon) if lon is not None else None

    @property
    def location_name(self) -> str | None:
        ev = self._get_event()
        if not ev:
            return None
        road = ev.get("road") or ev.get("label") or "Hendelse"
        what = ev.get("what") or ""
        dkm = ev.get("distance_km")
        parts = [f"{self.slot.index}.", str(road)]
        if what:
            parts.append(str(what))
        if dkm is not None:
            parts.append(f"({dkm} km)")
        return " ".join(parts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self._get_event() or {}
        keep = (
            "id",
            "label",
            "road",
            "what",
            "closed",
            "last_update",
            "start_time",
            "expected_end_time",
            "distance_km",
            "road_number",
            "road_name",
            "location_for_display",
        )
        return {k: ev.get(k) for k in keep if k in ev}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"radius_{self.segment_id}")},
            name=self.base_name,
            manufacturer="Statens vegvesen",
            model="DATEX radius",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()
