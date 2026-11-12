"""HTTP: a browser sends a recorded message; a speaker fetches it.

- `POST /api/intercom/message?areas=<area>,<area>[&volume=0.5]`: the body is the recording
  (`audio/wav`, `audio/webm`, `audio/ogg`, `audio/mp4`, `audio/mpeg`). Any signed-in user may send
  one. The answer is the outcome, `{"played": [...], "missing": [...]}`.
- `GET /api/intercom/recording/<file>`: the message, through a signed link (see media_source).
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.exceptions import HomeAssistantError

from .announce import async_announce
from .const import DOMAIN, MAX_RECORDING_BYTES, MIME_TYPES, RECORDING_TYPES
from .storage import media_id

READ_CHUNK = 64 * 1024


def recording_extension(content_type: str) -> str | None:
    """The file extension of a recording's type, or None for one we do not take."""
    return RECORDING_TYPES.get(content_type.split(";", 1)[0].strip().lower())


def message_volume(value: str | None) -> float | None:
    """A volume asked for in the link, kept within 0-1."""
    try:
        return min(max(float(value), 0.0), 1.0) if value not in (None, "") else None
    except ValueError:
        return None


class IntercomMessageView(HomeAssistantView):
    """Take a recording from a browser and speak it in rooms."""

    url = "/api/intercom/message"
    name = "api:intercom:message"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Keep the recording and play it."""
        hass = request.app[KEY_HASS]
        data = hass.data.get(DOMAIN)
        if data is None:
            return self.json_message("Intercom is not set up", 503)
        areas = [a for a in request.query.get("areas", "").split(",") if a]
        if not areas:
            return self.json_message("Give the rooms: ?areas=<area>,<area>", 400)
        extension = recording_extension(request.content_type or "")
        if extension is None:
            return self.json_message(f"Unsupported recording type {request.content_type}", 415)
        if request.content_length and request.content_length > MAX_RECORDING_BYTES:
            return self.json_message("The recording is too long", 413)
        # All of it: read(n) gives only what has arrived so far, which cut every recording longer
        # than about 1.7 s
        body = bytearray()
        while chunk := await request.content.read(READ_CHUNK):
            body += chunk
            if len(body) > MAX_RECORDING_BYTES:
                return self.json_message("The recording is too long", 413)
        if not body:
            return self.json_message("The recording is empty", 400)
        name = await data.recordings.save(bytes(body), extension)
        try:
            result = await async_announce(
                hass,
                data.settings,
                data.recordings,
                areas,
                media=media_id(name),
                volume=message_volume(request.query.get("volume")),
            )
        except HomeAssistantError as err:
            return self.json_message(str(err), 400)
        return self.json(result)


class IntercomRecordingView(HomeAssistantView):
    """Serve a message to a speaker (through a signed link)."""

    url = "/api/intercom/recording/{name}"
    name = "api:intercom:recording"
    requires_auth = True

    async def get(self, request: web.Request, name: str) -> web.StreamResponse:
        """The whole file, with its length: a speaker that drops streams plays it."""
        hass = request.app[KEY_HASS]
        data = hass.data.get(DOMAIN)
        path = data.recordings.path(name) if data else None
        if path is None or not await hass.async_add_executor_job(path.is_file):
            return web.Response(status=404)
        extension = name.rsplit(".", 1)[-1]
        return web.FileResponse(
            path, headers={"Content-Type": MIME_TYPES.get(extension, "application/octet-stream")}
        )
