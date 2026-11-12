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
from homeassistant.util import language as language_util
import voluptuous as vol

from .const import (
    CONF_FILE_SPEAKERS,
    CONF_KEEP_MINUTES,
    CONF_LANGUAGE,
    CONF_ROOMS,
    CONF_SPEAKERS,
    CONF_TTS_ENGINE,
    CONF_VOICE,
    CONF_VOLUME,
    DEFAULT_KEEP_MINUTES,
    DOMAIN,
)
from .rooms import SPEAKER_DOMAINS, area_name, suggested_file_speakers, suggested_speakers

CONF_AREA = "area"
CONF_REMOVE = "remove"


def _speaker_names(hass: HomeAssistant, speakers: list[str]) -> str:
    names = []
    for speaker in speakers:
        state = hass.states.get(speaker)
        names.append(state.name if state else speaker)
    return ", ".join(names)


def rooms_summary(hass: HomeAssistant, rooms: dict[str, dict[str, Any]]) -> str:
    """The rooms and their speakers in order, one line each (markdown)."""
    lines = [
        f"- **{area_name(hass, area)}**: {_speaker_names(hass, room.get(CONF_SPEAKERS) or [])}"
        for area, room in sorted(rooms.items(), key=lambda item: area_name(hass, item[0]))
    ]
    return "\n".join(lines) or "-"


def voices(
    hass: HomeAssistant, engine: str | None, language: str
) -> tuple[str | None, list[selector.SelectOptionDict]]:
    """The voices an engine offers for a language, and the engine's own code of that language
    ("pl" -> "pl_PL" for Piper); no voices when it offers no choice."""
    from homeassistant.components import tts
    from homeassistant.components.tts.helper import get_engine_instance

    try:
        engine = engine or tts.async_default_engine(hass)
        instance = get_engine_instance(hass, engine) if engine else None
    except KeyError:  # text to speech is not set up
        return None, []
    get_voices = getattr(instance, "async_get_supported_voices", None)
    if get_voices is None:
        return None, []
    supported = list(getattr(instance, "supported_languages", None) or [])
    for candidate in [language, *language_util.matches(language, supported)]:
        if found := get_voices(candidate):
            return candidate, [
                selector.SelectOptionDict(value=voice.voice_id, label=voice.name) for voice in found
            ]
    return None, []


def found_rooms(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Every area with a speaker, with its speakers in the suggested order."""
    rooms: dict[str, dict[str, Any]] = {}
    for area in ar.async_get(hass).async_list_areas():
        speakers = suggested_speakers(hass, area.id)
        if speakers:
            rooms[area.id] = {
                CONF_SPEAKERS: speakers,
                CONF_FILE_SPEAKERS: suggested_file_speakers(hass, speakers),
            }
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
        self._settings: dict[str, Any] = {}

    def _rooms(self) -> dict[str, dict[str, Any]]:
        return dict(self.config_entry.options.get(CONF_ROOMS) or {})

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What to change; the rooms as they are set now."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["room", "settings"],
            description_placeholders={"rooms": rooms_summary(self.hass, self._rooms())},
        )

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the room: the rooms set up first, with their speakers, then the other areas."""
        if user_input is not None:
            self._area = user_input[CONF_AREA]
            return await self.async_step_speakers()
        rooms = self._rooms()
        by_name = lambda area: area_name(self.hass, area)  # noqa: E731
        speakers = {area: room.get(CONF_SPEAKERS) or [] for area, room in rooms.items()}
        options = [
            selector.SelectOptionDict(
                value=area, label=f"{by_name(area)}: {_speaker_names(self.hass, speakers[area])}"
            )
            for area in sorted(rooms, key=by_name)
        ] + [
            selector.SelectOptionDict(value=area.id, label=area.name)
            for area in sorted(ar.async_get(self.hass).async_list_areas(), key=lambda a: a.name)
            if area.id not in rooms
        ]
        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AREA): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.LIST
                        )
                    )
                }
            ),
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
        if (room := rooms.get(self._area)) is None:
            speakers = suggested_speakers(self.hass, self._area)
            room = {
                CONF_SPEAKERS: speakers,
                CONF_FILE_SPEAKERS: suggested_file_speakers(self.hass, speakers),
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
        """The engine and how long messages are kept; its voice comes next."""
        options = self.config_entry.options
        if user_input is not None:
            self._settings = {
                CONF_TTS_ENGINE: user_input.get(CONF_TTS_ENGINE) or None,
                CONF_KEEP_MINUTES: int(user_input[CONF_KEEP_MINUTES]),
            }
            return await self.async_step_voice()
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TTS_ENGINE,
                    description={"suggested_value": options.get(CONF_TTS_ENGINE)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
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

    async def async_step_voice(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The voice of the engine in the language of Home Assistant, when it offers more than one.
        The language goes with it, in the engine's own code."""
        language, offered = voices(
            self.hass, self._settings.get(CONF_TTS_ENGINE), self.hass.config.language
        )
        if user_input is not None or len(offered) < 2:
            voice = (user_input or {}).get(CONF_VOICE) or None
            if voice not in {v["value"] for v in offered}:
                voice = None
            return self._save(
                **self._settings, **{CONF_VOICE: voice, CONF_LANGUAGE: language if voice else None}
            )
        current = self.config_entry.options.get(CONF_VOICE)
        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_VOICE,
                        description={
                            "suggested_value": current
                            if current in {v["value"] for v in offered}
                            else None
                        },
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=offered, mode=selector.SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )
