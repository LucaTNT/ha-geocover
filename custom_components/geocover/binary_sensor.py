"""Binary sensors for Decathlon Geocover."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GeocoverConfigEntry
from .coordinator import GeocoverBikeData, GeocoverCoordinator
from .entity import GeocoverEntity, async_setup_bike_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GeocoverBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Geocover binary sensor."""

    value_fn: Callable[[GeocoverBikeData], bool | None]


def _not(value: bool | None) -> bool | None:
    return None if value is None else not value


BINARY_SENSORS: tuple[GeocoverBinarySensorEntityDescription, ...] = (
    GeocoverBinarySensorEntityDescription(
        key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda d: d.bike.last_location.is_moving if d.bike.last_location else None,
    ),
    GeocoverBinarySensorEntityDescription(
        key="ride_in_progress",
        translation_key="ride_in_progress",
        value_fn=lambda d: d.bike.ride_in_progress,
    ),
    GeocoverBinarySensorEntityDescription(
        key="stolen",
        translation_key="stolen",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: d.bike.is_stolen,
    ),
    GeocoverBinarySensorEntityDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda d: d.charging,
    ),
    GeocoverBinarySensorEntityDescription(
        key="powered_on",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda d: d.state.powered_on if d.state else None,
    ),
    GeocoverBinarySensorEntityDescription(
        # LOCK device class: on means unlocked
        key="ecu_locked",
        translation_key="ecu_lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda d: _not(d.state.ecu_locked) if d.state else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeocoverConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Geocover binary sensors."""
    coordinator = entry.runtime_data
    async_setup_bike_entities(
        coordinator,
        async_add_entities,
        lambda bike_id: (
            GeocoverBinarySensor(coordinator, bike_id, description)
            for description in BINARY_SENSORS
        ),
    )


class GeocoverBinarySensor(GeocoverEntity, BinarySensorEntity):
    """A Geocover binary sensor."""

    entity_description: GeocoverBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: GeocoverCoordinator,
        bike_id: int,
        description: GeocoverBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, bike_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.bike_data)
