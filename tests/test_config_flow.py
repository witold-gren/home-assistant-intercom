"""Setting up the intercom: the rooms are found, then adjusted."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intercom.config_flow import found_rooms
from custom_components.intercom.const import (
    CONF_FILE_SPEAKERS,
    CONF_KEEP_MINUTES,
    CONF_ROOMS,
    CONF_SPEAKERS,
    CONF_TTS_ENGINE,
    CONF_VOICE,
    CONF_VOLUME,
    DOMAIN,
)
from custom_components.intercom.rooms import (
    Room,
    pick_speaker,
    resolve_areas,
    rooms_from_options,
    suggested_file_speakers,
    suggested_speakers,
)

from .conftest import BEDROOM_SPEAKER, HOMEPOD, KITCHEN_SATELLITE, SATELLITE


async def test_the_rooms_with_a_speaker_are_found(hass: HomeAssistant, house, dependencies) -> None:
    with patch("custom_components.intercom.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["description_placeholders"] == {"rooms": "3"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    rooms = result["options"][CONF_ROOMS]
    # Satellites first, then media players; the hall has no speaker
    assert rooms[house["living"]][CONF_SPEAKERS] == [SATELLITE, HOMEPOD]
    assert rooms[house["kitchen"]][CONF_SPEAKERS] == [KITCHEN_SATELLITE]
    assert house["hall"] not in rooms
    assert result["options"][CONF_KEEP_MINUTES] == 15


async def test_one_intercom_only(hass: HomeAssistant, house, intercom) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_a_room_is_changed_added_and_removed(
    hass: HomeAssistant, house, calls, speech, intercom
) -> None:
    async def room(area: str, values: dict) -> dict:
        result = await hass.config_entries.options.async_init(intercom.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "room"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"area": area}
        )
        assert result["step_id"] == "speakers"
        return await hass.config_entries.options.async_configure(result["flow_id"], values)

    # The satellite first, no file, a volume
    await room(
        house["living"],
        {CONF_SPEAKERS: [SATELLITE, HOMEPOD], CONF_FILE_SPEAKERS: [HOMEPOD], CONF_VOLUME: 0.5},
    )
    living = intercom.options[CONF_ROOMS][house["living"]]
    assert living == {
        CONF_SPEAKERS: [SATELLITE, HOMEPOD],
        CONF_FILE_SPEAKERS: [HOMEPOD],
        CONF_VOLUME: 0.5,
    }
    # The running intercom follows at once
    await hass.async_block_till_done()
    assert hass.data[DOMAIN].settings.rooms[house["living"]].speakers == (SATELLITE, HOMEPOD)
    # A room without a speaker gets one; a room is removed
    await room(house["hall"], {CONF_SPEAKERS: [BEDROOM_SPEAKER], CONF_FILE_SPEAKERS: []})
    await room(house["kitchen"], {CONF_SPEAKERS: [KITCHEN_SATELLITE], "remove": True})
    rooms = intercom.options[CONF_ROOMS]
    assert rooms[house["hall"]][CONF_SPEAKERS] == [BEDROOM_SPEAKER]
    assert house["kitchen"] not in rooms


async def test_the_settings(hass: HomeAssistant, house, intercom) -> None:
    result = await hass.config_entries.options.async_init(intercom.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TTS_ENGINE: "tts.test_voice", CONF_KEEP_MINUTES: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    data = hass.data[DOMAIN]
    assert data.settings.tts_engine == "tts.test_voice"
    assert data.recordings.keep.total_seconds() == 3600
    # The rooms are kept
    assert house["living"] in intercom.options[CONF_ROOMS]


async def test_rooms_resolve_and_pick(hass: HomeAssistant, house) -> None:
    assert suggested_speakers(hass, house["hall"]) == []
    # An entity on a device stands for the device's area; a name for its area
    assert resolve_areas(hass, [HOMEPOD, "Kitchen", house["living"]]) == [
        house["living"],
        house["kitchen"],
    ]
    room = Room(house["living"], (HOMEPOD, SATELLITE))
    assert pick_speaker(hass, room) == HOMEPOD
    hass.states.async_set(HOMEPOD, "unavailable")
    assert pick_speaker(hass, room) == SATELLITE
    # Off: a HomePod given whole files is lost (Apple TV plays nothing on it), another player is not
    hass.states.async_set(HOMEPOD, "off")
    assert pick_speaker(hass, room) == HOMEPOD
    assert pick_speaker(
        hass, Room(house["living"], (HOMEPOD, SATELLITE), frozenset({HOMEPOD}))
    ) == (SATELLITE)
    # A file speaker that is not a speaker of the room is dropped
    rooms = rooms_from_options(
        {CONF_ROOMS: {"x": {CONF_SPEAKERS: [SATELLITE], CONF_FILE_SPEAKERS: [HOMEPOD]}}}
    )
    assert rooms["x"].file_speakers == frozenset()


async def test_suggested_speakers_leave_out_televisions_and_doubles(
    hass: HomeAssistant, house
) -> None:
    """A real living room: a satellite with its own player, a television, a HomePod."""
    config = MockConfigEntry(domain="test")
    config.add_to_hass(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    room = ar.async_get(hass).async_create("Lounge").id
    voice = devices.async_get_or_create(
        config_entry_id=config.entry_id, identifiers={("test", "voice")}, name="voice"
    )
    devices.async_update_device(voice.id, area_id=room)

    def add(domain: str, platform: str, name: str, **kwargs) -> str:
        entity = entities.async_get_or_create(
            domain, platform, name, suggested_object_id=name, **kwargs
        )
        if not kwargs.get("device_id"):
            entities.async_update_entity(entity.entity_id, area_id=room)
        return entity.entity_id

    satellite = add("assist_satellite", "esphome", "lounge_voice", device_id=voice.id)
    add("media_player", "esphome", "lounge_voice_player", device_id=voice.id)
    add("media_player", "webostv", "lounge_tv", original_device_class="tv")
    homepod = add("media_player", "apple_tv", "lounge_homepod")
    sonos = add("media_player", "sonos", "lounge_sonos")

    speakers = suggested_speakers(hass, room)
    assert speakers == [satellite, homepod, sonos]
    assert suggested_file_speakers(hass, speakers) == [homepod]
    assert found_rooms(hass)[room] == {CONF_SPEAKERS: speakers, CONF_FILE_SPEAKERS: [homepod]}


async def test_the_voice_of_the_engine(hass: HomeAssistant, house, intercom, calls, speech) -> None:
    offered = [
        {"value": "pl_PL-vision", "label": "Vision"},
        {"value": "pl_PL-jarvis", "label": "Jarvis"},
    ]
    with patch("custom_components.intercom.config_flow.voices", return_value=offered):
        result = await hass.config_entries.options.async_init(intercom.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "settings"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_TTS_ENGINE: "tts.test_voice", CONF_KEEP_MINUTES: 15}
        )
        # The engine offers voices: the next step chooses one
        assert result["step_id"] == "voice"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_VOICE: "pl_PL-vision"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.data[DOMAIN].settings.voice == "pl_PL-vision"

    # The typed message is spoken with that voice
    await hass.services.async_call(
        DOMAIN, "announce", {"areas": [house["bedroom"]], "message": "Obiad"}, blocking=True
    )
    assert speech["stream"].call_args.kwargs["options"] == {"voice": "pl_PL-vision"}


async def test_the_rooms_are_shown_with_their_speakers(
    hass: HomeAssistant, house, intercom
) -> None:
    result = await hass.config_entries.options.async_init(intercom.entry_id)
    rooms = result["description_placeholders"]["rooms"]
    assert "- **Living room**: living room homepod, living room voice" in rooms
    assert "- **Kitchen**: kitchen voice" in rooms
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "room"}
    )
    options = result["data_schema"].schema["area"].config["options"]
    labels = [o["label"] for o in options]
    # The rooms set up first, with their speakers; then the areas without a room
    assert labels[:3] == [
        "Bedroom: bedroom speaker",
        "Kitchen: kitchen voice",
        "Living room: living room homepod, living room voice",
    ]
    assert "Hall" in labels[3:]
