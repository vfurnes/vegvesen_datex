from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ITEM_TYPE,
    TYPE_SITUATION,
    TYPE_WEATHER,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_QUERY,
    CONF_SITE_ID,
)
from .datex_client import DatexClient

_LOGGER = logging.getLogger(__name__)


class DatexCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: DatexClient,
        segments: list[dict[str, Any]],
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="vegvesen_datex",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.segments = segments

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data: dict[str, Any] = {}
            for item in self.segments:
                item_id = item.get(CONF_SEGMENT_ID)
                item_type = item.get(CONF_ITEM_TYPE) or TYPE_SITUATION
                if not item_id:
                    continue

                if item_type == TYPE_SITUATION:
                    query = item.get(CONF_SEGMENT_QUERY) or ""
                    status = await self.client.get_status_for_query(query)
                    data[item_id] = {"status": status}
                    continue

                if item_type == TYPE_WEATHER:
                    site_id = item.get(CONF_SITE_ID)
                    measurements = {}
                    if site_id:
                        measurements = await self.client.get_measurements_for_site(site_id)
                    data[item_id] = {"weather": measurements}
                    continue

            return data
        except Exception as err:
            raise UpdateFailed(str(err)) from err
