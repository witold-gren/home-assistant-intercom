"""Recordings and spoken messages kept until they are played, then removed."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re
import secrets

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_DIR

# `YYYYMMDD_HHMMSS_<8 hex>.<ext>`: the only names served, so no path ever leaves the folder
NAME = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}\.(wav|webm|ogg|m4a|mp3|flac)$")


class Recordings:
    """The folder of messages waiting to be played."""

    def __init__(self, hass: HomeAssistant, keep_minutes: int) -> None:
        self.hass = hass
        self.folder = Path(hass.config.path(STORAGE_DIR))
        self.keep = timedelta(minutes=keep_minutes)

    def path(self, name: str) -> Path | None:
        """The file of a message, when the name is one of ours."""
        if not NAME.match(name):
            return None
        return self.folder / name

    async def save(self, data: bytes, extension: str) -> str:
        """Keep a message; returns its name."""
        name = f"{dt_util.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.{extension}"

        def write() -> None:
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / name).write_bytes(data)

        await self.hass.async_add_executor_job(write)
        return name

    async def cleanup(self, now: datetime | None = None) -> int:
        """Remove the messages older than the time they are kept; returns how many went."""
        limit = (now or dt_util.utcnow()).timestamp() - self.keep.total_seconds()

        def remove() -> int:
            if not self.folder.is_dir():
                return 0
            removed = 0
            for file in self.folder.iterdir():
                if NAME.match(file.name) and file.stat().st_mtime < limit:
                    file.unlink(missing_ok=True)
                    removed += 1
            return removed

        return await self.hass.async_add_executor_job(remove)


def media_id(name: str) -> str:
    """The media source id of a message: players resolve it to a signed link."""
    return f"media-source://{DOMAIN}/{name}"
