DOMAIN = "vegvesen_datex"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_QUERY = "query"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SITE_ID = "site_id"
CONF_SITE_NAME = "site_name"
CONF_SITE_FILTER = "site_filter"
CONF_USE_EXISTING = "use_existing"

DEFAULT_SCAN_INTERVAL = 60

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
