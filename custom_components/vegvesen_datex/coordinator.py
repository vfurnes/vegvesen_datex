from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    TYPE_WEATHER,
    TYPE_SITUATION,
    CONF_SITE_ID,
    CONF_SEGMENT_QUERY,
)
from .datex_client import DatexClient

_LOGGER = logging.getLogger(__name__)


class DatexCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: DatexClient,
        segments: list[dict[str, Any]],
        scan_interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.client = client
        self.segments = segments

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"weather": {}, "situation": {}}

        try:
            # WEATHER: fetch per weather segment (simple & robust)
            for seg in self.segments:
                if seg.get(CONF_ITEM_TYPE) != TYPE_WEATHER:
                    continue
                site_id = seg.get(CONF_SITE_ID)
                if not site_id:
                    continue
                values = await self.client.fetch_measured_weather_site(str(site_id))
                data["weather"][seg["segment_id"]] = values

            # SITUATION: keep existing behavior as raw xml (if you use it elsewhere)
            # (Not changing your situation logic in this patch – can expand later.)
            for seg in self.segments:
                if seg.get(CONF_ITEM_TYPE) != TYPE_SITUATION:
                    continue
                # For now, store the query so sensors can decide what to do
                data["situation"][seg["segment_id"]] = {
                    "query": seg.get(CONF_SEGMENT_QUERY) or "",
                }

        except Exception as err:
            raise UpdateFailed(str(err)) from err

        return data
