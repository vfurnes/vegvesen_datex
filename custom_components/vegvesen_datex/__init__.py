from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_QUERY,
    CONF_SITE_ID,
    CONF_SEGMENTS,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_CLOSED,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_DIRECTION,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import DatexCoordinator
from .datex_client import DatexClient

PLATFORMS: list[str] = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    if scan < DEFAULT_SCAN_INTERVAL:
        scan = DEFAULT_SCAN_INTERVAL

    client = DatexClient(hass, username, password)
    segments = _get_segments(entry)
    coordinator = DatexCoordinator(hass, client, segments, scan)
    coordinator.config_entry_id = entry.entry_id
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "segments": segments,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _get_segments(entry: ConfigEntry) -> list[dict[str, str | list[str] | None]]:
    segments = entry.options.get(CONF_SEGMENTS)
    if segments:
        return segments

    query = entry.data.get(CONF_QUERY)
    if not query:
        return []

    site_id = entry.data.get(CONF_SITE_ID)
    entities = [ENTITY_STATUS, ENTITY_MESSAGE, ENTITY_CLOSED]
    if site_id:
        entities.extend([ENTITY_WIND_SPEED, ENTITY_WIND_DIRECTION])

    return [
        {
            CONF_SEGMENT_ID: entry.entry_id,
            CONF_SEGMENT_NAME: query,
            CONF_SEGMENT_QUERY: query,
            CONF_SEGMENT_ENTITIES: entities,
            CONF_SITE_ID: site_id,
        }
    ]
