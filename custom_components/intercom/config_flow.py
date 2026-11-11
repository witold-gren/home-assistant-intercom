"""Set up the intercom: the rooms are found by themselves, then adjusted in the options."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, selector
import voluptuous as vol

from .const import (
    CONF_FILE_SPEAKERS,
    CONF_KEEP_MINUTES,
    CONF_LANGUAGE,
    CONF_ROOMS,
    CONF_SPEAKERS,
    CONF_TTS_ENGINE,
    CONF_VOLUME,
    DEFAULT_KEEP_MINUTES,
    DOMAIN,
)
from .rooms import SPEAKER_DOMAINS, suggested_speakers

CONF_AREA = "area"
CONF_REMOVE = "remove"


def found_rooms(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Every area with a speaker, with its speakers in the suggested order."""
    rooms: dict[str, dict[str, Any]] = {}
    for area in ar.async_get(hass).async_list_areas():
        speakers = suggested_speakers(hass, area.id)
        if speakers:
            rooms[area.id] = {CONF_SPEAKERS: speakers, CONF_FILE_SPEAKERS: []}
    return rooms


class IntercomConfigFlow(ConfigFlow, domain=DOMAIN):
    """One intercom for the house."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm; the rooms with a speaker are set up at once."""
        if user_input is not None:
            return self.async_create_entry(
                title="Intercom",
                data={},
                options={
                    CONF_ROOMS: found_rooms(self.hass),
                    CONF_KEEP_MINUTES: DEFAULT_KEEP_MINUTES,
                },
            )
        return self.async_show_form(
            step_id="user",
            description_placeholders={"rooms": str(len(found_rooms(self.hass)))},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IntercomOptionsFlow:
        """Rooms and settings."""
        return IntercomOptionsFlow()


class IntercomOptionsFlow(OptionsFlow):
    """Change a room, add one, or the settings."""

    def __init__(self) -> None:
        self._area: str | None = None

    def _rooms(self) -> dict[str, dict[str, Any]]:
        return dict(self.config_entry.options.get(CONF_ROOMS) or {})

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What to change."""
        return self.async_show_menu(step_id="init", menu_options=["room", "settings"])

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the room (any area, also one without a speaker yet)."""
        if user_input is not None:
            self._area = user_input[CONF_AREA]
            return await self.async_step_speakers()
        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema({vol.Required(CONF_AREA): selector.AreaSelector()}),
        )

    async def async_step_speakers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The room's speakers in the order they are tried."""
        assert self._area is not None
        rooms = self._rooms()
        if user_input is not None:
            if user_input.get(CONF_REMOVE) or not user_input.get(CONF_SPEAKERS):
                rooms.pop(self._area, None)
            else:
                speakers = list(user_input[CONF_SPEAKERS])
                room: dict[str, Any] = {
                    CONF_SPEAKERS: speakers,
                    CONF_FILE_SPEAKERS: [
                        s for s in user_input.get(CONF_FILE_SPEAKERS) or [] if s in speakers
                    ],
                }
                if user_input.get(CONF_VOLUME) is not None:
                    room[CONF_VOLUME] = user_input[CONF_VOLUME]
                rooms[self._area] = room
            return self._save(**{CONF_ROOMS: rooms})
        room = rooms.get(self._area) or {
            CONF_SPEAKERS: suggested_speakers(self.hass, self._area),
            CONF_FILE_SPEAKERS: [],
        }
        volume = room.get(CONF_VOLUME)
        schema: dict[Any, Any] = {
            vol.Optional(CONF_SPEAKERS, default=room[CONF_SPEAKERS]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(SPEAKER_DOMAINS), multiple=True)
            ),
            vol.Optional(
                CONF_FILE_SPEAKERS, default=room.get(CONF_FILE_SPEAKERS) or []
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Optional(
                CONF_VOLUME, description={"suggested_value": volume}
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            vol.Optional(CONF_REMOVE, default=False): selector.BooleanSelector(),
        }
        area = ar.async_get(self.hass).async_get_area(self._area)
        return self.async_show_form(
            step_id="speakers",
            data_schema=vol.Schema(schema),
            description_placeholders={"room": area.name if area else self._area},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The voice, its language and how long messages are kept."""
        options = self.config_entry.options
        if user_input is not None:
            return self._save(
                **{
                    CONF_TTS_ENGINE: user_input.get(CONF_TTS_ENGINE) or None,
                    CONF_LANGUAGE: user_input.get(CONF_LANGUAGE) or None,
                    CONF_KEEP_MINUTES: int(user_input[CONF_KEEP_MINUTES]),
                }
            )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TTS_ENGINE,
                    description={"suggested_value": options.get(CONF_TTS_ENGINE)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
                vol.Optional(
                    CONF_LANGUAGE,
                    description={"suggested_value": options.get(CONF_LANGUAGE)},
                ): selector.LanguageSelector(),
                vol.Required(
                    CONF_KEEP_MINUTES,
                    default=options.get(CONF_KEEP_MINUTES, DEFAULT_KEEP_MINUTES),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=1440, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)
