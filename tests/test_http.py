"""A browser sends a recording; a speaker fetches it through a signed link."""

from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path
import time

from homeassistant.components import media_source
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.intercom.const import DOMAIN
from custom_components.intercom.http import message_volume, recording_extension

from .conftest import KITCHEN_SATELLITE

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28


async def test_a_recording_is_kept_and_played(
    hass: HomeAssistant, house, calls, intercom, hass_client
) -> None:
    client = await hass_client()
    resp = await client.post(
        f"/api/intercom/message?areas={house['kitchen']},{house['hall']}",
        data=WAV,
        headers={"Content-Type": "audio/wav"},
    )
    assert resp.status == 200
    result = await resp.json()
    assert [p["speaker"] for p in result["played"]] == [KITCHEN_SATELLITE]
    assert result["missing"] == [house["hall"]]
    media = calls["announce"][0].data["media_id"]
    assert media.startswith("media-source://intercom/") and media.endswith(".wav")

    # The speaker resolves the message to a signed link and fetches the whole file
    played = await media_source.async_resolve_media(hass, media, None)
    assert played.mime_type == "audio/wav"
    assert "authSig=" in played.url
    unauthenticated = await hass_client(None)
    fetched = await unauthenticated.get(played.url)
    assert fetched.status == 200
    assert await fetched.read() == WAV


async def test_what_a_browser_may_send(hass: HomeAssistant, house, intercom, hass_client) -> None:
    client = await hass_client()
    url = f"/api/intercom/message?areas={house['kitchen']}"
    assert (await client.post(url, data=b"x", headers={"Content-Type": "text/plain"})).status == 415
    assert (await client.post(url, data=b"", headers={"Content-Type": "audio/wav"})).status == 400
    assert (
        await client.post("/api/intercom/message", data=WAV, headers={"Content-Type": "audio/wav"})
    ).status == 400
    # A recording is never served without a signature, nor by a name that is not ours
    unauthenticated = await hass_client(None)
    assert (
        await unauthenticated.get("/api/intercom/recording/20261111_120000_0123abcd.wav")
    ).status == 401
    assert (await client.get("/api/intercom/recording/..%2F..%2Fsecrets.yaml")).status in (400, 404)


def test_recording_types_and_volume() -> None:
    assert recording_extension("audio/webm;codecs=opus") == "webm"
    assert recording_extension("audio/mp4") == "m4a"
    assert recording_extension("video/mp4") is None
    assert message_volume("0.6") == 0.6
    assert message_volume("7") == 1.0
    assert message_volume("loud") is None
    assert message_volume(None) is None


async def test_old_messages_are_removed(hass: HomeAssistant, house, intercom) -> None:
    recordings = hass.data[DOMAIN].recordings
    old = await recordings.save(b"old", "wav")
    new = await recordings.save(b"new", "wav")
    folder = Path(hass.config.path("intercom"))
    hour_ago = time.time() - 3600
    os.utime(folder / old, (hour_ago, hour_ago))
    # Not ours: left alone
    (folder / "notes.txt").write_text("keep")
    assert await recordings.cleanup(dt_util.utcnow()) == 1
    assert sorted(p.name for p in folder.iterdir()) == sorted([new, "notes.txt"])
    # Kept 15 minutes by default
    assert recordings.keep == timedelta(minutes=15)


async def test_the_card_hears_the_rooms(
    hass: HomeAssistant, house, intercom, hass_ws_client
) -> None:
    hass.states.async_set(KITCHEN_SATELLITE, "unavailable")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "intercom/rooms"})
    rooms = {r["area"]: r for r in (await client.receive_json())["result"]["rooms"]}
    assert rooms[house["living"]] == {"area": house["living"], "name": "Living room", "ready": True}
    assert rooms[house["kitchen"]]["ready"] is False
    # The card is offered to every dashboard, its link versioned
    url = intercom.js.call_args[0][1]  # type: ignore[attr-defined]
    assert url.startswith("/intercom_static/intercom-card.js?v=")


async def test_a_long_recording_is_kept_whole(
    hass: HomeAssistant, house, calls, intercom, hass_client
) -> None:
    """A browser sends a recording in pieces: all of it is kept, not the first piece."""
    recording = WAV + bytes(range(256)) * 2000  # about 10 s of 24 kHz speech

    async def pieces():
        for start in range(0, len(recording), 16384):
            yield recording[start : start + 16384]

    client = await hass_client()
    resp = await client.post(
        f"/api/intercom/message?areas={house['kitchen']}",
        data=pieces(),
        headers={"Content-Type": "audio/wav"},
    )
    assert resp.status == 200
    media = calls["announce"][0].data["media_id"]
    stored = Path(hass.config.path("intercom")) / media.rsplit("/", 1)[1]
    assert stored.read_bytes() == recording
