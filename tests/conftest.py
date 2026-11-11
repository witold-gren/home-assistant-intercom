"""A house with rooms and speakers, and the intercom set up on it."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.intercom.const import (
    CONF_FILE_SPEAKERS,
    CONF_ROOMS,
    CONF_SPEAKERS,
    CONF_VOLUME,
    DOMAIN,
)

HOMEPOD = "media_player.living_room_homepod"
SATELLITE = "assist_satellite.living_room_voice"
KITCHEN_SATELLITE = "assist_satellite.kitchen_voice"
BEDROOM_SPEAKER = "media_player.bedroom_speaker"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components."""


@pytest.fixture
async def house(hass: HomeAssistant) -> dict[str, str]:
    """Three rooms: a HomePod and a satellite, a satellite, a speaker; one area without any."""
    areas = ar.async_get(hass)
    living = areas.async_create("Living room")
    kitchen = areas.async_create("Kitchen")
    bedroom = areas.async_create("Bedroom")
    hall = areas.async_create("Hall")
    config = MockConfigEntry(domain="test")
    config.add_to_hass(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    def add(entity_id: str, area: str, *, on_device: bool = False, state: str = "idle") -> None:
        domain, object_id = entity_id.split(".")
        device_id = None
        if on_device:
            device_id = devices.async_get_or_create(
                config_entry_id=config.entry_id, identifiers={("test", object_id)}, name=object_id
            ).id
            devices.async_update_device(device_id, area_id=area)
        entities.async_get_or_create(
            domain,
            "test",
            object_id,
            suggested_object_id=object_id,
            device_id=device_id,
        )
        if not on_device:
            entities.async_update_entity(entity_id, area_id=area)
        hass.states.async_set(entity_id, state, {"friendly_name": object_id.replace("_", " ")})

    add(HOMEPOD, living.id, on_device=True)
    add(SATELLITE, living.id)
    add(KITCHEN_SATELLITE, kitchen.id)
    add(BEDROOM_SPEAKER, bedroom.id)
    hass.states.async_set("tts.test_voice", "unknown")
    return {"living": living.id, "kitchen": kitchen.id, "bedroom": bedroom.id, "hall": hall.id}


def rooms_options(house: dict[str, str]) -> dict[str, Any]:
    """The rooms as the options keep them: the HomePod gets whole files."""
    return {
        CONF_ROOMS: {
            house["living"]: {
                CONF_SPEAKERS: [HOMEPOD, SATELLITE],
                CONF_FILE_SPEAKERS: [HOMEPOD],
                CONF_VOLUME: 0.4,
            },
            house["kitchen"]: {CONF_SPEAKERS: [KITCHEN_SATELLITE], CONF_FILE_SPEAKERS: []},
            house["bedroom"]: {CONF_SPEAKERS: [BEDROOM_SPEAKER], CONF_FILE_SPEAKERS: []},
        }
    }


@pytest.fixture
def calls(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    """The speaker actions, recorded."""
    return {
        "announce": async_mock_service(hass, "assist_satellite", "announce"),
        "play_media": async_mock_service(hass, "media_player", "play_media"),
        "volume_set": async_mock_service(hass, "media_player", "volume_set"),
    }


@pytest.fixture
def speech():
    """Text-to-speech without an engine: a stream id, and a whole file of mp3 bytes."""
    with (
        patch(
            "custom_components.intercom.announce.tts.generate_media_source_id",
            side_effect=lambda hass, message, **kw: f"media-source://tts/test?message={message}",
        ) as stream,
        patch(
            "custom_components.intercom.announce.tts.async_get_media_source_audio",
            return_value=("mp3", b"ID3 spoken"),
        ) as audio,
    ):
        yield {"stream": stream, "audio": audio}


@pytest.fixture
async def dependencies(hass: HomeAssistant, tmp_path):
    """What the intercom needs loaded; the card is not offered for real."""
    hass.config.config_dir = str(tmp_path)
    # Their packages are not installed for the tests; the intercom only needs them to be loaded
    hass.config.components.update({"frontend", "tts"})
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "media_source", {})
    with patch("custom_components.intercom.add_extra_js_url") as js:
        yield js


@pytest.fixture
async def intercom(hass: HomeAssistant, house: dict[str, str], dependencies) -> MockConfigEntry:
    """The intercom set up with the rooms of the house."""
    entry = MockConfigEntry(domain=DOMAIN, options=rooms_options(house))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.js = dependencies  # type: ignore[attr-defined]
    return entry
