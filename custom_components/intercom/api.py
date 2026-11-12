"""For other integrations, e.g. a voice assistant: announce through the intercom.

from custom_components.intercom import api as intercom

if intercom.is_set_up(hass):
    rooms = intercom.areas_in_text(hass, "Announcement to the kitchen: dinner!")
    await intercom.async_announce(hass, rooms or None, audio=wav, exclude=satellite)
"""

from __future__ import annotations

import re
from typing import Any
import unicodedata

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar

from .announce import async_announce as _announce
from .const import DOMAIN
from .rooms import resolve_areas
from .storage import media_id

# How much of a word must agree with a room's name: inflected forms differ at the end
# ("kuchnia" / "do kuchni", "salon" / "w salonie")
MIN_STEM = 4
FLEXIBLE_END = 2


def is_set_up(hass: HomeAssistant) -> bool:
    """Whether the intercom runs (it is installed and added)."""
    return hass.data.get(DOMAIN) is not None


def rooms(hass: HomeAssistant) -> list[str]:
    """The area ids of the intercom's rooms."""
    data = hass.data.get(DOMAIN)
    return list(data.settings.rooms) if data else []


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower().replace("ł", "l"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.findall(r"\w+", plain)


def _named(name_words: list[str], words: list[str]) -> bool:
    def stem(word: str) -> str:
        return word[: min(len(word), max(MIN_STEM, len(word) - FLEXIBLE_END))]

    return bool(name_words) and all(
        any(word.startswith(stem(name_word)) for word in words) for name_word in name_words
    )


def areas_in_text(hass: HomeAssistant, text: str) -> list[str]:
    """The intercom's rooms named in a sentence, by their area's name or aliases.

    Inflected forms count: "do kuchni" names "Kuchnia", "w pokoju Adama" names "Pokój Adama". When
    one named room's name holds another's ("Pokój" and "Pokój Adama"), only the longer one counts.
    """
    words = _words(text)
    registry = ar.async_get(hass)
    found: list[tuple[str, set[str]]] = []
    for area_id in rooms(hass):
        area = registry.async_get_area(area_id)
        if area is None:
            continue
        for name in [area.name, *area.aliases]:
            name_words = _words(name)
            if _named(name_words, words):
                found.append((area_id, set(name_words)))
                break
    # A room whose whole name is inside another named room's ("Pokój" in "Pokój Adama") is not
    # meant
    return [area_id for area_id, name in found if not any(name < other for _, other in found)]


async def async_announce(
    hass: HomeAssistant,
    areas: list[str] | None = None,
    *,
    message: str | None = None,
    audio: bytes | None = None,
    extension: str = "wav",
    exclude: str | None = None,
    volume: float | None = None,
) -> dict[str, Any] | None:
    """Speak `message`, or play `audio` (the bytes of a recording), in rooms.

    `areas`: area ids or entities in them; None means every room except the area of `exclude`
    (e.g. the voice satellite that heard the announcement). Returns the result of
    `intercom.announce` ({"played": [...], "missing": [...]}), or None when the intercom is not
    set up.
    """
    data = hass.data.get(DOMAIN)
    if data is None:
        return None
    if areas is None:
        here = set(resolve_areas(hass, exclude)) if exclude else set()
        areas = [area for area in data.settings.rooms if area not in here]
        if not areas:
            return {"played": [], "missing": []}
    media = None
    if audio:
        media = media_id(await data.recordings.save(audio, extension))
    return await _announce(
        hass,
        data.settings,
        data.recordings,
        areas,
        message=None if media else message,
        media=media,
        volume=volume,
    )
