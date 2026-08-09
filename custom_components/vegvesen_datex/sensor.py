
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import UnitOfSpeed, DEGREE, UnitOfTemperature, PERCENTAGE, UnitOfTime

from .const import (
    DOMAIN,
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    TYPE_WEATHER,
    TYPE_SITUATION,
    TYPE_RADIUS,
    TYPE_TRAVEL_TIME,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_TEMPERATURE,
    ENTITY_DEW_POINT,
    ENTITY_HUMIDITY,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_GUST,
    ENTITY_WIND_GUST_CURRENT,
    ENTITY_WIND_DIRECTION,
    ENTITY_PRECIPITATION_INTENSITY,
    ENTITY_ROAD_SURFACE_CONDITION,
    ENTITY_ROAD_SURFACE_TEMPERATURE,
    ENTITY_ROAD_SURFACE_FRICTION,
    ENTITY_ROAD_SURFACE_WATER_FILM,
    ENTITY_ROAD_SURFACE_ICE_LAYER,
    ENTITY_ROAD_SURFACE_SNOW_DEPTH,
    ENTITY_TRAVEL_TIME,
    ENTITY_FREE_FLOW_TRAVEL_TIME,
    ENTITY_TRAVEL_TIME_DELAY,
    ENTITY_FREE_FLOW_SPEED,
    ENTITY_TRAFFIC_STATUS,
    ENTITY_TRAVEL_TIME_TREND,
    ENTITY_TRAVEL_TIME_TYPE,
    ATTR_MESSAGE,
    ATTR_MATCHED,
    ATTR_SOURCE,
    ATTR_LAST_MEASURED,
    ATTR_PERIOD_START,
    ATTR_PERIOD_END,
)
from .coordinator import DatexCoordinator, travel_time_bucket_key
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
        seg_name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SITE_NAME) or seg.get(CONF_SEGMENT_QUERY) or "DATEX"
        selected = set(seg.get(CONF_SEGMENT_ENTITIES, []))

        if not seg_id:
            continue

        if item_type == TYPE_WEATHER:
            site_id = str(seg.get(CONF_SITE_ID) or seg_id)
            site_name = seg.get(CONF_SITE_NAME) or seg_name

            _W = _MeasuredValueSensor  # shorthand
            _M = SensorStateClass.MEASUREMENT
            if ENTITY_HUMIDITY in selected:
                entities.append(_W(coordinator, site_id, site_name, "humidity", "Luftfuktighet", PERCENTAGE, SensorDeviceClass.HUMIDITY, state_class=_M))
            if ENTITY_TEMPERATURE in selected:
                entities.append(_W(coordinator, site_id, site_name, "temperature", "Temperatur", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, state_class=_M))
            if ENTITY_DEW_POINT in selected:
                entities.append(_W(coordinator, site_id, site_name, "dew_point_temperature", "Duggpunkt", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, state_class=_M))
            if ENTITY_WIND_DIRECTION in selected:
                # WIND_DIRECTION permits no state class at all - giving it one
                # makes Home Assistant reject the combination.
                entities.append(_W(coordinator, site_id, site_name, "wind_direction", "Vindretning", DEGREE, SensorDeviceClass.WIND_DIRECTION, state_class=None))
            if ENTITY_WIND_SPEED in selected:
                entities.append(_W(coordinator, site_id, site_name, "wind_speed", "Vindstyrke", UnitOfSpeed.METERS_PER_SECOND, SensorDeviceClass.WIND_SPEED, state_class=_M))
            if ENTITY_WIND_GUST in selected:
                entities.append(_W(coordinator, site_id, site_name, "wind_gust", "Vindkast", UnitOfSpeed.METERS_PER_SECOND, SensorDeviceClass.WIND_SPEED, state_class=_M, include_period=True))
            if ENTITY_WIND_GUST_CURRENT in selected:
                entities.append(_W(coordinator, site_id, site_name, "wind_gust_current", "Vindkast nå", UnitOfSpeed.METERS_PER_SECOND, SensorDeviceClass.WIND_SPEED, state_class=_M))
            if ENTITY_PRECIPITATION_INTENSITY in selected:
                entities.append(_W(coordinator, site_id, site_name, "precipitation_intensity", "Nedbørsintensitet", "mm/h", SensorDeviceClass.PRECIPITATION_INTENSITY, state_class=_M))
            if ENTITY_ROAD_SURFACE_CONDITION in selected:
                # Free text, so neither a device class nor a state class applies.
                entities.append(_W(coordinator, site_id, site_name, "road_surface_condition", "Føreforhold", None, None, state_class=None))
            if ENTITY_ROAD_SURFACE_TEMPERATURE in selected:
                entities.append(_W(coordinator, site_id, site_name, "road_surface_temperature", "Vegbanetemperat.", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, state_class=_M))
            if ENTITY_ROAD_SURFACE_FRICTION in selected:
                entities.append(_W(coordinator, site_id, site_name, "road_surface_friction", "Friksjon", None, None, state_class=_M))
            if ENTITY_ROAD_SURFACE_WATER_FILM in selected:
                entities.append(_W(coordinator, site_id, site_name, "road_surface_water_film", "Vannfilm", "m", None, state_class=_M))
            if ENTITY_ROAD_SURFACE_ICE_LAYER in selected:
                entities.append(_W(coordinator, site_id, site_name, "road_surface_ice_layer", "Islag", "m", None, state_class=_M))
            if ENTITY_ROAD_SURFACE_SNOW_DEPTH in selected:
                entities.append(_W(coordinator, site_id, site_name, "road_surface_snow_depth", "Snødybde", "m", None, state_class=_M))

        elif item_type == TYPE_TRAVEL_TIME:
            # A single stretch keys off its own DATEX location id; several
            # stretches accumulated together key off the segment's own id (see
            # coordinator.travel_time_bucket_key - this must match how the
            # coordinator stores data["travel_time"], or lookups below miss).
            site_id = travel_time_bucket_key(seg) or str(seg_id)
            site_name = seg.get(CONF_SITE_NAME) or seg_name

            def _T(key, name_suffix, unit, device_class, state_class=None, include_period=False):
                return _MeasuredValueSensor(
                    coordinator, site_id, site_name, key, name_suffix, unit, device_class,
                    state_class=state_class, include_period=include_period,
                    data_bucket="travel_time", device_id_prefix="travel_time",
                    model="DATEX II Travel Time",
                )

            _M = SensorStateClass.MEASUREMENT
            if ENTITY_TRAVEL_TIME in selected:
                entities.append(_T(ENTITY_TRAVEL_TIME, "Reisetid", UnitOfTime.SECONDS, SensorDeviceClass.DURATION, state_class=_M, include_period=True))
            if ENTITY_FREE_FLOW_TRAVEL_TIME in selected:
                entities.append(_T(ENTITY_FREE_FLOW_TRAVEL_TIME, "Reisetid uten kø", UnitOfTime.SECONDS, SensorDeviceClass.DURATION, state_class=_M))
            if ENTITY_FREE_FLOW_SPEED in selected:
                entities.append(_T(ENTITY_FREE_FLOW_SPEED, "Fri flyt-hastighet", UnitOfSpeed.KILOMETERS_PER_HOUR, SensorDeviceClass.SPEED, state_class=_M))
            if ENTITY_TRAFFIC_STATUS in selected:
                # Free text enum (freeFlow/heavy/…), so neither device class nor state class applies.
                entities.append(_T(ENTITY_TRAFFIC_STATUS, "Trafikkstatus", None, None, state_class=None))
            if ENTITY_TRAVEL_TIME_TREND in selected:
                entities.append(_T(ENTITY_TRAVEL_TIME_TREND, "Trend", None, None, state_class=None))
            if ENTITY_TRAVEL_TIME_TYPE in selected:
                entities.append(_T(ENTITY_TRAVEL_TIME_TYPE, "Beregningstype", None, None, state_class=None))
            if ENTITY_TRAVEL_TIME_DELAY in selected:
                entities.append(_TravelTimeDelaySensor(coordinator, site_id, site_name))

        elif item_type in (TYPE_SITUATION, TYPE_RADIUS):
            if ENTITY_STATUS in selected:
                entities.append(_SituationStatusSensor(coordinator, str(seg_id), seg_name))
            if ENTITY_MESSAGE in selected:
                entities.append(_SituationMessageSensor(coordinator, str(seg_id), seg_name))

    # No update_before_add: the coordinator has already done its first refresh
    # in async_setup_entry, so forcing an update per entity only serialised
    # waits and made platform setup exceed ten seconds.
    async_add_entities(entities)


