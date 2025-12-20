DOMAIN = "vegvesen_datex"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_QUERY = "query"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SITE_ID = "site_id"
CONF_SITE_NAME = "site_name"
CONF_SITE_FILTER = "site_filter"
CONF_USE_EXISTING = "use_existing"
CONF_SEGMENTS = "segments"
CONF_SEGMENT_ID = "segment_id"
CONF_SEGMENT_NAME = "segment_name"
CONF_SEGMENT_QUERY = "segment_query"
CONF_SEGMENT_ENTITIES = "segment_entities"
CONF_ADD_ANOTHER = "add_another"

DEFAULT_SCAN_INTERVAL = 60

ENTITY_STATUS = "status"
ENTITY_MESSAGE = "message"
ENTITY_CLOSED = "closed"
ENTITY_WIND_SPEED = "wind_speed"
ENTITY_WIND_DIRECTION = "wind_direction"

SITUATION_URL_DEFAULT = (
    "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetSituation/pullsnapshotdata"
)

WEATHER_SITE_TABLE_URL_DEFAULT = (
    "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetMeasurementWeatherSiteTable/pullsnapshotdata"
)
MEASURED_WEATHER_URL_DEFAULT = (
    "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetMeasuredWeatherData/pullsnapshotdata"
)

ATTR_MESSAGE = "message"
ATTR_MATCHED = "matched"
ATTR_SOURCE = "source"
