"""Vehicle render image for SkodaLink."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SkodaConfigEntry
from .coordinator import SkodaCoordinator
from .entity import SkodaEntity

PARALLEL_UPDATES = 0

DESCRIPTION = EntityDescription(key="render", translation_key="render")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the render image."""
    async_add_entities(
        SkodaImage(hass, coordinator)
        for coordinator in entry.runtime_data.coordinators.values()
        if coordinator.data.has("renderUrl")
    )


class SkodaImage(SkodaEntity, ImageEntity):
    """Render of the vehicle as shown in the MyŠkoda app."""

    def __init__(self, hass: HomeAssistant, coordinator: SkodaCoordinator) -> None:
        """Initialise the image."""
        SkodaEntity.__init__(self, coordinator, DESCRIPTION, ("renderUrl",))
        ImageEntity.__init__(self, hass)
        self._attr_image_url = coordinator.data.get("renderUrl")
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        url = self.data.get("renderUrl")
        if url and url != self._attr_image_url:
            self._attr_image_url = url
            self._attr_image_last_updated = dt_util.utcnow()
            self._cached_image = None
        super()._handle_coordinator_update()
