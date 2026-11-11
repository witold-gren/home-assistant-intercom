"""Media source `media-source://intercom/<file>`: a message waiting to be played.

A speaker resolves it to a short-lived signed link to the integration's own view, so the messages
need neither the media folder nor an administrator.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MIME_TYPES

RECORDING_URL = "/api/intercom/recording/{name}"
# How long a speaker may take to start playing a message
LINK_VALID = timedelta(minutes=15)


async def async_get_media_source(hass: HomeAssistant) -> IntercomMediaSource:
    """The intercom's media source."""
    return IntercomMediaSource(hass)


class IntercomMediaSource(MediaSource):
    """Messages waiting to be played (not browsable)."""

    name = "Intercom"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """A signed link to the message."""
        name = item.identifier
        data = self.hass.data.get(DOMAIN)
        path = data.recordings.path(name) if data else None
        if path is None or not await self.hass.async_add_executor_job(path.is_file):
            raise Unresolvable(f"No intercom message {name}")
        extension = name.rsplit(".", 1)[-1]
        url = async_sign_path(self.hass, RECORDING_URL.format(name=name), LINK_VALID)
        return PlayMedia(url, MIME_TYPES.get(extension, "application/octet-stream"))

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Messages are played once and gone, so there is nothing to browse."""
        if item.identifier:
            raise BrowseError("Intercom messages cannot be browsed")
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title="Intercom",
            can_play=False,
            can_expand=False,
            children=[],
        )
