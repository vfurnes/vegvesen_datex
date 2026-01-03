from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import UnitOfSpeed, DEGREE, UnitOfTemperature, PERCENTAGE

from .const import (
    DOMAIN,
    ATTR_MESSAGE,
    ATTR_MATCHED,
    ATTR_SOURCE,
    CONF_ITEM_TYPE,
    TYPE_SITUATION,
    TYPE_WEATHER,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_GUST,
    ENTITY_WIND_DIRECTION,
    ENTITY_TEMPERATURE,
    ENTITY_HUMIDITY,
    ENTITY_PRESSURE,
    ENTITY_PRECIP_INTENSITY,
)
from .coordinator import DatexCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DatexCoordinator = entry_data["coordinator"]
    items = entry_data["segments"]

    entities: list[SensorEntity] = []

    for item in items:
        item_id = item.get(CONF_SEGMENT_ID)
        item_type = item.get(CONF_ITEM_TYPE) or TYPE_SITUATION
        name = item.get(CONF_SEGMENT_NAME) or item.get(CONF_SEGMENT_QUERY) or "DATEX"
        selected = set(item.get(CONF_SEGMENT_ENTITIES) or [])

        if not item_id:
            continue

        if item_type == TYPE_SITUATION:
            if ENTITY_STATUS in selected:
                entities.append(VegvesenDatexStatusSensor(coordinator, item_id, name))
            if ENTITY_MESSAGE in selected:
                entities.append(VegvesenDatexMessageSensor(coordinator, item_id, name))
            continue

        # TYPE_WEATHER
        if ENTITY_WIND_SPEED in selected:
            entities.append(VegvesenDatexWindSpeedSensor(coordinator, item_id, name))
        if ENTITY_WIND_DIRECTION in selected:
            entities.append(VegvesenDatexWindDirectionSensor(coordinator, item_id, name))
        if ENTITY_TEMPERATURE in selected:
            entities.append(VegvesenDatexTemperatureSensor(coordinator, item_id, name))
        if ENTITY_HUMIDITY in selected:
            entities.append(VegvesenDatexHumiditySensor(coordinator, item_id, name))
        if ENTITY_PRESSURE in selected:
            entities.append(VegvesenDatexPressureSensor(coordinator, item_id, name))
        if ENTITY_PRECIP_INTENSITY in selected:
            entities.append(VegvesenDatexPrecipIntensitySensor(coordinator, item_id, name))

    async_add_entities(entities, True)


class VegvesenDatexBaseSensor(SensorEntity):
    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        self.coordinator = coordinator
        self.item_id = item_id
        self.name = name

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    def _item_data(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.item_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


# -------------------------
# Situation sensors
# -------------------------
class VegvesenDatexStatusSensor(VegvesenDatexBaseSensor):
    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_status"
        self._attr_name = f"{name} Status"

    @property
    def native_value(self) -> str:
        data = self._item_data()
        if not data:
            return "ukjent"
        status = data.get("status")
        return status.status if status else "ukjent"

    @property
    def extra_state_attributes(self):
        data = self._item_data()
        if not data:
            return {}
        status = data.get("status")
        return {
            ATTR_MESSAGE: status.message if status else None,
            ATTR_MATCHED: status.matched if status else None,
            ATTR_SOURCE: status.source if status else None,
        }


class VegvesenDatexMessageSensor(VegvesenDatexBaseSensor):
    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_message"
        self._attr_name = f"{name} Hendelse"

    @property
    def native_value(self) -> str | None:
        data = self._item_data()
        if not data:
            return None
        status = data.get("status")
        return status.message if status else None


# -------------------------
# Weather sensors
# -------------------------
class VegvesenDatexWeatherBaseSensor(VegvesenDatexBaseSensor):
    def _weather(self) -> dict | None:
        data = self._item_data()
        if not data:
            return None
        return data.get("weather") or {}


class VegvesenDatexWindSpeedSensor(VegvesenDatexWeatherBaseSensor):
    _attr_device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND

    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_wind_speed"
        self._attr_name = f"{name} Vindstyrke"

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_WIND_SPEED)



class VegvesenDatexWindGustSensor(VegvesenDatexWeatherBaseSensor):
    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_wind_gust"
        self._attr_name = f"{name} Vindkast"
        self._attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND
        self._attr_device_class = SensorDeviceClass.WIND_SPEED

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_WIND_GUST)


class VegvesenDatexWindDirectionSensor(VegvesenDatexWeatherBaseSensor):
    _attr_device_class = SensorDeviceClass.WIND_DIRECTION
    _attr_native_unit_of_measurement = DEGREE

    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_wind_direction"
        self._attr_name = f"{name} Vindretning"

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_WIND_DIRECTION)


class VegvesenDatexTemperatureSensor(VegvesenDatexWeatherBaseSensor):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_temperature"
        self._attr_name = f"{name} Temperatur"

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_TEMPERATURE)


class VegvesenDatexHumiditySensor(VegvesenDatexWeatherBaseSensor):
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_humidity"
        self._attr_name = f"{name} Luftfuktighet"

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_HUMIDITY)


class VegvesenDatexPressureSensor(VegvesenDatexWeatherBaseSensor):
    _attr_device_class = SensorDeviceClass.ATMOSPHERIC_PRESSURE
    _attr_native_unit_of_measurement = "hPa"

    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_pressure"
        self._attr_name = f"{name} Lufttrykk"

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_PRESSURE)


class VegvesenDatexPrecipIntensitySensor(VegvesenDatexWeatherBaseSensor):
    def __init__(self, coordinator: DatexCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, item_id, name)
        self._attr_unique_id = f"{coordinator.config_entry_id}_{item_id}_precip_intensity"
        self._attr_name = f"{name} Nedbør-intensitet"

    @property
    def native_value(self) -> float | None:
        w = self._weather()
        return None if w is None else w.get(ENTITY_PRECIP_INTENSITY)
