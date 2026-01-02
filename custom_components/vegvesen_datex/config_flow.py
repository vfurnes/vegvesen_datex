from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    # options storage
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    TYPE_SITUATION,
    TYPE_WEATHER,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    # site picker
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_SITE_FILTER,
    # entities
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_CLOSED,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_DIRECTION,
    ENTITY_TEMPERATURE,
    ENTITY_HUMIDITY,
    ENTITY_PRESSURE,
    ENTITY_PRECIP_INTENSITY,
)

from .datex_client import DatexClient

_LOGGER = logging.getLogger(__name__)

class VegvesenDatexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Install flow: only credentials (+ scan interval)."""

    VERSION = 2

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        # Only one config entry (shared credentials).
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            username = (user_input.get(CONF_USERNAME) or "").strip()
            password = user_input.get(CONF_PASSWORD) or ""
            scan = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

            if not username or not password:
                errors["base"] = "auth"
            else:
                try:
                    client = DatexClient(self.hass, username, password)
                    await client.fetch_situation()  # verify creds
                except Exception:
                    errors["base"] = "auth"

            if not errors:
                if scan < DEFAULT_SCAN_INTERVAL:
                    scan = DEFAULT_SCAN_INTERVAL

                return self.async_create_entry(
                    title="DATEX",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_SCAN_INTERVAL: scan,
                    },
                    options={CONF_SEGMENTS: []},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return VegvesenDatexOptionsFlowHandler(config_entry)


class VegvesenDatexOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

        self._site_options: dict[str, str] = {}
        self._adding_type: str | None = None

        # Situation being added
        self._segment_query: str | None = None
        self._segment_name: str | None = None

        # Weather site being added
        self._weather_site_id: str | None = None
        self._weather_site_name: str | None = None

        self._selected_entities: list[str] = []

    async def async_step_init(self, user_input=None) -> FlowResult:
        segment_summary = self._format_segment_summary()
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_situation", "add_weather", "manage_segments"],
            description_placeholders={"segment_summary": segment_summary},
        )

    async def async_step_manage_segments(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="manage_segments",
            data_schema=vol.Schema({}),
            description_placeholders={"segment_summary": self._format_segment_summary()},
        )

    async def async_step_add_situation(self, user_input=None) -> FlowResult:
        self._adding_type = TYPE_SITUATION
        errors: dict[str, str] = {}

        if user_input is not None:
            self._segment_query = (user_input.get(CONF_SEGMENT_QUERY) or "").strip()
            self._segment_name = (user_input.get(CONF_SEGMENT_NAME) or "").strip()

            if not self._segment_query:
                errors["base"] = "segment_required"
            else:
                if not self._segment_name:
                    self._segment_name = self._segment_query
                return await self.async_step_entities()

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_QUERY): str,
                vol.Optional(CONF_SEGMENT_NAME): str,
            }
        )
        return self.async_show_form(step_id="add_situation", data_schema=schema, errors=errors)

    async def async_step_add_weather(self, user_input=None) -> FlowResult:
        self._adding_type = TYPE_WEATHER
        return await self.async_step_site()
    
    async def async_step_site(self, user_input=None) -> FlowResult:
        """Pick weather measurement site. Filter is 'contains' on full name (and site_id)."""
        errors: dict[str, str] = {}
        filter_text = (user_input or {}).get(CONF_SITE_FILTER, "")
        if not isinstance(filter_text, str):
            filter_text = ""
        filter_text = filter_text.strip()

        try:
            client = DatexClient(
                self.hass,
                self.entry.data[CONF_USERNAME],
                self.entry.data[CONF_PASSWORD],
            )
            sites = await client.list_sites(filter_text)
            self._site_options = {site_id: site_name for site_id, site_name in sites}

            if user_input is not None:
                site_id = user_input.get(CONF_SITE_ID)

                if site_id is None:
                    errors["base"] = "site_required"
                elif site_id not in self._site_options:
                    errors["base"] = "site_required"
                else:
                    self._weather_site_id = site_id
                    self._weather_site_name = self._site_options.get(site_id) or str(site_id)
                    return await self.async_step_entities()

        except Exception as err:
            _LOGGER.exception("vegvesen_datex options: site step failed: %s", err)
            errors["base"] = "fetch_failed"
            self._site_options = {}

        schema_dict: dict = {vol.Optional(CONF_SITE_FILTER, default=filter_text): str}

        if self._site_options:
            schema_dict[vol.Required(CONF_SITE_ID)] = vol.In(self._site_options)
        else:
            schema_dict[vol.Required(CONF_SITE_ID)] = str
            if not errors.get("base"):
                errors["base"] = "no_sites"

        return self.async_show_form(step_id="site", data_schema=vol.Schema(schema_dict), errors=errors)


    async def async_step_entities(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        try:
            available = await self._get_available_entities()
        except Exception as err:
            available = {"options": {}, "defaults": []}
            errors["base"] = "fetch_failed"

        if user_input is not None:
            selected = user_input.get(CONF_SEGMENT_ENTITIES) or []
            if not selected:
                errors["base"] = "entities_required"
            else:
                self._selected_entities = list(selected)
                self._save_item()
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SEGMENT_ENTITIES,
                    default=available.get("defaults", []),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=k, label=v)
                            for k, v in (available.get("options", {}) or {}).items()
                        ],
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema, errors=errors)

    async def _get_available_entities(self) -> dict[str, list[str] | dict[str, str]]:
        client = DatexClient(
            self.hass,
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
        )

        if self._adding_type == TYPE_SITUATION:
            status = await client.get_status_for_query(self._segment_query or "")
            options = {
                ENTITY_STATUS: f"Status (sist: {status.status})",
                ENTITY_MESSAGE: "Hendelse / tekst",
                ENTITY_CLOSED: f"Stengt (sist: {'ja' if status.is_closed else 'nei'})",
            }
            defaults = [ENTITY_STATUS, ENTITY_MESSAGE, ENTITY_CLOSED]
            return {"options": options, "defaults": defaults}

        # TYPE_WEATHER
        site_id = self._weather_site_id or ""
        measurements = await client.get_measurements_for_site(site_id)

        options: dict[str, str] = {}
        defaults: list[str] = []

        def add_if_present(key: str, label: str, unit: str = ""):
            if key in measurements and measurements[key] is not None:
                val = measurements[key]
                suffix = f" (sist: {val}{unit})" if unit else f" (sist: {val})"
                options[key] = f"{label}{suffix}"
                defaults.append(key)

        add_if_present(ENTITY_WIND_SPEED, "Vindstyrke", " m/s")
        add_if_present(ENTITY_WIND_DIRECTION, "Vindretning", "°")
        add_if_present(ENTITY_TEMPERATURE, "Temperatur", " °C")
        add_if_present(ENTITY_HUMIDITY, "Luftfuktighet", " %")
        add_if_present(ENTITY_PRESSURE, "Lufttrykk", " hPa")
        add_if_present(ENTITY_PRECIP_INTENSITY, "Nedbør-intensitet", "")

        if not options:
            options = {
                ENTITY_WIND_SPEED: "Vindstyrke (hvis tilgjengelig)",
                ENTITY_WIND_DIRECTION: "Vindretning (hvis tilgjengelig)",
            }
            defaults = [ENTITY_WIND_SPEED, ENTITY_WIND_DIRECTION]

        return {"options": options, "defaults": defaults}

    def _save_item(self) -> None:
        segments = list(self.entry.options.get(CONF_SEGMENTS, []))

        # Migration: if old segments exist without type, treat as situation
        for seg in segments:
            if CONF_ITEM_TYPE not in seg and seg.get(CONF_SEGMENT_QUERY):
                seg[CONF_ITEM_TYPE] = TYPE_SITUATION

        new_id = f"item_{len(segments) + 1}"

        if self._adding_type == TYPE_SITUATION:
            segments.append(
                {
                    CONF_ITEM_TYPE: TYPE_SITUATION,
                    CONF_SEGMENT_ID: new_id,
                    CONF_SEGMENT_NAME: self._segment_name,
                    CONF_SEGMENT_QUERY: self._segment_query,
                    CONF_SEGMENT_ENTITIES: self._selected_entities,
                }
            )
        else:
            segments.append(
                {
                    CONF_ITEM_TYPE: TYPE_WEATHER,
                    CONF_SEGMENT_ID: new_id,
                    CONF_SEGMENT_NAME: self._weather_site_name,
                    CONF_SITE_ID: self._weather_site_id,
                    CONF_SITE_NAME: self._weather_site_name,
                    CONF_SEGMENT_ENTITIES: self._selected_entities,
                }
            )

        self.hass.config_entries.async_update_entry(self.entry, options={CONF_SEGMENTS: segments})

    def _format_segment_summary(self) -> str:
        segments = self.entry.options.get(CONF_SEGMENTS, [])
        if not segments:
            return "Ingen oppføringer lagt til."

        for seg in segments:
            if CONF_ITEM_TYPE not in seg and seg.get(CONF_SEGMENT_QUERY):
                seg[CONF_ITEM_TYPE] = TYPE_SITUATION

        lines = []
        for seg in segments:
            t = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION
            name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SEGMENT_QUERY) or seg.get(CONF_SITE_NAME) or "Ukjent"
            entities = seg.get(CONF_SEGMENT_ENTITIES) or []
            prefix = "Veistykke" if t == TYPE_SITUATION else "Målested"
            lines.append(f"- {prefix}: {name} ({len(entities)} entiteter)")
        return "\\n".join(lines)
