from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

import requests

from .config import Config

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelayMapping:
    profile_token: str
    path: str
    upstream_uri: str


class RtspRelayRegistry:
    """Registers on-demand, stream-copy paths in the MediaMTX control API."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._mappings: dict[str, RelayMapping] = {}
        self._lock = threading.Lock()

    @staticmethod
    def path_for(profile_token: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", profile_token).strip("-.") or "profile"
        digest = hashlib.sha256(profile_token.encode()).hexdigest()[:8]
        return f"profile-{safe[:80]}-{digest}"

    def public_uri(self, path: str) -> str:
        return f"rtsp://{self.config.rtsp_advertised_host}:{self.config.rtsp_port}/{path}"

    def authenticated_upstream(self, uri: str) -> str:
        parsed = urlsplit(uri)
        host = parsed.hostname or self.config.camera_host
        port = f":{parsed.port}" if parsed.port else ""
        user = quote(self.config.camera_rtsp_username, safe="")
        password = quote(self.config.camera_rtsp_password, safe="")
        return urlunsplit((parsed.scheme, f"{user}:{password}@{host}{port}", parsed.path, parsed.query, parsed.fragment))

    def register(self, profile_token: str, upstream_uri: str) -> RelayMapping:
        path = self.path_for(profile_token)
        mapping = RelayMapping(profile_token, path, upstream_uri)
        with self._lock:
            previous = self._mappings.get(profile_token)
            if previous == mapping:
                return mapping
            payload = {
                "source": self.authenticated_upstream(upstream_uri),
                "sourceOnDemand": True,
                "sourceOnDemandCloseAfter": "10s",
                "rtspTransport": "tcp",
            }
            encoded_path = quote(path, safe="")
            add = requests.post(
                f"{self.config.rtsp_control_url}/v3/config/paths/add/{encoded_path}",
                json=payload,
                timeout=5,
                auth=(self.config.rtsp_control_username, self.config.rtsp_control_password),
            )
            if add.status_code in {400, 409}:
                add = requests.patch(
                    f"{self.config.rtsp_control_url}/v3/config/paths/patch/{encoded_path}",
                    json=payload,
                    timeout=5,
                    auth=(self.config.rtsp_control_username, self.config.rtsp_control_password),
                )
            add.raise_for_status()
            self._mappings[profile_token] = mapping
        LOGGER.info("Registered RTSP relay %s -> %s", profile_token, _safe_uri(upstream_uri))
        LOGGER.info("Returned RTSP URI to Protect: %s", self.public_uri(path))
        return mapping

    def health(self) -> dict[str, object]:
        try:
            response = requests.get(
                f"{self.config.rtsp_control_url}/v3/paths/list",
                timeout=2,
                auth=(self.config.rtsp_control_username, self.config.rtsp_control_password),
            )
            response.raise_for_status()
            items = response.json().get("items", [])
            active = sum(len(item.get("readers") or []) for item in items)
            running = True
        except (requests.RequestException, ValueError):
            active, running = 0, False
        return {
            "running": running,
            "port": self.config.rtsp_port,
            "profiles": len(self._mappings),
            "activeClients": active,
        }


def _safe_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    host = parsed.hostname or "unknown"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, parsed.query, parsed.fragment))
