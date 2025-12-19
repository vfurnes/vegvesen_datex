from __future__ import annotations

import re
from dataclasses import dataclass

import aiohttp

from defusedxml import ElementTree as DET

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import SITUATION_URL_DEFAULT


@dataclass
class DatexResult:
    status: str               # "åpen" | "stengt" | "restriksjon" | "ukjent"
    is_closed: bool
    message: str | None
    matched: bool
    source: str


class DatexClient:
    def __init__(self, hass, username: str, password: str, url: str = SITUATION_URL_DEFAULT) -> None:
        self._hass = hass
        self._username = username
        self._password = password
        self._url = url

    async def fetch_situation(self) -> bytes:
        session = async_get_clientsession(self._hass)
        async with session.get(
            self._url,
            auth=aiohttp.BasicAuth(self._username, self._password),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    @staticmethod
    def _flatten_text(xml_bytes: bytes) -> str:
        root = DET.fromstring(xml_bytes)
        txt = " ".join(t.strip() for t in root.itertext() if t and t.strip())
        return re.sub(r"\s+", " ", txt)

    async def get_status_for_query(self, query: str) -> DatexResult:
        xml_bytes = await self.fetch_situation()
        text = self._flatten_text(xml_bytes)
        low = text.lower()
        q = (query or "").strip().lower()

        matched = bool(q) and (q in low)

        closed_words = ("stengt", "closed", "stenging", "road closed", "bridge closed")
        restr_words = ("restriks", "restricted", "kolonne", "convoy", "høy", "high-sided", "fare for stengt", "wind")

        status = "ukjent"
        is_closed = False
        msg = None

        if matched:
            if any(w in low for w in closed_words):
                status = "stengt"
                is_closed = True
            elif any(w in low for w in restr_words):
                status = "restriksjon"
            else:
                status = "åpen"

            idx = low.find(q)
            if idx >= 0:
                start = max(0, idx - 120)
                end = min(len(text), idx + 180)
                msg = text[start:end].strip()

        return DatexResult(
            status=status,
            is_closed=is_closed,
            message=msg,
            matched=matched,
            source=self._url,
        )
