
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import UnitOfSpeed, DEGREE, UnitOfTemperature, PERCENTAGE

from .const import (
    DOMAIN,
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    TYPE_WEATHER,
    TYPE_SITUATION,
    TYPE_RADIUS,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_TEMPERATURE,
    ENTITY_HUMIDITY,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_GUST,
    ENTITY_WIND_DIRECTION,
    ATTR_MESSAGE,
    ATTR_MATCHED,
    ATTR_SOURCE,
    ATTR_LAST_MEASURED,
    ATTR_PERIOD_START,
    ATTR_PERIOD_END,
)
from .coordinator import DatexCoordinator
from .datex_client import MeasuredValue


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DatexCoordinator = entry_data["coordinator"]
    segments = entry.options.get(CONF_SEGMENTS, [])
    entities: list[SensorEntity] = []

    for seg in segments:
        item_type = seg.get(CONF_ITEM_TYPE)
        seg_id = seg.get(CONF_SEGMENT_ID)
        seg_name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SEGMENT_QUERY) or "DATEX"
        selected = set(seg.get(CONF_SEGMENT_ENTITIES, []))

        if not seg_id:
            continue

        if item_type == TYPE_WEATHER:
            if ENTITY_HUMIDITY in selected:
                entities.append(_WeatherValueSensor(coordinator, str(seg_id), seg_name, "humidity", "Luftfuktighet", PERCENTAGE, SensorDeviceClass.HUMIDITY))
            if ENTITY_TEMPERATURE in selected:
                entities.append(_WeatherValueSensor(coordinator, str(seg_id), seg_name, "temperature", "Temperatur", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE))
            if ENTITY_WIND_DIRECTION in selected:
                entities.append(_WeatherValueSensor(coordinator, str(seg_id), seg_name, "wind_direction", "Vindretning", DEGREE, None))
            if ENTITY_WIND_SPEED in selected:
                entities.append(_WeatherValueSensor(coordinator, str(seg_id), seg_name, "wind_speed", "Vindstyrke", UnitOfSpeed.METERS_PER_SECOND, None))
            if ENTITY_WIND_GUST in selected:
                entities.append(_WeatherValueSensor(coordinator, str(seg_id), seg_name, "wind_gust", "Vindkast", UnitOfSpeed.METERS_PER_SECOND, None, include_period=True))

        elif item_type in (TYPE_SITUATION, TYPE_RADIUS):
            if ENTITY_STATUS in selected:
                entities.append(_SituationStatusSensor(coordinator, str(seg_id), seg_name))
            if ENTITY_MESSAGE in selected:
                entities.append(_SituationMessageSensor(coordinator, str(seg_id), seg_name))

    async_add_entities(entities, True)


@dataclass(frozen=True)
class _KeySpec:
    key: str
    include_period: bool = False


class _WeatherValueSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DatexCoordinator,
        segment_id: str,
        segment_name: str,
        key: str,
        name_suffix: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        include_period: bool = False,
    ) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self._spec = _KeySpec(key=key, include_period=include_period)

        self._attr_name = f"{segment_name} {name_suffix}"
        self._attr_unique_id = f"{coordinator.config_entry_id}_{segment_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    def _get_measured(self) -> MeasuredValue | None:
        weather = (self.coordinator.data or {}).get("weather", {})
        seg = weather.get(self.segment_id)
        if not seg:
            return None
        return seg.get(self._spec.key)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> Any:
        mv = self._get_measured()
        return None if mv is None else mv.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mv = self._get_measured()
        if mv is None:
            return {}
        attrs: dict[str, Any] = {}
        if mv.time_value:
            attrs[ATTR_LAST_MEASURED] = mv.time_value
        if self._spec.include_period:
            if mv.period_start:
                attrs[ATTR_PERIOD_START] = mv.period_start
            if mv.period_end:
                attrs[ATTR_PERIOD_END] = mv.period_end
        return attrs

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()


class _SituationBaseSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, name: str) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self._base_name = name

    def _get(self) -> dict | None:
        return ((self.coordinator.data or {}).get("situation") or {}).get(self.segment_id)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()


class _SituationStatusSensor(_SituationBaseSensor):
    def __init__(self, coordinator: DatexCoordinator, segment_id: str, base_name: str) -> None:
        super().__init__(coordinator, segment_id, base_name)
        self._attr_name = f"{base_name} Status"
        self._attr_unique_id = f"{coordinator.config_entry_id}_{segment_id}_status"

    @property
    def native_value(self) -> Any:
        d = self._get()
        if not d:
            return "Ukjent"
        if d.get("type") == "radius":
            return int(d.get("count") or 0)
        return "Hendelse" if d.get("active") else "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._get() or {}
        attrs: dict[str, Any] = {ATTR_MATCHED: int(d.get("count") or 0)}
        if d.get("type") == "radius":
            attrs["radius_km"] = d.get("radius_km")
            attrs["zone"] = d.get("zone")
            attrs["center"] = d.get("center")
        return attrs


class _SituationMessageSensor(_SituationBaseSensor):
    def __init__(self, coordinator: DatexCoordinator, segment_id: str, base_name: str) -> None:
        super().__init__(coordinator, segment_id, base_name)
        self._attr_name = f"{base_name} Hendelse"
        self._attr_unique_id = f"{coordinator.config_entry_id}_{segment_id}_message"

    @property
    def native_value(self) -> Any:
        d = self._get()
        first = (d or {}).get("first")
        if not first:
            return "Ingen"
        return first.get("label") or first.get("text") or "Hendelse"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._get() or {}
        attrs: dict[str, Any] = {ATTR_MATCHED: int(d.get("count") or 0)}
        events = d.get("events") or []
        attrs[ATTR_MESSAGE] = [
            {k: v for k, v in ev.items() if k in ("label", "text", "distance_km", "road_number", "location_for_display", "lat", "lon")}
            for ev in events
        ]
        if d.get("first"):
            attrs[ATTR_SOURCE] = d.get("first")
        return attrs
