from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import UnitOfSpeed, DEGREE

from .const import DOMAIN, ATTR_MESSAGE, ATTR_MATCHED, ATTR_SOURCE
from .coordinator import DatexCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DatexCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        VegvesenDatexStatusSensor(coordinator),
        VegvesenDatexMessageSensor(coordinator),
    ]
    if coordinator.site_id:
        entities.extend(
            [
                VegvesenDatexWindSpeedSensor(coordinator),
                VegvesenDatexWindDirectionSensor(coordinator),
            ]
        )
    async_add_entities(entities, True)


class VegvesenDatexStatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(self, coordinator: DatexCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_status"
            if hasattr(coordinator, "config_entry_id")
            else None
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return "ukjent"
        status = self.coordinator.data.get("status")
        return status.status if status else "ukjent"

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        if not d:
            return {}
        status = d.get("status")
        return {
            ATTR_MESSAGE: status.message if status else None,
            ATTR_MATCHED: status.matched if status else None,
            ATTR_SOURCE: status.source if status else None,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class VegvesenDatexMessageSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Hendelse"

    def __init__(self, coordinator: DatexCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_message"
            if hasattr(coordinator, "config_entry_id")
            else None
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        status = self.coordinator.data.get("status")
        return status.message if status else None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class VegvesenDatexWindSpeedSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Vindstyrke"
    _attr_device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND

    def __init__(self, coordinator: DatexCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_wind_speed"
            if hasattr(coordinator, "config_entry_id")
            else None
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("wind_ms")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class VegvesenDatexWindDirectionSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Vindretning"
    _attr_device_class = SensorDeviceClass.WIND_DIRECTION
    _attr_native_unit_of_measurement = DEGREE

    def __init__(self, coordinator: DatexCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_wind_direction"
            if hasattr(coordinator, "config_entry_id")
            else None
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("wind_deg")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
