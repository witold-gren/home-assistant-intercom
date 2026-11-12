"""Intercom: voice messages to the rooms of the house.

The action `intercom.announce` speaks a text or plays a recording in rooms, each on the first of its
speakers that is up. A browser sends a recording to `/api/intercom/message`; the card
`custom:intercom-card` records it in any dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .announce import Settings, async_announce
from .const import (
    ATTR_AREAS,
    ATTR_MEDIA,
    ATTR_MESSAGE,
    CARD_URL,
    CONF_KEEP_MINUTES,
    CONF_LANGUAGE,
    CONF_TTS_ENGINE,
    CONF_VOICE,
    CONF_VOLUME,
    DEFAULT_KEEP_MINUTES,
    DOMAIN,
    SERVICE_ANNOUNCE,
)
from .http import IntercomMessageView, IntercomRecordingView
from .rooms import area_name, pick_speaker, rooms_from_options
from .storage import Recordings

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CLEANUP_EVERY = timedelta(minutes=1)

ANNOUNCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_AREAS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_MEDIA): cv.string,
        vol.Optional(CONF_VOLUME): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    }
)


@dataclass
class IntercomData:
    """What the running intercom keeps: its settings and its messages."""

    settings: Settings
    recordings: Recordings


def settings_from_entry(entry: ConfigEntry) -> Settings:
    """The settings of the entry's options."""
    options = entry.options
    return Settings(
        rooms=rooms_from_options(options),
        tts_engine=options.get(CONF_TTS_ENGINE) or None,
        language=options.get(CONF_LANGUAGE) or None,
        voice=options.get(CONF_VOICE) or None,
    )


def _data(hass: HomeAssistant) -> IntercomData:
    data = hass.data.get(DOMAIN)
    if data is None:
        raise ServiceValidationError("Intercom is not set up")
    return data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The action, the views, the command for the card and the card itself."""

    async def announce(call: ServiceCall) -> ServiceResponse:
        data = _data(hass)
        return await async_announce(
            hass,
            data.settings,
            data.recordings,
            call.data[ATTR_AREAS],
            message=call.data.get(ATTR_MESSAGE),
            media=call.data.get(ATTR_MEDIA),
            volume=call.data.get(CONF_VOLUME),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ANNOUNCE,
        announce,
        schema=ANNOUNCE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.http.register_view(IntercomMessageView())
    hass.http.register_view(IntercomRecordingView())
    websocket_api.async_register_command(hass, ws_rooms)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL.rsplit("/", 1)[0],
                str(Path(__file__).parent / "frontend"),
                cache_headers=False,
            )
        ]
    )
    # The version in the link makes a browser fetch the card again after an update
    version = await hass.async_add_executor_job(_version)
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start the intercom with the entry's rooms."""
    recordings = Recordings(hass, entry.options.get(CONF_KEEP_MINUTES, DEFAULT_KEEP_MINUTES))
    hass.data[DOMAIN] = IntercomData(settings_from_entry(entry), recordings)
    await recordings.cleanup()
    entry.async_on_unload(async_track_time_interval(hass, recordings.cleanup, CLEANUP_EVERY))
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    return True


def _version() -> str:
    manifest = Path(__file__).parent / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8")).get("version", "0")


async def _options_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    data = hass.data.get(DOMAIN)
    if data is None:
        return
    data.settings = settings_from_entry(entry)
    data.recordings.keep = timedelta(
        minutes=entry.options.get(CONF_KEEP_MINUTES, DEFAULT_KEEP_MINUTES)
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop the intercom; the action answers that it is not set up."""
    hass.data.pop(DOMAIN, None)
    return True


@websocket_api.websocket_command({vol.Required("type"): "intercom/rooms"})
@callback
def ws_rooms(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The rooms for a card: their names and whether a speaker of theirs is up."""
    data = hass.data.get(DOMAIN)
    rooms = data.settings.rooms if data else {}
    connection.send_result(
        msg["id"],
        {
            "rooms": [
                {
                    "area": area,
                    "name": area_name(hass, area),
                    "ready": pick_speaker(hass, room) is not None,
                }
                for area, room in rooms.items()
            ]
        },
    )
