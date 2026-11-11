"""Constants of the Intercom integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "intercom"

# Options of the entry
CONF_ROOMS: Final = "rooms"
CONF_SPEAKERS: Final = "speakers"
CONF_FILE_SPEAKERS: Final = "file_speakers"
CONF_VOLUME: Final = "volume"
CONF_TTS_ENGINE: Final = "tts_engine"
CONF_LANGUAGE: Final = "language"
CONF_KEEP_MINUTES: Final = "keep_minutes"

DEFAULT_KEEP_MINUTES: Final = 15

# Service and its fields
SERVICE_ANNOUNCE: Final = "announce"
ATTR_AREAS: Final = "areas"
ATTR_MESSAGE: Final = "message"
ATTR_MEDIA: Final = "media"

# Where recordings and spoken messages are kept until they are played (in the config folder, not
# in www: they are served only through the integration's signed links)
STORAGE_DIR: Final = "intercom"

# A recording sent from a browser: the formats a phone's microphone gives
MAX_RECORDING_BYTES: Final = 5 * 1024 * 1024
RECORDING_TYPES: Final = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
}
MIME_TYPES: Final = {
    "wav": "audio/wav",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
}

# The card
CARD_URL: Final = "/intercom_static/intercom-card.js"