@dataclass(frozen=True)
class _KeySpec:
    key: str
    include_period: bool = False


class _MeasuredValueSensor(SensorEntity):
    _attr_has_entity_name = True
    # The coordinator pushes updates through the listener registered in
    # async_added_to_hass. Polling fetched nothing new - it only queued another
    # refresh request and waited on the debouncer, which is what produced
    # "Update of sensor.… is taking over 10 seconds".
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DatexCoordinator,
        site_id: str,
        site_name: str,
        key: str,
        name_suffix: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None = None,
        include_period: bool = False,
        data_bucket: str = "weather",
        device_id_prefix: str = "weather_site",
        model: str = "DATEX II Weather Station",
    ) -> None:
        self.coordinator = coordinator
        self.site_id = site_id
        self.site_name = site_name
        self._data_bucket = data_bucket
        self._spec = _KeySpec(key=key, include_period=include_period)

        self._attr_name = name_suffix
        self._attr_unique_id = f"{coordinator.config_entry_id}_{site_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        # Without a state class the readings never reach long-term statistics,
        # so history is limited to whatever the recorder still holds.
        self._attr_state_class = state_class

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device_id_prefix}_{site_id}")},
            name=site_name,
            manufacturer="Statens vegvesen",
            model=model,
        )

    def _get_measured(self) -> MeasuredValue | None:
        bucket = (self.coordinator.data or {}).get(self._data_bucket, {})
        seg = bucket.get(self.site_id)
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
        attrs: dict[str, Any] = {}
        if mv is not None:
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


