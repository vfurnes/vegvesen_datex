from __future__ import annotations

import logging
import re
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
    # situation picker
    CONF_SITUATION_ID,
    CONF_SITUATION_FILTER,
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

    VERSION = 3

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

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
                    await client.fetch_situation()
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
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return VegvesenDatexOptionsFlowHandler(config_entry)


class VegvesenDatexOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

        # Common
        self._adding_type: str | None = None
        self._selected_entities: list[str] = []
        self._editing_item_id: str | None = None
        self._segments_cache: list[dict] = []

        # Situation add/edit
        self._situation_options: dict[str, str] = {}
        self._situation_id: str | None = None
        self._segment_name: str | None = None
        self._segment_query: str | None = None  # legacy fallback

        # Weather add/edit
        self._site_options: dict[str, str] = {}
        self._weather_site_id: str | None = None
        self._weather_site_name: str | None = None

    async def async_step_init(self, user_input=None) -> FlowResult:
        segment_summary = self._format_segment_summary()
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_situation", "add_weather", "edit_remove"],
            description_placeholders={"segment_summary": segment_summary},
        )

    async def async_step_edit_remove(self, user_input=None) -> FlowResult:
        segments = list(self.entry.options.get(CONF_SEGMENTS, [])) or []
        segments = self._migrate_segments(segments)

        if not segments:
            return self.async_abort(reason="no_items")

        self._segments_cache = segments

        options = {}
        for seg in segments:
            item_id = seg.get(CONF_SEGMENT_ID)
            t = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION
            name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SITE_NAME) or seg.get(CONF_SEGMENT_QUERY) or "Ukjent"
            prefix = "Veistykke" if t == TYPE_SITUATION else "Målested"
            if item_id:
                options[item_id] = f"{prefix}: {name}"

        schema = vol.Schema(
            {
                vol.Required("item_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in options.items()],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "edit", "label": "Rediger"},
                            {"value": "remove", "label": "Fjern"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        if user_input is None:
            return self.async_show_form(
                step_id="edit_remove",
                data_schema=schema,
                description_placeholders={"segment_summary": self._format_segment_summary()},
            )

        item_id = user_input["item_id"]
        action = user_input["action"]

        if action == "remove":
            new_segments = [s for s in segments if s.get(CONF_SEGMENT_ID) != item_id]
            return self.async_create_entry(title="", data={CONF_SEGMENTS: new_segments})

        # action == edit
        self._editing_item_id = item_id
        item = next((s for s in segments if s.get(CONF_SEGMENT_ID) == item_id), None)
        if not item:
            return self.async_abort(reason="no_items")

        self._adding_type = item.get(CONF_ITEM_TYPE) or TYPE_SITUATION
        self._selected_entities = list(item.get(CONF_SEGMENT_ENTITIES) or [])

        if self._adding_type == TYPE_WEATHER:
            self._weather_site_id = item.get(CONF_SITE_ID)
            self._weather_site_name = item.get(CONF_SITE_NAME) or item.get(CONF_SEGMENT_NAME)
            return await self.async_step_site()

        # TYPE_SITUATION
        self._situation_id = item.get(CONF_SITUATION_ID)
        self._segment_name = item.get(CONF_SEGMENT_NAME)
        self._segment_query = item.get(CONF_SEGMENT_QUERY)
        return await self.async_step_add_situation()

    async def async_step_add_situation(self, user_input=None) -> FlowResult:
        """Pick a DATEX situationRecord (dropdown + filter)."""
        self._adding_type = TYPE_SITUATION
        errors: dict[str, str] = {}

        filter_text = (user_input or {}).get(CONF_SITUATION_FILTER, "")
        if not isinstance(filter_text, str):
            filter_text = ""
        filter_text = filter_text.strip()

        try:
            client = DatexClient(
                self.hass,
                self.entry.data[CONF_USERNAME],
                self.entry.data[CONF_PASSWORD],
            )
            items = await client.list_situations(filter_text)
            self._situation_options = {rid: label for rid, label in items}
        except Exception as err:
            _LOGGER.exception("vegvesen_datex options: list_situations failed: %s", err)
            self._situation_options = {}
            errors["base"] = "fetch_failed"

        schema_dict: dict = {
            vol.Optional(CONF_SITUATION_FILTER, default=filter_text): str,
        }

        default_id = self._situation_id if self._situation_id in self._situation_options else None

        if self._situation_options:
            schema_dict[vol.Required(CONF_SITUATION_ID, default=default_id)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in self._situation_options.items()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            schema_dict[vol.Optional(CONF_SITUATION_ID)] = str
            errors["base"] = errors.get("base") or "no_sites"

        schema_dict[vol.Optional(CONF_SEGMENT_NAME, default=self._segment_name or "")] = str

        if user_input is None or CONF_SITUATION_ID not in (user_input or {}):
            return self.async_show_form(step_id="add_situation", data_schema=vol.Schema(schema_dict), errors=errors)

        situation_id = (user_input.get(CONF_SITUATION_ID) or "").strip()
        if not situation_id:
            errors["base"] = "site_required"
            return self.async_show_form(step_id="add_situation", data_schema=vol.Schema(schema_dict), errors=errors)

        self._situation_id = situation_id

        # Default display name: label from dropdown
        name_in = (user_input.get(CONF_SEGMENT_NAME) or "").strip()
        self._segment_name = name_in or self._situation_options.get(situation_id) or situation_id

        # Legacy fallback query (helps old sensors/name logic)
        self._segment_query = self._segment_name

        return await self.async_step_entities()

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
        except Exception as err:
            _LOGGER.exception("vegvesen_datex options: site step failed: %s", err)
            errors["base"] = "fetch_failed"
            self._site_options = {}

        schema_dict: dict = {vol.Optional(CONF_SITE_FILTER, default=filter_text): str}

        default_site = self._weather_site_id if self._weather_site_id in self._site_options else None

        if self._site_options:
            schema_dict[vol.Required(CONF_SITE_ID, default=default_site)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in self._site_options.items()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            schema_dict[vol.Optional(CONF_SITE_ID)] = str
            errors["base"] = errors.get("base") or "no_sites"

        if user_input is None or CONF_SITE_ID not in (user_input or {}):
            return self.async_show_form(step_id="site", data_schema=vol.Schema(schema_dict), errors=errors)

        site_id = (user_input.get(CONF_SITE_ID) or "").strip()
        if not site_id:
            errors["base"] = "site_required"
            return self.async_show_form(step_id="site", data_schema=vol.Schema(schema_dict), errors=errors)

        self._weather_site_id = site_id
        self._weather_site_name = self._site_options.get(site_id) or site_id
        return await self.async_step_entities()

    async def async_step_entities(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        try:
            available = await self._get_available_entities()
        except Exception as err:
            _LOGGER.exception("vegvesen_datex options: entities failed: %s", err)
            available = {"options": {}, "defaults": []}
            errors["base"] = "fetch_failed"

        default_sel = self._selected_entities or available.get("defaults", [])

        if user_input is not None:
            selected = user_input.get(CONF_SEGMENT_ENTITIES) or []
            if not selected:
                errors["base"] = "entities_required"
            else:
                self._selected_entities = list(selected)
                new_segments = self._save_item()
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_create_entry(title="", data={CONF_SEGMENTS: new_segments})

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_ENTITIES, default=default_sel): selector.SelectSelector(
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
            if self._situation_id:
                status = await client.get_status_for_record(self._situation_id)
            else:
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

    def _save_item(self) -> list[dict]:
        """Return updated segments list (supports add + edit)."""
        segments = list(self.entry.options.get(CONF_SEGMENTS, [])) or []
        segments = self._migrate_segments(segments)

        # Edit: replace existing segment
        if self._editing_item_id:
            for i, seg in enumerate(segments):
                if seg.get(CONF_SEGMENT_ID) == self._editing_item_id:
                    segments[i] = self._build_item(seg_id=self._editing_item_id)
                    break
            else:
                # fallback: add if not found
                segments.append(self._build_item(seg_id=self._new_id(segments)))
        else:
            segments.append(self._build_item(seg_id=self._new_id(segments)))

        # Clear edit flag
        self._editing_item_id = None
        return segments

    def _build_item(self, seg_id: str) -> dict:
        if self._adding_type == TYPE_SITUATION:
            return {
                CONF_ITEM_TYPE: TYPE_SITUATION,
                CONF_SEGMENT_ID: seg_id,
                CONF_SEGMENT_NAME: self._segment_name,
                CONF_SITUATION_ID: self._situation_id,
                # keep legacy query for name fallback
                CONF_SEGMENT_QUERY: self._segment_query or self._segment_name,
                CONF_SEGMENT_ENTITIES: self._selected_entities,
            }

        return {
            CONF_ITEM_TYPE: TYPE_WEATHER,
            CONF_SEGMENT_ID: seg_id,
            CONF_SEGMENT_NAME: self._weather_site_name,
            CONF_SITE_ID: self._weather_site_id,
            CONF_SITE_NAME: self._weather_site_name,
            CONF_SEGMENT_ENTITIES: self._selected_entities,
        }

    @staticmethod
    def _new_id(segments: list[dict]) -> str:
        """Stable incremental item ids."""
        max_n = 0
        for s in segments:
            sid = s.get(CONF_SEGMENT_ID) or ""
            m = re.match(r"item_(\d+)$", sid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"item_{max_n + 1}"

    @staticmethod
    def _migrate_segments(segments: list[dict]) -> list[dict]:
        """Migration: set missing type to situation."""
        for seg in segments:
            if CONF_ITEM_TYPE not in seg:
                seg[CONF_ITEM_TYPE] = TYPE_SITUATION
        return segments

    def _format_segment_summary(self) -> str:
        segments = list(self.entry.options.get(CONF_SEGMENTS, [])) or []
        segments = self._migrate_segments(segments)

        if not segments:
            return "Ingen oppføringer lagt til."

        lines = []
        for seg in segments:
            t = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION
            name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SEGMENT_QUERY) or seg.get(CONF_SITE_NAME) or "Ukjent"
            entities = seg.get(CONF_SEGMENT_ENTITIES) or []
            prefix = "Veistykke" if t == TYPE_SITUATION else "Målested"
            lines.append(f"- {prefix}: {name} ({len(entities)} entiteter)")
        return "\\n".join(lines)
