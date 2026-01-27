from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta


from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_QUERY,  # legacy
    CONF_SITE_ID,  # legacy
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    TYPE_SITUATION,
    TYPE_RADIUS,
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


STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}_known_stretches"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    if scan < DEFAULT_SCAN_INTERVAL:
        scan = DEFAULT_SCAN_INTERVAL

    client = DatexClient(hass, username, password)

    items = _get_items(entry)
    coordinator = DatexCoordinator(hass, client, items, scan)
    coordinator.config_entry_id = entry.entry_id
    await coordinator.async_config_entry_first_refresh()
    # Load learned stretches (situation locations) and keep in memory
    store = Store(hass, STORE_VERSION, STORE_KEY)
    learned = await store.async_load() or {}
    hass.data[DOMAIN].setdefault("_known_stretches", learned)

    async def _learn_stretches(_now=None):
        try:
            xml_text = await client.fetch_situation()
            candidates = client.extract_situation_candidates(xml_text)
            # merge
            changed = False
            data = hass.data[DOMAIN].setdefault("_known_stretches", {})
            for c in candidates:
                cid = c["id"]
                if cid not in data:
                    data[cid] = {
                        "label": c["label"],
                        "token1": c.get("token1",""),
                        "token2": c.get("token2",""),
                    }
                    changed = True
            if changed:
                await store.async_save(data)
        except Exception:
            # keep silent to avoid spamming logs; enable debug if needed
            return

    # Run once shortly after startup, then hourly
    hass.async_create_task(_learn_stretches())
    async_track_time_interval(hass, _learn_stretches, timedelta(hours=1))


    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "segments": items,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _get_items(entry: ConfigEntry) -> list[dict]:
    """Read items from options (preferred). Keep compatibility with legacy data fields."""
    items = entry.options.get(CONF_SEGMENTS)
    if items:
        out = []
        for it in items:
            if CONF_ITEM_TYPE not in it:
                # Legacy “segment” => situation
                it = {**it, CONF_ITEM_TYPE: TYPE_SITUATION}
            out.append(it)
        return out

    # Legacy: single query stored in entry.data
    query = entry.data.get(CONF_QUERY)
    if not query:
        return []

    site_id = entry.data.get(CONF_SITE_ID)
    entities = [ENTITY_STATUS, ENTITY_MESSAGE, ENTITY_CLOSED]
    if site_id:
        entities.extend([ENTITY_WIND_SPEED, ENTITY_WIND_DIRECTION])

    return [
        {
            CONF_ITEM_TYPE: TYPE_SITUATION,
            CONF_SEGMENT_ID: entry.entry_id,
            CONF_SEGMENT_NAME: query,
            CONF_SEGMENT_QUERY: query,
            CONF_SEGMENT_ENTITIES: entities,
        }
    ]
