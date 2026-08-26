# Camera SMTP to UniFi Protect bridge

This service turns smart-detection emails from an ONVIF camera into JSON events
for a UniFi Protect integration. It is useful when Protect can adopt the camera
but the camera does not expose its human, vehicle, intrusion, or line-crossing
analytics through ONVIF.

```text
Camera smart event -> camera Send Email action -> local SMTP listener
                   -> UniFi Protect event/integration URL
```

> **Important limitation:** UniFi Protect does not expose a generic inbound
> `/protect-event` HTTP endpoint and its Alarm Manager webhooks are outbound
> actions. Do not set `UNIFI_PROTECT_EVENT_URL` to your console plus
> `/protect-event`; that URL returns `404` or `405`. The value must be a genuine
> inbound endpoint from automation or middleware connected to Protect. Protect's
> public integration API can read Protect events, but does not provide an API for
> injecting an arbitrary third-party smart-detection event into its timeline.

## Camera setup

Enable **Send Email** for each desired smart event, then configure the camera's
mail settings as follows:

| Camera SMTP field | Value |
| --- | --- |
| SMTP server | Address of the Docker host running this bridge |
| SMTP port | `8025` (default) |
| TLS/SSL | Off |
| Authentication | Off, or LOGIN/PLAIN with `SMTP_USERNAME` and `SMTP_PASSWORD` |
| Sender / recipient | Any valid-looking local addresses |

If the camera requires port 25, map `25:8025` instead. Binding port 25 may need
additional host privileges or firewall configuration.

SMTP authentication from these cameras is normally plaintext LOGIN/PLAIN because
they do not support STARTTLS. Use it only on a trusted, isolated camera network;
the credentials protect against accidental senders but are not encrypted in transit.

## UniFi Protect setup

1. Create or identify an inbound event URL in Protect-connected automation or
   middleware and obtain its API key if required. The Protect console itself is
   not this receiver.
2. Put that complete URL in `UNIFI_PROTECT_EVENT_URL`.
3. Put the key in `UNIFI_PROTECT_API_KEY`. It is sent as `X-API-Key`.
4. Optionally set `UNIFI_PROTECT_CAMERA_ID` so the receiver can associate the
   email alarm with an adopted camera.
5. Configure the receiving automation to turn `camera-email-alarm` events into
   the desired Protect alarm, notification, or recording action.

The bridge posts JSON like this:

```json
{
  "type": "camera-email-alarm",
  "name": "Human Detection Alarm",
  "source": "camera@example.local",
  "description": "Camera email alert: Human Detection Alarm",
  "cameraId": "protect-camera-id",
  "subject": "Human Detection Alarm",
  "body": "Alarm input 1",
  "messageId": "<example@camera.local>",
  "recipients": ["protect@example.local"],
  "attachmentCount": 1
}
```

## Run with Docker Compose

```bash
cp docker-compose.example.yml docker-compose.yml
# Edit UNIFI_PROTECT_EVENT_URL and credentials first.
docker compose up -d --build
docker compose logs -f
```

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `UNIFI_PROTECT_EVENT_URL` | yes | Complete inbound automation/middleware URL; never a made-up path on the Protect console. |
| `UNIFI_PROTECT_API_KEY` | no | API key sent in the `X-API-Key` header. |
| `UNIFI_PROTECT_CAMERA_ID` | no | Protect camera identifier added as `cameraId`. |
| `UNIFI_PROTECT_TIMEOUT_SECONDS` | no | HTTP timeout; defaults to `10`. |
| `SMTP_HOST` | no | SMTP bind address; defaults to `0.0.0.0`. |
| `SMTP_PORT` | no | SMTP listener port; defaults to `8025`. |
| `SMTP_USERNAME` | no | SMTP username for camera LOGIN/PLAIN authentication. Must be set with `SMTP_PASSWORD`. |
| `SMTP_PASSWORD` | no | SMTP password for camera LOGIN/PLAIN authentication. Must be set with `SMTP_USERNAME`. |
| `MATCH_SUBJECT_PATTERNS` | no | Comma-separated subject fragments; defaults to `intrusion,line crossing,human,vehicle,person,alarm`. |
| `MATCH_BODY_PATTERNS` | no | Optional comma-separated body fragments. |
| `IGNORE_SUBJECT_PATTERNS` | no | Ignored subject fragments; defaults to `test email,smtp test`. |
| `COOLDOWN_SECONDS` | no | Per-subject suppression window; defaults to `20`. |
| `MAX_BODY_CHARS` | no | Maximum body length in the JSON; defaults to `2000`. |
| `VERIFY_TLS` | no | Verify destination TLS; defaults to `true`. Only disable for a trusted self-signed local endpoint. |
| `LOG_LEVEL` | no | Python log level; defaults to `INFO`. |
| `SMTP_LOG_LEVEL` | no | Internal SMTP protocol log level; defaults to `ERROR`. Use `INFO` for protocol troubleshooting. |

## Troubleshooting

1. Watch `docker compose logs -f` while using the camera's Test Email button.
2. If the log ends at `AUTH LOGIN`, set both `SMTP_USERNAME` and `SMTP_PASSWORD`
   to the same credentials configured in the camera, then recreate the container.
   The bridge accepts AUTH after either `HELO` or `EHLO` for older camera firmware.
3. Test emails are ignored by default. Confirm the log says they were received.
4. Trigger a real event and verify its subject matches a configured pattern.
5. A non-2xx destination response is logged and returned to the camera as an
   SMTP processing failure, allowing the camera to retry where supported.
6. A `404` or `405` means the configured URL is not an inbound receiver. In
   particular, `https://your-console/protect-event` is not a Protect API route.
7. Do not place a Protect outbound webhook URL in `UNIFI_PROTECT_EVENT_URL`.
