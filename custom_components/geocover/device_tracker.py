"""GPS tracker for Decathlon Geocover."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GeocoverConfigEntry
from .coordinator import GeocoverCoordinator
from .entity import GeocoverEntity, async_setup_bike_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeocoverConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Geocover tracker."""
    coordinator = entry.runtime_data
    async_setup_bike_entities(
        coordinator,
        async_add_entities,
        lambda bike_id: [GeocoverTracker(coordinator, bike_id)],
    )


class GeocoverTracker(GeocoverEntity, TrackerEntity):
    """Last GPS position reported by the bike."""

    _attr_name = None
    _attr_translation_key = "location"

    def __init__(self, coordinator: GeocoverCoordinator, bike_id: int) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator, bike_id, "location")

    @property
    def latitude(self) -> float | None:
        """Return the latitude."""
        location = self.bike_data.bike.last_location
        return location.lat if location else None

    @property
    def longitude(self) -> float | None:
        """Return the longitude."""
        location = self.bike_data.bike.last_location
        return location.lon if location else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the speed and fix time of the last position."""
        if (location := self.bike_data.bike.last_location) is None:
            return None
        return {
            "speed": location.speed,
            "fix_time": location.date.isoformat() if location.date else None,
        }
