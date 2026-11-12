"""The intercom for other integrations: a voice assistant announces through it."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intercom import api as intercom_api
from custom_components.intercom.const import CONF_FILE_SPEAKERS, CONF_ROOMS, CONF_SPEAKERS

from .conftest import BEDROOM_SPEAKER, HOMEPOD, KITCHEN_SATELLITE, SATELLITE


async def test_not_set_up_answers_none(hass: HomeAssistant) -> None:
    assert not intercom_api.is_set_up(hass)
    assert intercom_api.rooms(hass) == []
    assert intercom_api.areas_in_text(hass, "to the kitchen") == []
    assert await intercom_api.async_announce(hass, message="Dinner!") is None


async def test_rooms_named_in_a_sentence(
    hass: HomeAssistant, house: dict[str, str], intercom: MockConfigEntry
) -> None:
    areas = ar.async_get(hass)
    areas.async_update(house["kitchen"], name="Kuchnia")
    areas.async_update(house["living"], name="Salon", aliases={"Pokój dzienny"})

    assert intercom_api.is_set_up(hass)
    assert intercom_api.areas_in_text(hass, "Komunikat do kuchni: obiad gotowy") == [
        house["kitchen"]
    ]
    # Inflected, and by an alias
    assert intercom_api.areas_in_text(hass, "Ogłoszenie w salonie") == [house["living"]]
    assert intercom_api.areas_in_text(hass, "intercom do pokoju dziennego") == [house["living"]]
    assert set(intercom_api.areas_in_text(hass, "do kuchni i do sypialni, the bedroom")) == {
        house["kitchen"],
        house["bedroom"],
    }
    # No room named: the caller decides (every room)
    assert intercom_api.areas_in_text(hass, "Komunikat: wychodzimy") == []


async def test_a_room_inside_a_longer_name_is_not_meant(
    hass: HomeAssistant, house: dict[str, str], dependencies
) -> None:
    areas = ar.async_get(hass)
    room = areas.async_create("Pokój")
    adam = areas.async_create("Pokój Adama")
    areas.async_update(house["kitchen"], name="Kuchnia")
    options = {
        CONF_ROOMS: {
            area: {CONF_SPEAKERS: [KITCHEN_SATELLITE], CONF_FILE_SPEAKERS: []}
            for area in (room.id, adam.id, house["kitchen"])
        }
    }
    entry = MockConfigEntry(domain="intercom", options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    assert intercom_api.areas_in_text(hass, "do pokoju Adama i do kuchni") == [
        adam.id,
        house["kitchen"],
    ]
    assert intercom_api.areas_in_text(hass, "do pokoju") == [room.id]


async def test_a_recording_everywhere_but_where_it_was_said(
    hass: HomeAssistant, house: dict[str, str], intercom: MockConfigEntry, calls, speech
) -> None:
    result = await intercom_api.async_announce(hass, audio=b"RIFF voice", exclude=SATELLITE)
    # The living room heard it: the kitchen and the bedroom play the very recording
    assert {p["area"] for p in result["played"]} == {house["kitchen"], house["bedroom"]}
    assert result["missing"] == []
    announced = calls["announce"][0].data
    assert announced["entity_id"] == KITCHEN_SATELLITE
    assert announced["media_id"].startswith("media-source://intercom/")
    played = calls["play_media"][0].data
    assert played["entity_id"] == BEDROOM_SPEAKER
    assert played["media_content_id"] == announced["media_id"]
    speech["audio"].assert_not_called()
    stored = list(Path(hass.config.path("intercom")).iterdir())
    assert [p.read_bytes() for p in stored] == [b"RIFF voice"]


async def test_a_text_to_named_rooms(
    hass: HomeAssistant, house: dict[str, str], intercom: MockConfigEntry, calls, speech
) -> None:
    result = await intercom_api.async_announce(
        hass, [house["living"]], message="Obiad!", exclude=SATELLITE
    )
    # Named rooms are kept even when the message comes from there
    assert [p["speaker"] for p in result["played"]] == [HOMEPOD]
    assert calls["play_media"][0].data["media_content_id"].startswith("media-source://intercom/")


async def test_only_the_room_it_came_from(
    hass: HomeAssistant, house: dict[str, str], dependencies
) -> None:
    options = {CONF_ROOMS: {house["living"]: {CONF_SPEAKERS: [SATELLITE], CONF_FILE_SPEAKERS: []}}}
    entry = MockConfigEntry(domain="intercom", options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert await intercom_api.async_announce(hass, message="Hi", exclude=SATELLITE) == {
        "played": [],
        "missing": [],
    }
