from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SEGMENT_ID, CONF_SEGMENT_QUERY, CONF_SITE_ID
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
            for segment in self.segments:
                segment_id = segment.get(CONF_SEGMENT_ID)
                query = segment.get(CONF_SEGMENT_QUERY) or ""
                site_id = segment.get(CONF_SITE_ID)
                if not segment_id:
                    continue

                status = await self.client.get_status_for_query(query)
                wind_ms = None
                wind_deg = None
                if site_id:
                    wind_ms, wind_deg = await self.client.get_wind_for_site(site_id)

                data[segment_id] = {
                    "status": status,
                    "wind_ms": wind_ms,
                    "wind_deg": wind_deg,
                }

            return data
        except Exception as err:
            raise UpdateFailed(str(err)) from err
