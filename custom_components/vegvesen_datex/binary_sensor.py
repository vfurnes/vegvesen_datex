
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_ITEM_TYPE,
    TYPE_SITUATION,
    TYPE_RADIUS,
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
    items = entry_data["segments"]

    entities: list[BinarySensorEntity] = []

    for item in items:
        item_type = item.get(CONF_ITEM_TYPE) or TYPE_SITUATION
        if item_type not in (TYPE_SITUATION, TYPE_RADIUS):
            continue

        item_id = item.get(CONF_SEGMENT_ID)
        name = item.get(CONF_SEGMENT_NAME) or item.get(CONF_SEGMENT_QUERY) or "DATEX"
        selected = set(item.get(CONF_SEGMENT_ENTITIES) or [])

        if not item_id:
            continue

        if ENTITY_CLOSED in selected:
            entities.append(VegvesenDatexActiveBinarySensor(coordinator, str(item_id), name))

    async_add_entities(entities)


class VegvesenDatexActiveBinarySensor(BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    # The coordinator pushes updates through the listener registered in
    # async_added_to_hass, so polling would only wait on its debouncer.
    _attr_should_poll = False

    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        self.coordinator = coordinator
        self.item_id = item_id
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_active"
        self._attr_name = f"{name} Stengt"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        sit = (self.coordinator.data or {}).get("situation") or {}
        d = sit.get(self.item_id)
        return bool(d and d.get("active"))

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
