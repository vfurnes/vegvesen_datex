from __future__ import annotations

from typing import Any

import logging
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    CONF_SEGMENTS,
    CONF_ITEM_TYPE,
    TYPE_SITUATION,
    TYPE_WEATHER,
    TYPE_RADIUS,
    TYPE_TRAVEL_TIME,
    CONF_SEGMENT_ID,
    CONF_SEGMENT_NAME,
    CONF_SEGMENT_QUERY,
    CONF_SEGMENT_ENTITIES,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_SITE_FILTER,
    CONF_KNOWN_STRETCH,
    CONF_RADIUS_ZONE,
    CONF_RADIUS_KM,
    ENTITY_STATUS,
    ENTITY_MESSAGE,
    ENTITY_CLOSED,
    ENTITY_TEMPERATURE,
    ENTITY_DEW_POINT,
    ENTITY_HUMIDITY,
    ENTITY_WIND_SPEED,
    ENTITY_WIND_GUST,
    ENTITY_WIND_GUST_CURRENT,
    ENTITY_WIND_DIRECTION,
    ENTITY_PRECIPITATION_INTENSITY,
    ENTITY_ROAD_SURFACE_CONDITION,
    ENTITY_ROAD_SURFACE_TEMPERATURE,
    ENTITY_ROAD_SURFACE_FRICTION,
    ENTITY_ROAD_SURFACE_WATER_FILM,
    ENTITY_ROAD_SURFACE_ICE_LAYER,
    ENTITY_ROAD_SURFACE_SNOW_DEPTH,
    ENTITY_TRAVEL_TIME,
    ENTITY_FREE_FLOW_TRAVEL_TIME,
    ENTITY_TRAVEL_TIME_DELAY,
    ENTITY_FREE_FLOW_SPEED,
    ENTITY_TRAFFIC_STATUS,
    ENTITY_TRAVEL_TIME_TREND,
    ENTITY_TRAVEL_TIME_TYPE,
)

from .datex_client import DatexClient

_LOGGER = logging.getLogger(__name__)


class VegvesenDatexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2
    MINOR_VERSION = 0

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
                    data={CONF_USERNAME: username, CONF_PASSWORD: password, CONF_SCAN_INTERVAL: scan},
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

        self._adding_type: str | None = None
        self._editing_id: str | None = None

        self._segment_name: str = ""
        self._segment_query: str = ""

        self._site_filter: str = ""
        self._site_options: dict[str, str] = {}
        self._picked_site_id: str | None = None
        self._picked_site_name: str | None = None

        self._radius_zone: str = "zone.home"
        self._radius_km: int = 20

        self._selected_entities: list[str] = []

    async def async_step_init(self, user_input=None) -> FlowResult:
        summary = self._format_segment_summary()
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_situation", "add_weather", "add_travel_time", "add_radius", "edit_remove"],
            description_placeholders={"segment_summary": summary},
        )

    async def async_step_edit_remove(self, user_input=None) -> FlowResult:
        segments = list(self.entry.options.get(CONF_SEGMENTS, [])) or []
        if not segments:
            return self.async_abort(reason="no_items")

        opts = []
        for seg in segments:
            sid = seg.get(CONF_SEGMENT_ID)
            if not sid:
                continue
            t = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION
            name = seg.get(CONF_SEGMENT_NAME) or seg.get(CONF_SEGMENT_QUERY) or seg.get(CONF_SITE_NAME) or "Ukjent"
            prefix = {
                TYPE_SITUATION: "Veistykke",
                TYPE_RADIUS: "Nærområde",
                TYPE_TRAVEL_TIME: "Reisetid",
            }.get(t, "Målested")
            opts.append(selector.SelectOptionDict(value=sid, label=f"{prefix}: {name}"))

        schema = vol.Schema(
            {
                vol.Required("item_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=opts, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="edit", label="Rediger"),
                            selector.SelectOptionDict(value="remove", label="Fjern"),
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
            removed = next((s for s in segments if s.get(CONF_SEGMENT_ID) == item_id), None)
            new_segments = [s for s in segments if s.get(CONF_SEGMENT_ID) != item_id]
            if removed:
                self._async_remove_item_devices(removed)
            return self.async_create_entry(title="", data={CONF_SEGMENTS: new_segments})

        # edit
        seg = next((s for s in segments if s.get(CONF_SEGMENT_ID) == item_id), None)
        if not seg:
            return self.async_abort(reason="no_items")

        self._editing_id = item_id
        self._adding_type = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION
        self._segment_name = seg.get(CONF_SEGMENT_NAME) or ""
        self._segment_query = seg.get(CONF_SEGMENT_QUERY) or ""
        self._selected_entities = list(seg.get(CONF_SEGMENT_ENTITIES) or [])

        if self._adding_type in (TYPE_WEATHER, TYPE_TRAVEL_TIME):
            self._picked_site_id = seg.get(CONF_SITE_ID)
            self._picked_site_name = seg.get(CONF_SITE_NAME) or ""
            return await self.async_step_site()

        if self._adding_type == TYPE_RADIUS:
            self._radius_zone = seg.get(CONF_RADIUS_ZONE) or "zone.home"
            self._radius_km = int(seg.get(CONF_RADIUS_KM) or 20)
            return await self.async_step_add_radius()

        return await self.async_step_add_situation()

    async def async_step_add_situation(self, user_input=None) -> FlowResult:
        self._adding_type = TYPE_SITUATION
        errors: dict[str, str] = {}

        if user_input is not None:
            known = user_input.get(CONF_KNOWN_STRETCH)
            self._segment_query = (user_input.get(CONF_SEGMENT_QUERY) or "").strip()
            self._segment_name = (user_input.get(CONF_SEGMENT_NAME) or "").strip()

            if known and not self._segment_query:
                kdata = (self.hass.data.get(DOMAIN, {}).get("_known_stretches") or {}).get(known) or {}
                t1 = (kdata.get("token1") or "").strip()
                t2 = (kdata.get("token2") or "").strip()
                self._segment_query = f"{t1} {t2}".strip()

            if not self._segment_query:
                errors["base"] = "query_required"
            else:
                return await self.async_step_entities()

        schema = vol.Schema(
            {
                vol.Optional(CONF_KNOWN_STRETCH): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._known_stretch_options(),
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_SEGMENT_QUERY, default=self._segment_query): str,
                vol.Optional(CONF_SEGMENT_NAME, default=self._segment_name): str,
            }
        )
        return self.async_show_form(step_id="add_situation", data_schema=schema, errors=errors)

    async def async_step_add_weather(self, user_input=None) -> FlowResult:
        self._adding_type = TYPE_WEATHER
        return await self.async_step_site()

    async def async_step_add_travel_time(self, user_input=None) -> FlowResult:
        self._adding_type = TYPE_TRAVEL_TIME
        return await self.async_step_site()

    async def async_step_site(self, user_input=None) -> FlowResult:
        """Filter + pick a predefined location: a weather station or a travel-time route.

        Shared between TYPE_WEATHER and TYPE_TRAVEL_TIME - self._adding_type (set by
        the caller before entering this step) decides which DATEX table to query.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._site_filter = str(user_input.get(CONF_SITE_FILTER) or "").strip()

        try:
            client = DatexClient(self.hass, self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD])
            if self._adding_type == TYPE_TRAVEL_TIME:
                sites = await client.list_travel_time_locations(self._site_filter)
            else:
                sites = await client.list_sites(self._site_filter)
            self._site_options = {sid: name for sid, name in sites}
        except Exception as err:
            _LOGGER.exception("vegvesen_datex: list_sites failed: %s", err)
            errors["base"] = "fetch_failed"
            self._site_options = {}

        schema_dict: dict = {
            # Label and hint text come from the "site_filter" translation key, not
            # from TextSelectorConfig - it has no label/placeholder fields, and
            # passing them raises voluptuous.MultipleInvalid ("extra keys not
            # allowed"), which HA's REST layer turns into a 400 on this step.
            vol.Optional(CONF_SITE_FILTER, default=self._site_filter): selector.TextSelector(),
        }

        if self._site_options:
            # Placeholder øverst for å hindre autovalg av første oppføring
            select_options = [
                selector.SelectOptionDict(value="", label="— Velg —"),
                *[
                    selector.SelectOptionDict(value=str(sid), label=str(name))
                    for sid, name in self._site_options.items()
                ],
            ]

            # Viktig: Optional her! Vi vil kunne trykke "Send inn" kun for å filtrere lista.
            schema_dict[vol.Optional(CONF_SITE_ID, default="")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=select_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            schema_dict[vol.Optional(CONF_SITE_ID)] = str
            errors["base"] = errors.get("base") or "no_sites"

        # Første visning, eller ingen site valgt: vis skjema (ev. etter filtrering)
        if user_input is None or CONF_SITE_ID not in user_input:
            return self.async_show_form(step_id="site", data_schema=vol.Schema(schema_dict), errors=errors)

        site_id = str(user_input.get(CONF_SITE_ID) or "").strip()

        # Hvis brukeren bare filtrerte (eller ikke valgte noe), vis skjema på nytt uten feilmelding
        if not site_id:
            return self.async_show_form(step_id="site", data_schema=vol.Schema(schema_dict), errors=errors)

        # Ekte valg -> gå videre
        self._picked_site_id = site_id
        self._picked_site_name = self._site_options.get(site_id) or site_id
        return await self.async_step_entities()

    async def async_step_add_radius(self, user_input=None) -> FlowResult:
        self._adding_type = TYPE_RADIUS
        errors: dict[str, str] = {}

        if user_input is not None:
            self._segment_name = (user_input.get(CONF_SEGMENT_NAME) or "").strip()
            self._radius_zone = (user_input.get(CONF_RADIUS_ZONE) or "zone.home").strip()
            try:
                self._radius_km = int(user_input.get(CONF_RADIUS_KM))
            except Exception:
                self._radius_km = 0

            if self._radius_km <= 0:
                errors["base"] = "radius_required"
            else:
                if not self._segment_name:
                    self._segment_name = f"Nærområde ({self._radius_km} km)"
                return await self.async_step_entities()

        schema = vol.Schema(
            {
                vol.Optional(CONF_SEGMENT_NAME, default=self._segment_name): str,
                vol.Optional(CONF_RADIUS_ZONE, default=self._radius_zone): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["zone"])
                ),
                vol.Required(CONF_RADIUS_KM, default=self._radius_km or 20): int,
            }
        )
        return self.async_show_form(step_id="add_radius", data_schema=schema, errors=errors)

    async def async_step_entities(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        available = self._available_entities()
        defaults = self._selected_entities or available["defaults"]
        if user_input is not None:
            sel = list(user_input.get(CONF_SEGMENT_ENTITIES) or [])
            if not sel:
                errors["base"] = "entities_required"
            else:
                self._selected_entities = sel
                segments = self._save_item()
                return self.async_create_entry(title="", data={CONF_SEGMENTS: segments})

        schema = vol.Schema(
            {
                vol.Required(CONF_SEGMENT_ENTITIES, default=defaults): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=k, label=v) for k, v in available["options"].items()],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema, errors=errors)

    def _available_entities(self) -> dict[str, Any]:
        t = self._adding_type or TYPE_SITUATION
        if t == TYPE_WEATHER:
            options = {
                ENTITY_TEMPERATURE: "Temperatur (luft)",
                ENTITY_DEW_POINT: "Duggpunkt",
                ENTITY_HUMIDITY: "Luftfuktighet",
                ENTITY_WIND_SPEED: "Vindstyrke (leveres nesten ikke)",
                ENTITY_WIND_GUST: "Vindkast (maks siste 10 min)",
                ENTITY_WIND_GUST_CURRENT: "Vindkast nå",
                ENTITY_WIND_DIRECTION: "Vindretning (leveres ikke)",
                ENTITY_PRECIPITATION_INTENSITY: "Nedbørsintensitet (mm/h)",
                ENTITY_ROAD_SURFACE_CONDITION: "Føreforhold (tekst)",
                ENTITY_ROAD_SURFACE_TEMPERATURE: "Vegbanetemperatur",
                ENTITY_ROAD_SURFACE_FRICTION: "Friksjon",
                ENTITY_ROAD_SURFACE_WATER_FILM: "Vannfilm (m)",
                ENTITY_ROAD_SURFACE_ICE_LAYER: "Islag (m)",
                ENTITY_ROAD_SURFACE_SNOW_DEPTH: "Snødybde (m)",
            }
            # Vindstyrke og vindretning sto tidligere som standard, men NPRA har
            # sluttet å publisere dem: 0 stasjoner sender retning og 2 sender
            # styrke, av 467. Nye brukere fikk dermed tomme sensorer og manglet
            # vindkast, som er det eneste vindfeltet som faktisk leveres.
            defaults = [ENTITY_TEMPERATURE, ENTITY_HUMIDITY, ENTITY_WIND_GUST]
            return {"options": options, "defaults": defaults}

        if t == TYPE_TRAVEL_TIME:
            options = {
                ENTITY_TRAVEL_TIME: "Reisetid",
                ENTITY_TRAVEL_TIME_DELAY: "Forsinkelse (vs. fri flyt)",
                ENTITY_FREE_FLOW_TRAVEL_TIME: "Reisetid uten kø (fri flyt)",
                ENTITY_FREE_FLOW_SPEED: "Fri flyt-hastighet",
                ENTITY_TRAFFIC_STATUS: "Trafikkstatus",
                ENTITY_TRAVEL_TIME_TREND: "Trend",
                ENTITY_TRAVEL_TIME_TYPE: "Beregningstype",
            }
            defaults = [ENTITY_TRAVEL_TIME, ENTITY_TRAVEL_TIME_DELAY]
            return {"options": options, "defaults": defaults}

        # situation + radius
        options = {
            ENTITY_STATUS: "Status",
            ENTITY_MESSAGE: "Hendelse",
            ENTITY_CLOSED: "Stengt (problem)",
        }
        defaults = [ENTITY_STATUS, ENTITY_MESSAGE, ENTITY_CLOSED]
        return {"options": options, "defaults": defaults}

    def _save_item(self) -> list[dict]:
        segments = list(self.entry.options.get(CONF_SEGMENTS, [])) or []

        seg_id = self._editing_id or uuid.uuid4().hex[:8]
        item: dict = {
            CONF_SEGMENT_ID: seg_id,
            CONF_ITEM_TYPE: self._adding_type or TYPE_SITUATION,
            CONF_SEGMENT_NAME: self._segment_name,
            CONF_SEGMENT_ENTITIES: list(self._selected_entities or []),
        }

        if (self._adding_type in (TYPE_WEATHER, TYPE_TRAVEL_TIME)) and (not self._segment_name):
            # Bruk stasjonens/strekningens navn som segment-navn hvis ikke brukeren har satt eget
            self._segment_name = self._picked_site_name or self._picked_site_id or "DATEX"
            item[CONF_SEGMENT_NAME] = self._segment_name

        if self._adding_type in (TYPE_WEATHER, TYPE_TRAVEL_TIME):
            item[CONF_SITE_ID] = self._picked_site_id
            item[CONF_SITE_NAME] = self._picked_site_name or self._picked_site_id
        elif self._adding_type == TYPE_RADIUS:
            item[CONF_RADIUS_ZONE] = self._radius_zone
            item[CONF_RADIUS_KM] = int(self._radius_km)
        else:
            item[CONF_SEGMENT_QUERY] = self._segment_query

        # replace or append
        new_segments = []
        replaced = False
        for s in segments:
            if s.get(CONF_SEGMENT_ID) == seg_id:
                new_segments.append(item)
                replaced = True
            else:
                new_segments.append(s)
        if not replaced:
            new_segments.append(item)

        self._editing_id = None
        return new_segments

    def _async_remove_item_devices(self, seg: dict) -> None:
        """Drop the device(s) for a removed item so its entities disappear too.

        Saving new options reloads the config entry, which stops *creating*
        entities for a removed item - but Home Assistant doesn't purge the
        registry on its own, so the device and its entities would otherwise
        stay behind forever as unavailable ghosts (the same registry-orphan
        problem geo_location.py already guards against for individual incident
        markers). Removing the device cascades to remove every entity on it.
        """
        item_type = seg.get(CONF_ITEM_TYPE) or TYPE_SITUATION
        seg_id = seg.get(CONF_SEGMENT_ID)

        if item_type == TYPE_WEATHER:
            keys = [f"weather_site_{seg.get(CONF_SITE_ID)}"]
        elif item_type == TYPE_TRAVEL_TIME:
            keys = [f"travel_time_{seg.get(CONF_SITE_ID)}"]
        elif item_type == TYPE_RADIUS:
            # Status/message/binary sensors live on "situation_<id>";
            # geo_location incident markers live on their own "radius_<id>" device.
            keys = [f"situation_{seg_id}", f"radius_{seg_id}"]
        else:
            keys = [f"situation_{seg_id}"]

        registry = dr.async_get(self.hass)
        for key in keys:
            device = registry.async_get_device(identifiers={(DOMAIN, key)})
            if device:
                registry.async_remove_device(device.id)

    def _known_stretch_options(self) -> list[selector.SelectOptionDict]:
        data = (self.hass.data.get(DOMAIN, {}).get("_known_stretches") or {})
        return [
            selector.SelectOptionDict(value=k, label=(v.get("label") or k))
            for k, v in sorted(data.items(), key=lambda kv: (kv[1].get("label", "").lower(), kv[0]))
        ]

    def _format_segment_summary(self) -> str:
        segs = list(self.entry.options.get(CONF_SEGMENTS, [])) or []
        if not segs:
            return "Ingen valgt ennå."
        parts = []
        for s in segs[:8]:
            t = s.get(CONF_ITEM_TYPE) or TYPE_SITUATION
            name = s.get(CONF_SEGMENT_NAME) or s.get(CONF_SEGMENT_QUERY) or s.get(CONF_SITE_NAME) or "Ukjent"
            parts.append(f"{t}: {name}")
        extra = "" if len(segs) <= 8 else f" (+{len(segs)-8} flere)"
        return " | ".join(parts) + extra
