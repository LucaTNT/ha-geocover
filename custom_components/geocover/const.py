"""Constants for the Decathlon Geocover integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "geocover"

CONF_TOKENS: Final = "tokens"
CONF_REDIRECT_URL: Final = "redirect_url"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 5  # minutes
MIN_SCAN_INTERVAL: Final = 1  # minutes
MAX_SCAN_INTERVAL: Final = 1440  # minutes

# Rides only change when a ride ends, so they are fetched less often than the
# rest; a ride that just ended (ride_in_progress true -> false) is fetched at once.
RIDE_UPDATE_INTERVAL: Final = timedelta(minutes=30)
