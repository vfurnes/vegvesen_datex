from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ATTR_MESSAGE, ATTR_MATCHED, ATTR_SOURCE
from .coordinator import DatexCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DatexCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VegvesenDatexStatusSensor(coordinator)], True)


class VegvesenDatexStatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(self, coordinator: DatexCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry_id}_status" if hasattr(coordinator, "config_entry_id") else None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        return self.coordinator.data.status if self.coordinator.data else "ukjent"

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        if not d:
            return {}
        return {
            ATTR_MESSAGE: d.message,
            ATTR_MATCHED: d.matched,
            ATTR_SOURCE: d.source,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
