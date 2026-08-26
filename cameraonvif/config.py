from __future__ import annotations
import os
from dataclasses import dataclass

def csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, default).split(",") if x.strip())

def bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}

def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

@dataclass(frozen=True)
class Config:
    onvif_bind_host: str; onvif_port: int; onvif_advertised_host: str
    onvif_username: str; onvif_password: str
    camera_host: str; camera_port: int; camera_username: str; camera_password: str
    camera_media_url: str
    smtp_host: str; smtp_port: int; smtp_username: str | None; smtp_password: str | None
    match_subject_patterns: tuple[str, ...]; match_body_patterns: tuple[str, ...]
    ignore_subject_patterns: tuple[str, ...]
    motion_duration: float; motion_cooldown: float; subscription_ttl: float
    auth_clock_tolerance: float; verify_upstream_tls: bool
    enable_debug_endpoints: bool; stable_uuid: str

    @property
    def base_url(self) -> str:
        return f"http://{self.onvif_advertised_host}:{self.onvif_port}"

    @classmethod
    def from_env(cls) -> "Config":
        smtp_user, smtp_password = os.getenv("SMTP_USERNAME") or None, os.getenv("SMTP_PASSWORD") or None
        if bool(smtp_user) != bool(smtp_password):
            raise ValueError("Set both SMTP_USERNAME and SMTP_PASSWORD, or neither")
        host, port = required("CAMERA_ONVIF_HOST"), int(os.getenv("CAMERA_ONVIF_PORT", "80"))
        scheme = os.getenv("CAMERA_ONVIF_SCHEME", "http")
        return cls(
            os.getenv("ONVIF_BIND_HOST", "0.0.0.0"), int(os.getenv("ONVIF_PORT", "8080")),
            required("ONVIF_ADVERTISED_HOST"), required("ONVIF_USERNAME"), required("ONVIF_PASSWORD"),
            host, port, required("CAMERA_USERNAME"), required("CAMERA_PASSWORD"),
            os.getenv("CAMERA_MEDIA_URL", f"{scheme}://{host}:{port}/onvif/media_service"),
            os.getenv("SMTP_HOST", "0.0.0.0"), int(os.getenv("SMTP_PORT", "8025")), smtp_user, smtp_password,
            csv_env("MATCH_SUBJECT_PATTERNS", "human,person,intrusion,line crossing,vehicle,alarm"),
            csv_env("MATCH_BODY_PATTERNS", ""), csv_env("IGNORE_SUBJECT_PATTERNS", "test email,smtp test"),
            float(os.getenv("MOTION_EVENT_DURATION_SECONDS", "5")),
            float(os.getenv("MOTION_COOLDOWN_SECONDS", "10")),
            float(os.getenv("ONVIF_SUBSCRIPTION_TTL_SECONDS", "3600")),
            float(os.getenv("ONVIF_AUTH_CLOCK_TOLERANCE_SECONDS", "300")),
            bool_env("VERIFY_UPSTREAM_TLS", True), bool_env("ENABLE_DEBUG_ENDPOINTS"),
            os.getenv("ONVIF_DEVICE_UUID", "2fc995e1-9d08-5d38-97d3-cc5f5b0c72a1"),
        )
