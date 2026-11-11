"""Speak a message in rooms: text through text-to-speech, or a recording.

Each room plays it on the first of its speakers that is up. A voice satellite announces it; a media
player plays it as an announcement. A speaker that drops streamed speech (an Apple TV / HomePod)
gets the whole spoken message as a file instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components import tts
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .rooms import Room, area_name, pick_speaker, resolve_areas
from .storage import Recordings, media_id

_LOGGER = logging.getLogger(__name__)


@dataclass
class Settings:
    """What the entry sets for every message."""

    rooms: dict[str, Room]
    tts_engine: str | None = None
    language: str | None = None


def _tts_engine(hass: HomeAssistant, settings: Settings) -> str:
    engine = settings.tts_engine or next(iter(hass.states.async_entity_ids("tts")), None)
    if not engine:
        raise HomeAssistantError("No text-to-speech engine: add one, or choose it in Intercom")
    return engine


def _speaker_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and state.name:
        return state.name
    entry = er.async_get(hass).async_get(entity_id)
    return (entry.name or entry.original_name or entity_id) if entry else entity_id


async def _spoken_file(
    hass: HomeAssistant, settings: Settings, recordings: Recordings, message: str
) -> str:
    """The whole spoken message as a file of ours; returns its media id."""
    source = tts.generate_media_source_id(
        hass,
        message,
        engine=_tts_engine(hass, settings),
        language=settings.language or hass.config.language,
    )
    extension, data = await tts.async_get_media_source_audio(hass, source)
    return media_id(await recordings.save(data, extension))


async def _play(
    hass: HomeAssistant,
    speaker: str,
    *,
    message: str | None,
    media: str | None,
    volume: float | None,
) -> None:
    domain = speaker.split(".", 1)[0]
    if domain == "assist_satellite":
        data: dict[str, Any] = {"entity_id": speaker}
        if media:
            data["media_id"] = media
        else:
            data["message"] = message
        await hass.services.async_call("assist_satellite", "announce", data, blocking=True)
        return
    if volume is not None:
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {"entity_id": speaker, "volume_level": volume},
            blocking=True,
        )
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": speaker,
            "media_content_id": media,
            "media_content_type": "music",
            "announce": True,
        },
        blocking=True,
    )


async def async_announce(
    hass: HomeAssistant,
    settings: Settings,
    recordings: Recordings,
    targets: str | list[str],
    *,
    message: str | None = None,
    media: str | None = None,
    volume: float | None = None,
) -> dict[str, Any]:
    """Speak `message` (or play `media`) in the rooms of `targets` (areas, or entities in them).

    Returns `{"played": [{area, area_name, speaker, speaker_name}], "missing": [area]}`: a room is
    missing when it has no speaker that is up, or its speaker failed.
    """
    message = (message or "").strip() or None
    if not message and not media:
        raise ServiceValidationError("Give a message or a recording")
    areas = resolve_areas(hass, targets)
    if not areas:
        raise ServiceValidationError("Give at least one room")

    chosen: list[tuple[str, str, Room]] = []
    missing: list[str] = []
    for area in areas:
        room = settings.rooms.get(area)
        speaker = pick_speaker(hass, room) if room else None
        if speaker and room:
            chosen.append((area, speaker, room))
        else:
            missing.append(area)

    # Speech for the media players: one whole file, or the text-to-speech stream
    file_media: str | None = None
    stream_media: str | None = None
    if message and not media:
        if any(speaker in room.file_speakers for _, speaker, room in chosen):
            file_media = await _spoken_file(hass, settings, recordings, message)
        if any(
            speaker.startswith("media_player.") and speaker not in room.file_speakers
            for _, speaker, room in chosen
        ):
            stream_media = tts.generate_media_source_id(
                hass,
                message,
                engine=_tts_engine(hass, settings),
                language=settings.language or hass.config.language,
            )

    async def play(area: str, speaker: str, room: Room) -> tuple[str, str, Exception | None]:
        if media:
            item = media
        elif speaker.startswith("assist_satellite."):
            item = None
        else:
            item = file_media if speaker in room.file_speakers else stream_media
        try:
            await _play(
                hass,
                speaker,
                message=message,
                media=item,
                volume=volume if volume is not None else room.volume,
            )
        except (HomeAssistantError, ValueError) as err:
            return area, speaker, err
        return area, speaker, None

    played: list[dict[str, str]] = []
    for area, speaker, error in await asyncio.gather(*(play(*c) for c in chosen)):
        if error:
            _LOGGER.warning("Intercom: %s in %s failed: %s", speaker, area, error)
            missing.append(area)
            continue
        played.append(
            {
                "area": area,
                "area_name": area_name(hass, area),
                "speaker": speaker,
                "speaker_name": _speaker_name(hass, speaker),
            }
        )
    return {"played": played, "missing": missing}
