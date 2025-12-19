from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DatexCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DatexCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VegvesenDatexClosedBinarySensor(coordinator)], True)


class VegvesenDatexClosedBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Stengt"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: DatexCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_closed"
            if hasattr(coordinator, "config_entry_id")
            else None
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        status = self.coordinator.data.get("status")
        return bool(status and status.is_closed)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
