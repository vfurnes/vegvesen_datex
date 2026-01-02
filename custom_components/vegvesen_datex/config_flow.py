from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_SITE_FILTER,
    CONF_SEGMENTS,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    CONF_ADD_ANOTHER,
    DEFAULT_SCAN_INTERVAL,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_CLOSED,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_DIRECTION,
)
from .datex_client import DatexClient


class VegvesenDatexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Statens vegvesen DATEX.

    Solution A:
    - One config entry stores credentials + scan interval
    - One or more "segments" (bridges/roads) are stored in config entry options
    - Additional segments can be added later via the Options flow (Systemalternativer)
    """

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._username: str | None = None
        self._password: str | None = None
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL

        # Segment being created in the flow
        self._segment_name: str | None = None
        self._segment_query: str | None = None
        self._segment_site_id: str | None = None
        self._segment_site_name: str | None = None
        self._segment_entities: list[str] = []

        self._site_options: dict[str, str] = {}

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: enter credentials once."""
        errors: dict[str, str] = {}

        # Only one config entry is supported (credentials are shared).
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            username = (user_input.get(CONF_USERNAME) or "").strip()
            password = user_input.get(CONF_PASSWORD) or ""
            scan = int(user_input[CONF_SCAN_INTERVAL])

            if not username or not password:
                errors["base"] = "auth"
            else:
                try:
                    client = DatexClient(self.hass, username, password)
                    await client.fetch_situation()  # verify creds
                except Exception:
                    errors["base"] = "auth"

            if not errors:
                self._username = username
                self._password = password
                self._scan_interval = scan
                # Continue to create the first segment immediately
                return await self.async_step_add_segment()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_add_segment(self, user_input=None) -> FlowResult:
        """Step 2: enter the road segment query and optional display name."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._segment_query = (user_input.get(CONF_SEGMENT_QUERY) or "").strip()
            self._segment_name = (user_input.get(CONF_SEGMENT_NAME) or "").strip()

            if not self._segment_query:
                errors["base"] = "segment_required"
            else:
                if not self._segment_name:
                    self._segment_name = self._segment_query
                return await self.async_step_site()

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_QUERY): str,
                vol.Optional(CONF_SEGMENT_NAME): str,
            }
        )
        return self.async_show_form(step_id="add_segment", data_schema=schema, errors=errors)

    async def async_step_site(self, user_input=None) -> FlowResult:
        """Step 3: list and select measurement site (optional).

        If we cannot load sites (auth/network/parse), we still allow the user to continue
        without selecting a site, but we surface a friendly error instead of 'Unknown error'.
        """
        errors: dict[str, str] = {}

        filter_text = (user_input or {}).get(CONF_SITE_FILTER, "").strip()

        # Load site options (can be empty)
        self._site_options = {}
        try:
            client = DatexClient(self.hass, self._username or "", self._password or "")
            sites = await client.list_sites(filter_text)
            self._site_options = {site_id: site_name for site_id, site_name in sites}
        except Exception:
            # Config flow will show "Unknown error" if we let exceptions bubble up.
            errors["base"] = "fetch_failed"

        if user_input is not None:
            site_id = (user_input.get(CONF_SITE_ID) or "").strip() or None

            # Allow blank (optional). If provided, validate against loaded options (if any).
            if site_id and self._site_options and site_id not in self._site_options:
                errors["base"] = "site_required"
            else:
                self._segment_site_id = site_id
                self._segment_site_name = self._site_options.get(site_id) if site_id else None
                return await self.async_step_entities()

        # Build schema.
        # NOTE: vol.In({}) crashes when the dict is empty -> 'Unknown error occurred'.
        schema_dict: dict = {vol.Optional(CONF_SITE_FILTER, default=filter_text): str}

        if self._site_options:
            schema_dict[vol.Optional(CONF_SITE_ID)] = vol.In(self._site_options)
        else:
            # Still show a text field so advanced users can paste an ID if needed.
            schema_dict[vol.Optional(CONF_SITE_ID)] = str

            # If we loaded successfully but found nothing, show a clearer message.
            if not errors.get("base") and filter_text:
                errors["base"] = "no_sites"

        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="site", data_schema=schema, errors=errors)

async def async_step_entities(self, user_input=None) -> FlowResult:
        """Step 4: select which entities to create for this segment."""
        errors: dict[str, str] = {}

        available = await self._get_available_entities()

        if user_input is not None:
            entities = user_input.get(CONF_SEGMENT_ENTITIES) or []
            if not entities:
                errors["base"] = "entities_required"
            else:
                self._segment_entities = list(entities)
                return self._create_entry_with_segment()

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_ENTITIES): vol.MultiSelect(
                    available["options"]
                ),
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema, errors=errors)

    def _create_entry_with_segment(self) -> FlowResult:
        """Create config entry and store segment in options."""
        # One initial segment
        segments = [
            {
                CONF_SEGMENT_ID: "seg_1",
                CONF_SEGMENT_NAME: self._segment_name,
                CONF_SEGMENT_QUERY: self._segment_query,
                CONF_SEGMENT_ENTITIES: self._segment_entities,
                CONF_SITE_ID: self._segment_site_id,
                CONF_SITE_NAME: self._segment_site_name,
            }
        ]

        return self.async_create_entry(
            title="DATEX",
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_SCAN_INTERVAL: self._scan_interval,
            },
            options={CONF_SEGMENTS: segments},
        )

    async def _get_available_entities(self) -> dict[str, dict[str, str]]:
        """Build entity choices with a tiny live preview based on the query."""
        client = DatexClient(self.hass, self._username or "", self._password or "")
        status = await client.get_status_for_query(self._segment_query or "")
        options = {
            ENTITY_STATUS: f"Status (sist: {status.status})",
            ENTITY_MESSAGE: "Hendelse",
            ENTITY_CLOSED: f"Stengt (sist: {'ja' if status.is_closed else 'nei'})",
            ENTITY_WIND: "Vind (hvis tilgjengelig)",
        }
        return {"options": options}


class VegvesenDatexOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        self._site_options: dict[str, str] = {}
        self._segment_name: str | None = None
        self._segment_query: str | None = None
        self._segment_site_id: str | None = None
        self._segment_site_name: str | None = None
        self._segment_entities: list[str] = []

    async def async_step_init(self, user_input=None) -> FlowResult:
        segment_summary = self._format_segment_summary()
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_segment", "manage_segments"],
            description_placeholders={"segment_summary": segment_summary},
        )

    async def async_step_manage_segments(self, user_input=None) -> FlowResult:
        if user_input is not None:
            if user_input.get(CONF_ADD_ANOTHER):
                return await self.async_step_add_segment()
            return self.async_create_entry(title="", data={})

        schema = vol.Schema({vol.Optional(CONF_ADD_ANOTHER, default=False): bool})
        return self.async_show_form(
            step_id="manage_segments",
            data_schema=schema,
            description_placeholders={"segment_summary": self._format_segment_summary()},
        )

    async def async_step_add_segment(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            self._segment_name = None
            self._segment_query = None
            self._segment_site_id = None
            self._segment_site_name = None
            self._segment_entities = []
        if user_input is not None:
            self._segment_query = (user_input.get(CONF_SEGMENT_QUERY) or "").strip()
            self._segment_name = (user_input.get(CONF_SEGMENT_NAME) or "").strip()
            if not self._segment_query:
                errors["base"] = "segment_required"
            else:
                if not self._segment_name:
                    self._segment_name = self._segment_query
                return await self.async_step_site()

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_QUERY): str,
                vol.Optional(CONF_SEGMENT_NAME): str,
            }
        )
        return self.async_show_form(step_id="add_segment", data_schema=schema, errors=errors)

    async def async_step_site(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        filter_text = (user_input or {}).get(CONF_SITE_FILTER, "").strip()
        client = DatexClient(
            self.hass,
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
        )
        sites = await client.list_sites(filter_text)
        self._site_options = {site_id: site_name for site_id, site_name in sites}

        if user_input is not None:
            site_id = user_input.get(CONF_SITE_ID)
            if site_id and site_id not in self._site_options:
                errors["base"] = "site_required"
            else:
                if site_id:
                    self._segment_site_id = site_id
                    self._segment_site_name = self._site_options.get(site_id)
                return await self.async_step_entities()

        if filter_text and not self._site_options:
            errors["base"] = "no_sites"

        schema = vol.Schema(
            {
                vol.Optional(CONF_SITE_FILTER, default=filter_text): str,
                vol.Optional(CONF_SITE_ID): vol.In(self._site_options or {}),
            }
        )
        return self.async_show_form(step_id="site", data_schema=schema, errors=errors)

    async def async_step_entities(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        try:
            available = await self._get_available_entities()
        except Exception:
            errors["base"] = "fetch_failed"
            available = {"options": {}, "defaults": []}

        if user_input is not None:
            selected = user_input.get(CONF_SEGMENT_ENTITIES, [])
            if not selected:
                errors["base"] = "entities_required"
            else:
                self._segment_entities = list(selected)
                self._save_segment()
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_ENTITIES, default=available["defaults"]): vol.MultiSelect(
                    available["options"]
                ),
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema, errors=errors)

    def _format_segment_summary(self) -> str:
        segments = self.entry.options.get(CONF_SEGMENTS, [])
        if not segments:
            if (self.hass.config.language or "").startswith(("nb", "no")):
                return "Ingen veistykker lagt til."
            return "No segments added."
        lines = []
        for seg in segments:
            name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SEGMENT_QUERY) or "Ukjent"
            entities = seg.get(CONF_SEGMENT_ENTITIES) or []
            lines.append(f"- {name} ({len(entities)} entiteter)")
        return "\\n".join(lines)

    async def _get_available_entities(self) -> dict[str, list[str] | dict[str, str]]:
        client = DatexClient(
            self.hass,
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
        )
        status = await client.get_status_for_query(self._segment_query or "")
        options = {
            ENTITY_STATUS: f"Status (sist: {status.status})",
            ENTITY_MESSAGE: "Hendelse",
            ENTITY_CLOSED: f"Stengt (sist: {'ja' if status.is_closed else 'nei'})",
        }
        defaults = [ENTITY_STATUS, ENTITY_MESSAGE, ENTITY_CLOSED]

        if self._segment_site_id:
            wind_ms, wind_deg = await client.get_wind_for_site(self._segment_site_id)
            options[ENTITY_WIND_SPEED] = (
                f"Vindstyrke (sist: {wind_ms} m/s)" if wind_ms is not None else "Vindstyrke"
            )
            options[ENTITY_WIND_DIRECTION] = (
                f"Vindretning (sist: {wind_deg}°)" if wind_deg is not None else "Vindretning"
            )
            defaults.extend([ENTITY_WIND_SPEED, ENTITY_WIND_DIRECTION])

        return {"options": options, "defaults": defaults}

    def _save_segment(self) -> None:
        segments = list(self.entry.options.get(CONF_SEGMENTS, []))
        segment_id = f"seg_{len(segments) + 1}"
        segments.append(
            {
                CONF_SEGMENT_ID: segment_id,
                CONF_SEGMENT_NAME: self._segment_name,
                CONF_SEGMENT_QUERY: self._segment_query,
                CONF_SEGMENT_ENTITIES: self._segment_entities,
                CONF_SITE_ID: self._segment_site_id,
                CONF_SITE_NAME: self._segment_site_name,
            }
        )
        self.hass.config_entries.async_update_entry(self.entry, options={CONF_SEGMENTS: segments})


async def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
    return VegvesenDatexOptionsFlowHandler(config_entry)
