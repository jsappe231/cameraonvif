"""Bridge ONVIF analytics events into Synology Surveillance Station.

The service subscribes to an ONVIF PullPoint event stream, looks for configured
rule names/topics such as HeroSpeed ``MyFieldDetector`` and ``MyLineDetector``,
and forwards active events to Synology via either an Action Rule webhook URL or
the legacy ``SYNO.SurveillanceStation.ExternalEvent`` API.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from onvif import ONVIFCamera
from requests import Response

LOGGER = logging.getLogger("onvif-synology-bridge")
STOP = False


@dataclass(frozen=True)
class Config:
    camera_host: str
    camera_port: int
    camera_user: str
    camera_password: str
    event_name_patterns: tuple[str, ...]
    active_values: tuple[str, ...]
    cooldown_seconds: float
    poll_timeout: str
    message_limit: int
    verify_tls: bool
    synology_webhook_url: str | None
    synology_base_url: str | None
    synology_user: str | None
    synology_password: str | None
    synology_external_event_id: int
    synology_timeout_seconds: float
    pullpoint_xaddr: str | None
    reconnect_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        webhook_url = os.getenv("SYNOLOGY_WEBHOOK_URL") or None
        base_url = os.getenv("SYNOLOGY_BASE_URL") or None
        user = os.getenv("SYNOLOGY_USER") or None
        password = os.getenv("SYNOLOGY_PASSWORD") or None

        if not webhook_url and not (base_url and user and password):
            raise ValueError(
                "Set SYNOLOGY_WEBHOOK_URL, or set SYNOLOGY_BASE_URL, "
                "SYNOLOGY_USER, and SYNOLOGY_PASSWORD for ExternalEvent mode."
            )

        return cls(
            camera_host=required_env("CAMERA_HOST"),
            camera_port=int(os.getenv("CAMERA_PORT", "80")),
            camera_user=required_env("CAMERA_USER"),
            camera_password=required_env("CAMERA_PASSWORD"),
            event_name_patterns=csv_env(
                "EVENT_NAME_PATTERNS",
                "MyFieldDetector,MyLineDetector,MyMotionDetectorRule",
            ),
            active_values=csv_env("ACTIVE_VALUES", "true,1,active"),
            cooldown_seconds=float(os.getenv("COOLDOWN_SECONDS", "20")),
            poll_timeout=os.getenv("POLL_TIMEOUT", "PT30S"),
            message_limit=int(os.getenv("MESSAGE_LIMIT", "20")),
            verify_tls=bool_env("VERIFY_TLS", True),
            synology_webhook_url=webhook_url,
            synology_base_url=base_url,
            synology_user=user,
            synology_password=password,
            synology_external_event_id=int(os.getenv("SYNOLOGY_EXTERNAL_EVENT_ID", "1")),
            synology_timeout_seconds=float(os.getenv("SYNOLOGY_TIMEOUT_SECONDS", "10")),
            pullpoint_xaddr=os.getenv("PULLPOINT_XADDR") or None,
            reconnect_seconds=float(os.getenv("RECONNECT_SECONDS", "15")),
        )


@dataclass(frozen=True)
class CameraEvent:
    name: str
    topic: str
    active: bool
    raw: dict[str, Any]


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def handle_signal(signum: int, _frame: Any) -> None:
    global STOP
    LOGGER.info("Received signal %s; shutting down", signum)
    STOP = True


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def connect_pullpoint(config: Config) -> Any:
    camera = ONVIFCamera(
        config.camera_host,
        config.camera_port,
        config.camera_user,
        config.camera_password,
    )
    subscription_xaddr = config.pullpoint_xaddr or current_pullpoint_xaddr(camera)
    if not subscription_xaddr:
        events = camera.create_events_service()
        LOGGER.info("Creating ONVIF PullPoint subscription for %s", config.camera_host)
        subscription_response = events.CreatePullPointSubscription()
        subscription_xaddr = subscription_address(subscription_response)

    if not subscription_xaddr:
        raise RuntimeError(
            "The camera created a PullPoint subscription, but no subscription "
            "address was found in the response. Set PULLPOINT_XADDR manually "
            "to the camera's subscription URL shown by another ONVIF tool."
        )

    LOGGER.info("Using ONVIF PullPoint subscription endpoint: %s", subscription_xaddr)
    set_pullpoint_xaddr(camera, subscription_xaddr)
    return camera.create_pullpoint_service()


def current_pullpoint_xaddr(camera: Any) -> str | None:
    xaddrs = getattr(camera, "xaddrs", {})
    for namespace in pullpoint_namespaces():
        if xaddrs.get(namespace):
            return str(xaddrs[namespace])
    return None


def subscription_address(subscription_response: Any) -> str | None:
    raw = object_to_plain(subscription_response)
    candidates = (
        ("SubscriptionReference", "Address", "_value_1"),
        ("SubscriptionReference", "Address"),
        ("SubscriptionReference", "ReferenceParameters", "Address"),
        ("Address", "_value_1"),
        ("Address",),
    )
    for path in candidates:
        value = extract_first(raw, path)
        if value:
            return str(value)
    return find_url_value(raw)


def find_url_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for item in value.values():
            found = find_url_value(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_url_value(item)
            if found:
                return found
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


def pullpoint_namespaces() -> tuple[str, str]:
    return (
        "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription",
        "http://www.onvif.org/ver10/events/wsdl/PullPointSubscriptionBinding",
    )


def set_pullpoint_xaddr(camera: Any, subscription_xaddr: str) -> None:
    for namespace in pullpoint_namespaces():
        camera.xaddrs[namespace] = subscription_xaddr

    pullpoint_service = getattr(camera, "pullpoint", None)
    ws_client = getattr(pullpoint_service, "ws_client", None)
    if ws_client:
        ws_client.set_options(location=subscription_xaddr)


def pull_messages(pullpoint: Any, config: Config) -> list[Any]:
    response = pullpoint.PullMessages(
        {"Timeout": config.poll_timeout, "MessageLimit": config.message_limit}
    )
    messages = field_value(response, "NotificationMessage")
    if not messages:
        return []
    if isinstance(messages, list):
        return messages
    return [messages]


def field_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def parse_event(message: Any, config: Config) -> CameraEvent | None:
    raw = object_to_plain(message)
    haystack = json.dumps(raw, default=str, sort_keys=True)
    if not any(pattern in haystack for pattern in config.event_name_patterns):
        return None

    topic = str(extract_first(raw, ("Topic", "_value_1")) or extract_first(raw, ("Topic",)) or "")
    name = find_matching_name(raw, config.event_name_patterns) or topic or "onvif-event"
    active = event_is_active(raw, config.active_values)
    return CameraEvent(name=name, topic=topic, active=active, raw=raw)


def object_to_plain(value: Any) -> Any:
    zeep_values = get_zeep_values(value)
    if zeep_values is not None:
        return object_to_plain(zeep_values)
    if isinstance(value, Mapping):
        return {str(key): object_to_plain(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [object_to_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: object_to_plain(val)
            for key, val in vars(value).items()
            if not key.startswith("__") or key == "__values__"
        }
    return value


def get_zeep_values(value: Any) -> Any:
    try:
        return object.__getattribute__(value, "__values__")
    except AttributeError:
        return None


def extract_first(value: Any, path: Iterable[str]) -> Any:
    current = value
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def find_matching_name(raw: Any, patterns: tuple[str, ...]) -> str | None:
    if isinstance(raw, dict):
        for key, value in raw.items():
            text = str(value)
            for pattern in patterns:
                if pattern in text:
                    return text
            nested = find_matching_name(value, patterns)
            if nested:
                return nested
    if isinstance(raw, list):
        for item in raw:
            nested = find_matching_name(item, patterns)
            if nested:
                return nested
    return None


def event_is_active(raw: Any, active_values: tuple[str, ...]) -> bool:
    values = [str(value).strip().lower() for value in walk_values(raw)]
    active_set = {value.lower() for value in active_values}

    state_like_keys = {"state", "isactive", "active", "logicalstate", "value"}
    for key, value in walk_items(raw):
        if key.lower() in state_like_keys and str(value).strip().lower() in active_set:
            return True

    return any(value in active_set for value in values)


def walk_values(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_values(item)
    else:
        yield value


def walk_items(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                yield from walk_items(item)
            else:
                yield str(key), item
    elif isinstance(value, list):
        for item in value:
            yield from walk_items(item)


def send_to_synology(event: CameraEvent, config: Config) -> None:
    if config.synology_webhook_url:
        send_webhook(event, config)
    else:
        trigger_external_event(event, config)


def send_webhook(event: CameraEvent, config: Config) -> None:
    payload = {
        "name": event.name,
        "source": config.camera_host,
        "description": f"ONVIF analytics event: {event.name}",
        "topic": event.topic,
        "active": event.active,
    }
    response = requests.post(
        config.synology_webhook_url,
        json=payload,
        timeout=config.synology_timeout_seconds,
        verify=config.verify_tls,
    )
    check_response(response)


def trigger_external_event(event: CameraEvent, config: Config) -> None:
    assert config.synology_base_url
    assert config.synology_user
    assert config.synology_password

    url = urljoin(config.synology_base_url.rstrip("/") + "/", "webapi/entry.cgi")
    response = requests.get(
        url,
        params={
            "api": "SYNO.SurveillanceStation.ExternalEvent",
            "method": "Trigger",
            "version": 1,
            "eventId": config.synology_external_event_id,
            "eventName": event.name,
            "account": config.synology_user,
            "password": config.synology_password,
        },
        timeout=config.synology_timeout_seconds,
        verify=config.verify_tls,
    )
    check_response(response)


def check_response(response: Response) -> None:
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        if body.get("success") is False:
            raise RuntimeError(f"Synology API returned failure: {body}")


def run(config: Config) -> None:
    last_sent_at: dict[str, float] = {}

    while not STOP:
        try:
            pullpoint = connect_pullpoint(config)
            while not STOP:
                for message in pull_messages(pullpoint, config):
                    event = parse_event(message, config)
                    if not event:
                        LOGGER.debug("Ignoring unmatched ONVIF event: %s", message)
                        continue
                    if not event.active:
                        LOGGER.info("Ignoring inactive event: %s", event.name)
                        continue

                    now = time.monotonic()
                    previous = last_sent_at.get(event.name, 0)
                    if now - previous < config.cooldown_seconds:
                        LOGGER.info("Suppressing %s during cooldown", event.name)
                        continue

                    LOGGER.info("Forwarding active ONVIF event to Synology: %s", event.name)
                    send_to_synology(event, config)
                    last_sent_at[event.name] = now
        except Exception:
            if STOP:
                raise
            LOGGER.exception(
                "ONVIF polling failed; reconnecting in %.1f seconds",
                config.reconnect_seconds,
            )
            time.sleep(config.reconnect_seconds)


def main() -> int:
    configure_logging()
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        run(Config.from_env())
    except Exception:
        LOGGER.exception("Bridge stopped because of an unrecoverable error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
