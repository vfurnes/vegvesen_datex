from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .datex_client import DatexClient, DatexResult

_LOGGER = logging.getLogger(__name__)


class DatexCoordinator(DataUpdateCoordinator[DatexResult]):
    def __init__(self, hass: HomeAssistant, client: DatexClient, query: str, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="vegvesen_datex",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.query = query

    async def _async_update_data(self) -> DatexResult:
        try:
            return await self.client.get_status_for_query(self.query)
        except Exception as err:
            raise UpdateFailed(str(err)) from err
