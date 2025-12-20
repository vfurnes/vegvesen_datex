from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    ENTITY_CLOSED,
)
from .coordinator import DatexCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DatexCoordinator = entry_data["coordinator"]
    segments = entry_data["segments"]
    entities: list[BinarySensorEntity] = []
    for segment in segments:
        segment_id = segment.get(CONF_SEGMENT_ID)
        segment_name = segment.get(CONF_SEGMENT_NAME) or segment.get(CONF_SEGMENT_QUERY) or "Veistykke"
        selected = set(segment.get(CONF_SEGMENT_ENTITIES) or [])
        if not segment_id:
            continue
        if ENTITY_CLOSED in selected:
            entities.append(VegvesenDatexClosedBinarySensor(coordinator, segment_id, segment_name))
    async_add_entities(entities, True)


class VegvesenDatexClosedBinarySensor(BinarySensorEntity):
    _attr_name = "Stengt"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, segment_name: str) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_{segment_id}_closed"
            if hasattr(coordinator, "config_entry_id")
            else None
        )
        self._attr_name = f"{segment_name} Stengt"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        data = self.coordinator.data.get(self.segment_id)
        if not data:
            return False
        status = data.get("status")
        return bool(status and status.is_closed)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
