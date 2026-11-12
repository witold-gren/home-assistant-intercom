"""Rooms: the speakers of each area, in the order they are tried."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import CONF_FILE_SPEAKERS, CONF_ROOMS, CONF_SPEAKERS, CONF_VOLUME

# The kinds of entity that can speak in a room
SPEAKER_DOMAINS = ("media_player", "assist_satellite")


@dataclass(frozen=True)
class Room:
    """An area and its speakers: the first one that is up plays the message."""

    area_id: str
    speakers: tuple[str, ...]
    # Speakers given a whole file rather than a stream (an Apple TV / HomePod drops streamed speech)
    file_speakers: frozenset[str] = frozenset()
    # 0-1; None leaves the speaker's volume as it is
    volume: float | None = None


def rooms_from_options(options: Mapping[str, Any]) -> dict[str, Room]:
    """The rooms kept in the entry's options."""
    rooms: dict[str, Room] = {}
    for area_id, room in (options.get(CONF_ROOMS) or {}).items():
        speakers = tuple(room.get(CONF_SPEAKERS) or ())
        rooms[area_id] = Room(
            area_id=area_id,
            speakers=speakers,
            file_speakers=frozenset(room.get(CONF_FILE_SPEAKERS) or ()) & frozenset(speakers),
            volume=room.get(CONF_VOLUME),
        )
    return rooms


def _entity_area(entity: er.RegistryEntry, devices: dr.DeviceRegistry) -> str | None:
    if entity.area_id:
        return entity.area_id
    device = devices.async_get(entity.device_id) if entity.device_id else None
    return device.area_id if device else None


# Players of these integrations get a whole file: Apple TV's HomePods drop streamed speech
FILE_PLATFORMS = ("apple_tv",)


def suggested_speakers(hass: HomeAssistant, area_id: str) -> list[str]:
    """The speakers in an area: voice satellites first (made for announcements), then media players.

    Left out: televisions, and a satellite's own media player (the same speaker twice).
    """
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found = [
        entity
        for entity in entities.entities.values()
        if entity.domain in SPEAKER_DOMAINS
        and not entity.disabled
        and not entity.hidden
        and _entity_area(entity, devices) == area_id
    ]
    satellite_devices = {
        e.device_id for e in found if e.domain == "assist_satellite" and e.device_id
    }
    found = [
        e
        for e in found
        if e.domain == "assist_satellite"
        or (
            (e.device_class or e.original_device_class) != "tv"
            and not (e.device_id and e.device_id in satellite_devices)
        )
    ]
    found.sort(key=lambda e: (e.domain != "assist_satellite", e.entity_id))
    return [entity.entity_id for entity in found]


def suggested_file_speakers(hass: HomeAssistant, speakers: Iterable[str]) -> list[str]:
    """The speakers to give a whole file: Apple TV's (a HomePod)."""
    entities = er.async_get(hass)
    return [
        s
        for s in speakers
        if (e := entities.async_get(s)) is not None and e.platform in FILE_PLATFORMS
    ]


def resolve_areas(hass: HomeAssistant, targets: str | Iterable[str]) -> list[str]:
    """Area ids of the targets: an area id stays, an entity stands for its area; each area once."""
    if isinstance(targets, str):
        targets = [targets]
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    areas = ar.async_get(hass)
    resolved: list[str] = []
    for target in targets:
        area_id: str | None = target
        if "." in target:
            entity = entities.async_get(target)
            area_id = _entity_area(entity, devices) if entity else None
        elif areas.async_get_area(target) is None:
            # Maybe a name rather than an id
            area = areas.async_get_area_by_name(target)
            area_id = area.id if area else target
        if area_id and area_id not in resolved:
            resolved.append(area_id)
    return resolved


def speaker_is_up(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether a speaker answers: it exists and is neither unavailable nor unknown."""
    state = hass.states.get(entity_id)
    return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def pick_speaker(hass: HomeAssistant, room: Room) -> str | None:
    """The first speaker of a room that is up.

    A whole-file speaker that is off is not: Apple TV shows a HomePod it lost as off, and plays
    nothing on it without an error. Other players that are off (a Google speaker at rest) still
    play.
    """
    return next(
        (
            s
            for s in room.speakers
            if speaker_is_up(hass, s)
            and not (s in room.file_speakers and hass.states.is_state(s, STATE_OFF))
        ),
        None,
    )


def area_name(hass: HomeAssistant, area_id: str) -> str:
    """The name of an area, or its id when it is gone."""
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else area_id
