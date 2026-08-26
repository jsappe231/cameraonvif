"""Receive camera alert emails and forward matching events to UniFi Protect.

This bridge is intended for cameras whose smart analytics events do not appear
in ONVIF/ODM, but can trigger the camera's built-in "Send Email" linkage.
It runs a small SMTP listener, accepts those camera emails, matches their
subject/body, and posts a normalized alarm to a UniFi Protect integration URL.
"""

from __future__ import annotations

import asyncio
import email
import hmac
import logging
import os
import signal
import sys
import time
import warnings
from dataclasses import dataclass
from email.message import Message
from typing import Any

import requests
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword, SMTP
from requests import Response

LOGGER = logging.getLogger("camera-smtp-unifi-protect-bridge")
STOP_EVENT: asyncio.Event | None = None


@dataclass(frozen=True)
class Config:
    smtp_host: str
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    match_subject_patterns: tuple[str, ...]
    match_body_patterns: tuple[str, ...]
    ignore_subject_patterns: tuple[str, ...]
    cooldown_seconds: float
    unifi_protect_event_url: str
    unifi_protect_api_key: str | None
    unifi_protect_camera_id: str | None
    unifi_protect_timeout_seconds: float
    verify_tls: bool
    max_body_chars: int

    @classmethod
    def from_env(cls) -> "Config":
        smtp_username = os.getenv("SMTP_USERNAME") or None
        smtp_password = os.getenv("SMTP_PASSWORD") or None
        if bool(smtp_username) != bool(smtp_password):
            raise ValueError("Set both SMTP_USERNAME and SMTP_PASSWORD, or neither.")

        return cls(
            smtp_host=os.getenv("SMTP_HOST", "0.0.0.0"),
            smtp_port=int(os.getenv("SMTP_PORT", "8025")),
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            match_subject_patterns=csv_env(
                "MATCH_SUBJECT_PATTERNS",
                "intrusion,line crossing,human,vehicle,person,alarm",
            ),
            match_body_patterns=csv_env("MATCH_BODY_PATTERNS", ""),
            ignore_subject_patterns=csv_env("IGNORE_SUBJECT_PATTERNS", "test email"),
            cooldown_seconds=float(os.getenv("COOLDOWN_SECONDS", "20")),
            unifi_protect_event_url=required_env("UNIFI_PROTECT_EVENT_URL"),
            unifi_protect_api_key=os.getenv("UNIFI_PROTECT_API_KEY") or None,
            unifi_protect_camera_id=os.getenv("UNIFI_PROTECT_CAMERA_ID") or None,
            unifi_protect_timeout_seconds=float(
                os.getenv("UNIFI_PROTECT_TIMEOUT_SECONDS", "10")
            ),
            verify_tls=bool_env("VERIFY_TLS", True),
            max_body_chars=int(os.getenv("MAX_BODY_CHARS", "2000")),
        )


@dataclass(frozen=True)
class CameraEmail:
    mail_from: str
    rcpt_tos: tuple[str, ...]
    subject: str
    body: str
    message_id: str
    attachment_count: int

    @property
    def event_name(self) -> str:
        return self.subject.strip() or "Camera email alert"


def csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("mail.log").setLevel(os.getenv("SMTP_LOG_LEVEL", "ERROR").upper())