class _TravelTimeDelaySensor(SensorEntity):
    """Travel time minus free-flow travel time, in seconds.

    Derived from two DATEX fields rather than a straight passthrough of one, so it
    doesn't fit the generic _MeasuredValueSensor.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DatexCoordinator, site_id: str, site_name: str) -> None:
        self.coordinator = coordinator
        self.site_id = site_id

        self._attr_name = "Forsinkelse"
        self._attr_unique_id = f"{coordinator.config_entry_id}_{site_id}_{ENTITY_TRAVEL_TIME_DELAY}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"travel_time_{site_id}")},
            name=site_name,
            manufacturer="Statens vegvesen",
            model="DATEX II Travel Time",
        )

    def _bucket(self) -> dict[str, MeasuredValue]:
        travel_time = (self.coordinator.data or {}).get("travel_time", {})
        return travel_time.get(self.site_id) or {}

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> Any:
        bucket = self._bucket()
        travel_time = bucket.get(ENTITY_TRAVEL_TIME)
        free_flow = bucket.get(ENTITY_FREE_FLOW_TRAVEL_TIME)
        if travel_time is None or free_flow is None:
            return None
        if travel_time.value is None or free_flow.value is None:
            return None
        return round(travel_time.value - free_flow.value, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mv = self._bucket().get(ENTITY_TRAVEL_TIME)
        if mv and mv.time_value:
            return {ATTR_LAST_MEASURED: mv.time_value}
        return {}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()


class _SituationBaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DatexCoordinator, segment_id: str, name: str) -> None:
        self.coordinator = coordinator
        self.segment_id = segment_id
        self._base_name = name

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"situation_{segment_id}")},
            name=name,
            manufacturer="Statens vegvesen",
            model="DATEX II Situation Feed",
        )

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
        d = self._get() or {}
        count = int(d.get("count") or 0)
        if count == 0:
            return "Ingen hendelser"
        if count == 1:
            return "1 hendelse"
        return f"{count} hendelser"

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
