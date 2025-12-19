from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_QUERY, CONF_SCAN_INTERVAL, DEFAULT_QUERY, DEFAULT_SCAN_INTERVAL
from .datex_client import DatexClient


class VegvesenDatexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            query = user_input[CONF_QUERY].strip()
            scan = int(user_input[CONF_SCAN_INTERVAL])

            try:
                client = DatexClient(self.hass, username, password)
                await client.fetch_situation()  # verifiser creds
            except Exception:
                errors["base"] = "auth"

            if not errors:
                # Hindrer duplikater for samme søk (valgfritt)
                await self.async_set_unique_id(f"{username}:{query}".lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"DATEX: {query}",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_QUERY: query,
                        CONF_SCAN_INTERVAL: scan,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_QUERY, default=DEFAULT_QUERY): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=3600)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
