from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .datex_client import DatexClient
from .const import CONF_SITE_ID  # legg denne i const.py

_LOGGER = logging.getLogger(__name__)


class DatexCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: DatexClient,
        query: str,
        scan_interval: int,
        site_id: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="vegvesen_datex",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.query = query
        self.site_id = site_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.client.get_status_for_query(self.query)

            wind_ms = None
            wind_deg = None
            if self.site_id:
                wind_ms, wind_deg = await self.client.get_wind_for_site(self.site_id)

            return {
                "status": status,       # DatexResult
                "wind_ms": wind_ms,     # float | None
                "wind_deg": wind_deg,   # float | None
            }
        except Exception as err:
            raise UpdateFailed(str(err)) from err
