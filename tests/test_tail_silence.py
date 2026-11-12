"""A whole-file speaker (HomePod) cut the end off: its messages get silence at their end."""

from __future__ import annotations

import io
from pathlib import Path
import wave

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intercom import api as intercom_api
from custom_components.intercom.storage import TAIL_SILENCE, with_tail_silence

from .conftest import BEDROOM_SPEAKER, HOMEPOD


def wav(frames: int, rate: int = 16000, width: int = 2, fill: bytes = b"\x10") -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(width)
        target.setframerate(rate)
        target.writeframes(fill * frames * width)
    return out.getvalue()


def frames_of(data: bytes) -> tuple[int, bytes]:
    with wave.open(io.BytesIO(data)) as source:
        count = source.getnframes()
        return count, source.readframes(count)


def test_silence_is_added_at_the_end() -> None:
    count, frames = frames_of(with_tail_silence(wav(1000)))
    assert count == 1000 + int(16000 * TAIL_SILENCE)
    # The message stays as it was, then silence
    assert frames[:2000] == b"\x10" * 2000
    assert set(frames[2000:]) == {0}
    # 8-bit WAV is unsigned: its silence is 0x80
    _, frames = frames_of(with_tail_silence(wav(10, width=1)))
    assert set(frames[10:]) == {0x80}
    # Not a PCM WAV: left as it is
    assert with_tail_silence(b"ID3 an mp3") is None


async def test_a_recording_plays_to_its_end_on_a_homepod(
    hass: HomeAssistant, house: dict[str, str], intercom: MockConfigEntry, calls, speech
) -> None:
    recording = wav(8000)
    result = await intercom_api.async_announce(
        hass, [house["living"], house["bedroom"]], audio=recording
    )
    assert {p["speaker"] for p in result["played"]} == {HOMEPOD, BEDROOM_SPEAKER}
    played = {c.data["entity_id"]: c.data["media_content_id"] for c in calls["play_media"]}
    folder = Path(hass.config.path("intercom"))

    def stored(media: str) -> bytes:
        return (folder / media.rsplit("/", 1)[1]).read_bytes()

    # The HomePod gets a copy with silence; the other speaker the recording as it came
    assert stored(played[BEDROOM_SPEAKER]) == recording
    assert frames_of(stored(played[HOMEPOD]))[0] == 8000 + int(16000 * TAIL_SILENCE)


async def test_spoken_wav_gets_silence_for_a_homepod(
    hass: HomeAssistant, house: dict[str, str], intercom: MockConfigEntry, calls, speech
) -> None:
    speech["audio"].return_value = ("wav", wav(4000))
    await intercom_api.async_announce(hass, [house["living"]], message="Obiad!")
    media = calls["play_media"][0].data["media_content_id"]
    data = (Path(hass.config.path("intercom")) / media.rsplit("/", 1)[1]).read_bytes()
    assert frames_of(data)[0] == 4000 + int(16000 * TAIL_SILENCE)
