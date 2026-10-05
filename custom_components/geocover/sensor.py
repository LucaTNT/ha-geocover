"""Sensors for Decathlon Geocover."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfMass,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import GeocoverConfigEntry
from .coordinator import GeocoverBikeData, GeocoverCoordinator
from .entity import GeocoverEntity, async_setup_bike_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GeocoverSensorEntityDescription(SensorEntityDescription):
    """Describes a Geocover sensor."""

    value_fn: Callable[[GeocoverBikeData], StateType | datetime]
    attrs_fn: Callable[[GeocoverBikeData], dict[str, Any] | None] = lambda _: None


def _ride_attrs(data: GeocoverBikeData) -> dict[str, Any] | None:
    if (ride := data.latest_ride) is None:
        return None
    return {"start_time": ride.start_date, "end_time": ride.end_date}


SENSORS: tuple[GeocoverSensorEntityDescription, ...] = (
    GeocoverSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_percentage,
    ),
    GeocoverSensorEntityDescription(
        key="range",
        translation_key="range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.range_km,
    ),
    GeocoverSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda d: d.bike.odometer_km,
    ),
    GeocoverSensorEntityDescription(
        key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.bike.last_location.speed if d.bike.last_location else None,
    ),
    GeocoverSensorEntityDescription(
        key="tracker_battery",
        translation_key="tracker_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.health.gps_battery if d.health else None,
    ),
    GeocoverSensorEntityDescription(
        key="last_gps_fix",
        translation_key="last_gps_fix",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            (d.health.last_gps if d.health else None)
            or (d.bike.last_location.date if d.bike.last_location else None)
        ),
    ),
    GeocoverSensorEntityDescription(
        key="last_connection",
        translation_key="last_connection",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.health.last_connection if d.health else None,
    ),
    GeocoverSensorEntityDescription(
        key="last_ride_distance",
        translation_key="last_ride_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=lambda d: d.latest_ride.distance_km if d.latest_ride else None,
        attrs_fn=_ride_attrs,
    ),
    GeocoverSensorEntityDescription(
        key="last_ride_duration",
        translation_key="last_ride_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda d: d.latest_ride.active_time_s if d.latest_ride else None,
        attrs_fn=_ride_attrs,
    ),
    GeocoverSensorEntityDescription(
        key="last_ride_average_speed",
        translation_key="last_ride_average_speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: d.latest_ride.avg_speed if d.latest_ride else None,
        attrs_fn=_ride_attrs,
    ),
    GeocoverSensorEntityDescription(
        # Unreliable: a mostly-downhill ride (136 -> 60 m) came back as +401/-305 m
        key="last_ride_elevation_up",
        translation_key="last_ride_elevation_up",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.latest_ride.elevation_up if d.latest_ride else None,
        attrs_fn=_ride_attrs,
    ),
    GeocoverSensorEntityDescription(
        # CO₂ saved versus driving, in grams (checked against the app: 3984 -> ~4 kg)
        key="last_ride_co2",
        translation_key="last_ride_co2",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        suggested_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=2,
        value_fn=lambda d: d.latest_ride.co2 if d.latest_ride else None,
        attrs_fn=_ride_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeocoverConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Geocover sensors."""
    coordinator = entry.runtime_data
    async_setup_bike_entities(
        coordinator,
        async_add_entities,
        lambda bike_id: (
            GeocoverSensor(coordinator, bike_id, description) for description in SENSORS
        ),
    )


class GeocoverSensor(GeocoverEntity, SensorEntity):
    """A Geocover sensor."""

    entity_description: GeocoverSensorEntityDescription

    def __init__(
        self,
        coordinator: GeocoverCoordinator,
        bike_id: int,
        description: GeocoverSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, bike_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        return self.entity_description.value_fn(self.bike_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attrs_fn(self.bike_data)
