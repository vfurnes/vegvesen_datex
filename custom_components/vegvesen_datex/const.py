from __future__ import annotations

DOMAIN = "vegvesen_datex"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

# Legacy / compatibility (older entries / config flows)
CONF_QUERY = "query"
CONF_SITE_FILTER = "site_filter"
CONF_KNOWN_STRETCH = "known_stretch"

# (previously ENTITY_PRESSURE / ENTITY_PRECIP_INTENSITY were draft stubs)

# Options storage
CONF_SEGMENTS = "segments"
CONF_ITEM_TYPE = "item_type"
TYPE_SITUATION = "situation"
TYPE_WEATHER = "weather"
TYPE_RADIUS = "radius"

CONF_SEGMENT_ID = "segment_id"
CONF_SEGMENT_NAME = "segment_name"
CONF_SEGMENT_QUERY = "segment_query"      # for situations
CONF_SITE_ID = "site_id"                  # for weather
CONF_SITE_NAME = "site_name"
CONF_RADIUS_ZONE = "radius_zone"
CONF_RADIUS_KM = "radius_km"
CONF_SEGMENT_ENTITIES = "segment_entities"

DEFAULT_SCAN_INTERVAL = 300  # seconds

# Entity keys
ENTITY_STATUS = "status"
ENTITY_MESSAGE = "message"
ENTITY_CLOSED = "closed"

ENTITY_TEMPERATURE = "temperature"
ENTITY_HUMIDITY = "humidity"
ENTITY_WIND_SPEED = "wind_speed"
ENTITY_WIND_GUST = "wind_gust"
ENTITY_WIND_DIRECTION = "wind_direction"

# Nedbør
ENTITY_PRECIPITATION_INTENSITY = "precipitation_intensity"

# Føreforhold
ENTITY_ROAD_SURFACE_CONDITION = "road_surface_condition"   # tekst-status (snow/wet/dry/…)
ENTITY_ROAD_SURFACE_TEMPERATURE = "road_surface_temperature"
ENTITY_ROAD_SURFACE_FRICTION = "road_surface_friction"
ENTITY_ROAD_SURFACE_WATER_FILM = "road_surface_water_film"
ENTITY_ROAD_SURFACE_ICE_LAYER = "road_surface_ice_layer"
ENTITY_ROAD_SURFACE_SNOW_DEPTH = "road_surface_snow_depth"

# Attributes
ATTR_MESSAGE = "message"
ATTR_MATCHED = "matched"
ATTR_SOURCE = "source"

ATTR_LAST_MEASURED = "sist_oppdatert"     # <-- NY (timeValue for målingen)
ATTR_PERIOD_START = "periode_start"       # <-- NY (kun når tilgjengelig)
ATTR_PERIOD_END = "periode_slutt"         # <-- NY (kun når tilgjengelig)

SITUATION_URL_DEFAULT = (
    "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetSituation/pullsnapshotdata"
)

WEATHER_SITE_TABLE_URL_DEFAULT = (
    "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetMeasurementWeatherSiteTable/pullsnapshotdata"
)

MEASURED_WEATHER_URL_DEFAULT = (
    "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetMeasuredWeatherData/pullsnapshotdata"
)


# UI helpers
DEFAULT_RADIUS_MARKERS = 10  # number of map markers per radius item
