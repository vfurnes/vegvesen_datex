from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import UnitOfSpeed, DEGREE

from .const import (
    DOMAIN,
    ATTR_MESSAGE,
    ATTR_MATCHED,
    ATTR_SOURCE,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_DIRECTION,
)
from .coordinator import DatexCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DatexCoordinator = entry_data["coordinator"]
    segments = entry_data["segments"]
    entities: list[SensorEntity] = []

    for segment in segments:
        segment_id = segment.get(CONF_SEGMENT_ID)
        segment_name = segment.get(CONF_SEGMENT_NAME) or segment.get(CONF_SEGMENT_QUERY) or "Veistykke"
        selected = set(segment.get(CONF_SEGMENT_ENTITIES) or [])

        if not segment_id:
            continue

        if ENTITY_STATUS in selected:
            entities.append(VegvesenDatexStatusSensor(coordinator, segment_id, segment_name))
        if ENTITY_MESSAGE in selected:
            entities.append(VegvesenDatexMessageSensor(coordinator, segment_id, segment_name))
        if ENTITY_WIND_SPEED in selected:
            entities.append(VegvesenDatexWindSpeedSensor(coordinator, segment_id, segment_name))
        if ENTITY_WIND_DIRECTION in selected:
            entities.append(VegvesenDatexWindDirectionSensor(coordinator, segment_id, segment_name))
    async_add_entities(entities, True)


class VegvesenDatexSegmentSensor(SensorEntity):
    def __init__(self, coordinator: DatexCoordinator, segment_id: str, segment_name: str) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self.segment_name = segment_name

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    def _segment_data(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.segment_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class VegvesenDatexStatusSensor(VegvesenDatexSegmentSensor):
    _attr_name = "Status"

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, segment_name: str) -> None:
        super().__init__(coordinator, segment_id, segment_name)
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_{segment_id}_status"
            if hasattr(coordinator, "config_entry_id")
            else None
        )
        self._attr_name = f"{segment_name} Status"

    @property
    def native_value(self) -> str:
        data = self._segment_data()
        if not data:
            return "ukjent"
        status = data.get("status")
        return status.status if status else "ukjent"

    @property
    def extra_state_attributes(self):
        data = self._segment_data()
        if not data:
            return {}
        status = data.get("status")
        return {
            ATTR_MESSAGE: status.message if status else None,
            ATTR_MATCHED: status.matched if status else None,
            ATTR_SOURCE: status.source if status else None,
        }


class VegvesenDatexMessageSensor(VegvesenDatexSegmentSensor):
    _attr_name = "Hendelse"

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, segment_name: str) -> None:
        super().__init__(coordinator, segment_id, segment_name)
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_{segment_id}_message"
            if hasattr(coordinator, "config_entry_id")
            else None
        )
        self._attr_name = f"{segment_name} Hendelse"

    @property
    def native_value(self) -> str | None:
        data = self._segment_data()
        if not data:
            return None
        status = data.get("status")
        return status.message if status else None


class VegvesenDatexWindSpeedSensor(VegvesenDatexSegmentSensor):
    _attr_name = "Vindstyrke"
    _attr_device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, segment_name: str) -> None:
        super().__init__(coordinator, segment_id, segment_name)
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_{segment_id}_wind_speed"
            if hasattr(coordinator, "config_entry_id")
            else None
        )
        self._attr_name = f"{segment_name} Vindstyrke"

    @property
    def native_value(self) -> float | None:
        data = self._segment_data()
        if not data:
            return None
        return data.get("wind_ms")


class VegvesenDatexWindDirectionSensor(VegvesenDatexSegmentSensor):
    _attr_name = "Vindretning"
    _attr_device_class = SensorDeviceClass.WIND_DIRECTION
    _attr_native_unit_of_measurement = DEGREE

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, segment_name: str) -> None:
        super().__init__(coordinator, segment_id, segment_name)
        self._attr_unique_id = (
            f"{coordinator.config_entry_id}_{segment_id}_wind_direction"
            if hasattr(coordinator, "config_entry_id")
            else None
        )
        self._attr_name = f"{segment_name} Vindretning"

    @property
    def native_value(self) -> float | None:
        data = self._segment_data()
        if not data:
            return None
        return data.get("wind_deg")
