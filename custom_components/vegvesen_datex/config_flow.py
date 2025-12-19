from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_QUERY,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_SITE_FILTER,
    DEFAULT_QUERY,
    DEFAULT_SCAN_INTERVAL,
)
from .datex_client import DatexClient


class VegvesenDatexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict[str, str] | None = None
        self._site_options: dict[str, str] = {}
        super().__init__()

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            scan = int(user_input[CONF_SCAN_INTERVAL])

            try:
                client = DatexClient(self.hass, username, password)
                await client.fetch_situation()  # verifiser creds
            except Exception:
                errors["base"] = "auth"

            if not errors:
                self._creds = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_SCAN_INTERVAL: scan,
                }
                return await self.async_step_site()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=3600)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_site(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if not self._creds:
            return await self.async_step_user()

        filter_text = (user_input or {}).get(CONF_SITE_FILTER, "").strip()
        client = DatexClient(self.hass, self._creds[CONF_USERNAME], self._creds[CONF_PASSWORD])
        sites = await client.list_sites(filter_text)
        self._site_options = {site_id: site_name for site_id, site_name in sites}
        if not self._site_options:
            errors["base"] = "no_sites"

        if user_input is not None:
            site_id = user_input.get(CONF_SITE_ID)
            if site_id and site_id in self._site_options:
                site_name = self._site_options[site_id]
                await self.async_set_unique_id(f"{self._creds[CONF_USERNAME]}:{site_id}".lower())
                self._abort_if_unique_id_configured()
                data = {
                    **self._creds,
                    CONF_QUERY: site_name or DEFAULT_QUERY,
                    CONF_SITE_ID: site_id,
                    CONF_SITE_NAME: site_name,
                }
                return self.async_create_entry(title=f"DATEX: {site_name}", data=data)
            if not errors:
                errors["base"] = "site_required"

        schema = vol.Schema(
            {
                vol.Optional(CONF_SITE_FILTER, default=filter_text): str,
                vol.Required(CONF_SITE_ID): vol.In(self._site_options or {}),
            }
        )
        return self.async_show_form(step_id="site", data_schema=schema, errors=errors)
