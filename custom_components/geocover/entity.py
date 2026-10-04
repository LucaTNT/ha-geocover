"""Base entity for Decathlon Geocover."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GeocoverBikeData, GeocoverCoordinator


class GeocoverEntity(CoordinatorEntity[GeocoverCoordinator]):
    """An entity belonging to one bike."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GeocoverCoordinator, bike_id: int, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.bike_id = bike_id
        self._attr_unique_id = f"{bike_id}_{key}"
        bike = coordinator.data[bike_id].bike
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(bike_id))},
            name=bike.name,
            manufacturer=(bike.manufacturer or "decathlon").title(),
            model_id=bike.article_number,
            serial_number=bike.frame_number,
        )

    @property
    def bike_data(self) -> GeocoverBikeData:
        """Current data for this bike."""
        return self.coordinator.data[self.bike_id]

    @property
    def available(self) -> bool:
        """Unavailable when the bike disappeared from the account."""
        return super().available and self.bike_id in self.coordinator.data


def async_setup_bike_entities(
    coordinator: GeocoverCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[int], Iterable[Entity]],
) -> None:
    """Add entities for every bike, including bikes added to the account later."""
    known: set[int] = set()

    @callback
    def _async_add_new_bikes() -> None:
        new = [bike_id for bike_id in coordinator.data if bike_id not in known]
        if not new:
            return
        known.update(new)
        async_add_entities([entity for bike_id in new for entity in factory(bike_id)])

    _async_add_new_bikes()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_async_add_new_bikes))
