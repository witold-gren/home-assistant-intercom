"""Speaking in rooms: who plays it, and how."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intercom.const import DOMAIN

from .conftest import BEDROOM_SPEAKER, HOMEPOD, KITCHEN_SATELLITE, SATELLITE


async def announce(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call(
        DOMAIN, "announce", data, blocking=True, return_response=True
    )


async def test_text_goes_to_the_first_speaker_of_each_room(
    hass: HomeAssistant, house, calls, speech, intercom: MockConfigEntry
) -> None:
    result = await announce(
        hass, areas=[house["living"], house["kitchen"], house["bedroom"]], message="Dinner!"
    )
    assert [p["speaker"] for p in result["played"]] == [HOMEPOD, KITCHEN_SATELLITE, BEDROOM_SPEAKER]
    assert result["missing"] == []
    # The satellite announces the text itself
    assert calls["announce"][0].data == {"entity_id": KITCHEN_SATELLITE, "message": "Dinner!"}
    by_speaker = {c.data["entity_id"]: c.data for c in calls["play_media"]}
    # The HomePod gets the whole spoken message as a file of ours
    assert by_speaker[HOMEPOD]["media_content_id"].startswith("media-source://intercom/")
    assert by_speaker[HOMEPOD]["media_content_id"].endswith(".mp3")
    assert by_speaker[HOMEPOD]["announce"] is True
    # Another media player gets the text-to-speech stream
    assert (
        by_speaker[BEDROOM_SPEAKER]["media_content_id"] == "media-source://tts/test?message=Dinner!"
    )
    # The room's volume is set first, only where the room has one
    assert [c.data for c in calls["volume_set"]] == [{"entity_id": HOMEPOD, "volume_level": 0.4}]
    # The spoken file is kept in the intercom folder
    files = list(Path(hass.config.path("intercom")).iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"ID3 spoken"


async def test_a_speaker_that_is_down_hands_over_to_the_next(
    hass: HomeAssistant, house, calls, speech, intercom
) -> None:
    hass.states.async_set(HOMEPOD, "unavailable")
    result = await announce(hass, areas=house["living"], message="Hi")
    assert result["played"][0]["speaker"] == SATELLITE
    assert calls["play_media"] == []
    # Nothing was spoken to a file: no speaker that needs one plays it
    speech["audio"].assert_not_called()


async def test_rooms_without_a_speaker_are_missing(
    hass: HomeAssistant, house, calls, speech, intercom
) -> None:
    hass.states.async_set(KITCHEN_SATELLITE, "unknown")
    result = await announce(hass, areas=[house["kitchen"], house["hall"]], message="Hi")
    assert result == {"played": [], "missing": [house["kitchen"], house["hall"]]}


async def test_an_entity_stands_for_its_room(
    hass: HomeAssistant, house, calls, speech, intercom
) -> None:
    result = await announce(hass, areas=[SATELLITE, house["living"]], message="Hi")
    # The satellite is in the living room: the room plays once
    assert [p["area"] for p in result["played"]] == [house["living"]]


async def test_a_recording_plays_as_it_is(
    hass: HomeAssistant, house, calls, speech, intercom
) -> None:
    media = "media-source://media_source/local/message.wav"
    await announce(hass, areas=[house["living"], house["kitchen"]], media=media, volume=0.7)
    assert calls["announce"][0].data == {"entity_id": KITCHEN_SATELLITE, "media_id": media}
    assert calls["play_media"][0].data["media_content_id"] == media
    # A volume asked for wins over the room's
    assert calls["volume_set"][0].data["volume_level"] == 0.7
    speech["stream"].assert_not_called()


async def test_a_speaker_that_fails_leaves_its_room_missing(
    hass: HomeAssistant, house, speech, intercom
) -> None:
    async def broken(call):
        raise ValueError("decoder")

    hass.services.async_register("assist_satellite", "announce", broken)
    result = await announce(hass, areas=house["kitchen"], message="Hi")
    assert result == {"played": [], "missing": [house["kitchen"]]}


async def test_a_message_or_a_recording_is_needed(hass: HomeAssistant, house, intercom) -> None:
    with pytest.raises(ServiceValidationError):
        await announce(hass, areas=house["kitchen"], message="  ")