class SmtpAuthenticator:
    """Validate the LOGIN or PLAIN credentials supplied by a camera."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")

    def __call__(
        self,
        server: Any,
        session: Any,
        envelope: Any,
        mechanism: str,
        auth_data: Any,
    ) -> AuthResult:
        if not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)

        success = hmac.compare_digest(auth_data.login, self.username) and hmac.compare_digest(
            auth_data.password, self.password
        )
        return AuthResult(
            success=success,
            handled=success,
            auth_data=auth_data if success else None,
        )


class CameraSmtpServer(SMTP):
    """Support legacy cameras that issue AUTH after HELO instead of EHLO."""

    async def smtp_AUTH(self, arg: str) -> None:
        assert self.session is not None
        used_legacy_helo = bool(self.session.host_name and not self.session.extended_smtp)
        if used_legacy_helo:
            LOGGER.info("Accepting legacy AUTH after HELO from %s", self.session.peer)
            self.session.extended_smtp = True
        try:
            await super().smtp_AUTH(arg)
        finally:
            if used_legacy_helo:
                self.session.extended_smtp = False


class CameraSmtpController(Controller):
    def factory(self) -> CameraSmtpServer:
        # aiosmtpd warns for every connection when plaintext AUTH is enabled.
        # The limitation is documented and logged once by this application.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Requiring AUTH while not requiring TLS.*",
                category=UserWarning,
            )
            return CameraSmtpServer(self.handler, **self.SMTP_kwargs)


class CameraEmailHandler:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.last_sent_at: dict[str, float] = {}

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        camera_email = parse_camera_email(
            content=envelope.content,
            mail_from=envelope.mail_from,
            rcpt_tos=tuple(envelope.rcpt_tos),
            max_body_chars=self.config.max_body_chars,
        )
        LOGGER.info(
            "Received camera email from %s to %s with subject %r",
            camera_email.mail_from,
            ",".join(camera_email.rcpt_tos),
            camera_email.subject,
        )

        if not should_forward(camera_email, self.config):
            LOGGER.info("Ignoring non-matching camera email: %r", camera_email.subject)
            return "250 Message accepted"

        if self.in_cooldown(camera_email):
            LOGGER.info("Suppressing %r during cooldown", camera_email.event_name)
            return "250 Message accepted"

        send_to_unifi_protect(camera_email, self.config)
        self.last_sent_at[camera_email.event_name.lower()] = time.monotonic()
        LOGGER.info("Forwarded camera email alert to UniFi Protect: %s", camera_email.event_name)
        return "250 Message accepted"

    def in_cooldown(self, camera_email: CameraEmail) -> bool:
        key = camera_email.event_name.lower()
        previous = self.last_sent_at.get(key, 0)
        return time.monotonic() - previous < self.config.cooldown_seconds


def parse_camera_email(
    content: bytes | str,
    mail_from: str,
    rcpt_tos: tuple[str, ...],
    max_body_chars: int,
) -> CameraEmail:
    if isinstance(content, str):
        raw_bytes = content.encode("utf-8", errors="replace")
    else:
        raw_bytes = content

    message = email.message_from_bytes(raw_bytes)
    subject = decoded_header(message.get("Subject", ""))
    body, attachment_count = extract_body_and_attachment_count(message)
    body = body[:max_body_chars]

    return CameraEmail(
        mail_from=mail_from or decoded_header(message.get("From", "")),
        rcpt_tos=rcpt_tos,
        subject=subject,
        body=body,
        message_id=decoded_header(message.get("Message-ID", "")),
        attachment_count=attachment_count,
    )


def decoded_header(value: str) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded_parts: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts).strip()


def extract_body_and_attachment_count(message: Message) -> tuple[str, int]:
    if not message.is_multipart():
        return decode_part(message), 0

    body_parts: list[str] = []
    attachment_count = 0
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        content_type = part.get_content_type().lower()
        if disposition == "attachment" or content_type.startswith("image/"):
            attachment_count += 1
            continue
        if content_type in {"text/plain", "text/html"}:
            body_parts.append(decode_part(part))
    return "\n".join(part for part in body_parts if part), attachment_count


def decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        payload_text = part.get_payload()
        return payload_text if isinstance(payload_text, str) else ""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def should_forward(camera_email: CameraEmail, config: Config) -> bool:
    subject = camera_email.subject.lower()
    body = camera_email.body.lower()

    if any(pattern.lower() in subject for pattern in config.ignore_subject_patterns):
        return False

    subject_match = any(pattern.lower() in subject for pattern in config.match_subject_patterns)
    body_match = any(pattern.lower() in body for pattern in config.match_body_patterns)
    return subject_match or body_match


def send_to_unifi_protect(camera_email: CameraEmail, config: Config) -> None:
    payload = {
        "type": "camera-email-alarm",
        "name": camera_email.event_name,
        "source": camera_email.mail_from,
        "description": f"Camera email alert: {camera_email.event_name}",
        "cameraId": config.unifi_protect_camera_id,
        "subject": camera_email.subject,
        "body": camera_email.body,
        "messageId": camera_email.message_id,
        "recipients": list(camera_email.rcpt_tos),
        "attachmentCount": camera_email.attachment_count,
    }
    headers = {"Accept": "application/json"}
    if config.unifi_protect_api_key:
        headers["X-API-Key"] = config.unifi_protect_api_key
    response = requests.post(
        config.unifi_protect_event_url,
        json=payload,
        headers=headers,
        timeout=config.unifi_protect_timeout_seconds,
        verify=config.verify_tls,
    )
    check_response(response)


def check_response(response: Response) -> None:
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        if body.get("success") is False:
            raise RuntimeError(f"UniFi Protect integration returned failure: {body}")


async def run(config: Config) -> None:
    global STOP_EVENT
    STOP_EVENT = asyncio.Event()
    handler = CameraEmailHandler(config)
    smtp_options: dict[str, Any]
    if config.smtp_username and config.smtp_password:
        smtp_options = {
            "authenticator": SmtpAuthenticator(config.smtp_username, config.smtp_password),
            "auth_required": True,
            # Camera appliances commonly support AUTH only over local, plaintext SMTP.
            "auth_require_tls": False,
        }
    else:
        # Do not advertise AUTH when no credentials were configured. This avoids
        # inviting cameras to start AUTH LOGIN only to have it rejected.
        smtp_options = {"auth_exclude_mechanism": ["LOGIN", "PLAIN"]}

    controller = CameraSmtpController(
        handler,
        hostname=config.smtp_host,
        port=config.smtp_port,
        **smtp_options,
    )
    controller.start()
    if config.smtp_username:
        LOGGER.warning(
            "SMTP authentication is running without TLS; use only on a trusted camera network"
        )
    LOGGER.info(
        "SMTP listener started on %s:%s (%s)",
        config.smtp_host,
        config.smtp_port,
        "authentication required" if config.smtp_username else "authentication disabled",
    )
    try:
        await STOP_EVENT.wait()
    finally:
        controller.stop()
        LOGGER.info("SMTP listener stopped")


def request_shutdown(signum: int, _frame: Any) -> None:
    LOGGER.info("Received signal %s; shutting down", signum)
    if STOP_EVENT:
        STOP_EVENT.set()


def main() -> int:
    configure_logging()
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    try:
        asyncio.run(run(Config.from_env()))
    except Exception:
        LOGGER.exception("Bridge stopped because of an unrecoverable error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
