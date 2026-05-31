# ONVIF to Synology Surveillance Station bridge

This repository contains a tiny Python service for cameras that expose useful
ONVIF analytics events, but whose events are not shown as selectable camera
triggers inside Synology Surveillance Station.

The target flow is:

```text
ONVIF camera analytics event
        ↓
this bridge
        ↓
Synology Action Rule webhook or ExternalEvent API
        ↓
notification, bookmark, recording, or trigger motion event action
```

It is intended for cameras that publish events such as `MyFieldDetector`,
`MyLineDetector`, or `MyMotionDetectorRule` in tools like ONVIF Device Manager.

## Important Synology setup note

If **Camera** is not a usable event source in your Action Rule screen, do not try
to solve this from the camera event list. Instead, create an Action Rule whose
**event source** is one of these Synology-side sources:

- **Webhook** → **External event detected via URL** on newer Surveillance Station
  versions.
- **External device** → **External event detected** on older Surveillance Station
  versions.

Then set the **action device** to the camera and choose an action such as:

- **Start action rule recording**
- **Trigger motion event**
- **Add bookmark**
- **Take snapshots**
- **Send Notification**

That makes the bridge the trigger, while Synology still performs the camera
recording or notification action.

## Run with Docker Compose

Copy the example compose file and edit the environment values:

```bash
cp docker-compose.example.yml docker-compose.yml
```

Then start it:

```bash
docker compose up -d --build
```

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `CAMERA_HOST` | yes | Camera IP address or DNS name. |
| `CAMERA_PORT` | no | ONVIF HTTP port. Defaults to `80`. |
| `CAMERA_USER` | yes | Camera ONVIF username. |
| `CAMERA_PASSWORD` | yes | Camera ONVIF password. |
| `EVENT_NAME_PATTERNS` | no | Comma-separated substrings to match in ONVIF events. Defaults to `MyFieldDetector,MyLineDetector,MyMotionDetectorRule`. |
| `ACTIVE_VALUES` | no | Values treated as active events. Defaults to `true,1,active`. |
| `COOLDOWN_SECONDS` | no | Per-event-name suppression window. Defaults to `20`. |
| `POLL_TIMEOUT` | no | ONVIF PullMessages timeout. Defaults to `PT30S`. |
| `MESSAGE_LIMIT` | no | ONVIF PullMessages message limit. Defaults to `20`. |
| `VERIFY_TLS` | no | Verify Synology HTTPS certificates. Defaults to `true`; set `false` only for self-signed local certificates you trust. |
| `SYNOLOGY_WEBHOOK_URL` | webhook mode | Full webhook URL copied from the Synology Action Rule event page. |
| `SYNOLOGY_BASE_URL` | ExternalEvent mode | DSM base URL, for example `https://nas.local:5001`. |
| `SYNOLOGY_USER` | ExternalEvent mode | Synology account allowed to trigger Surveillance Station external events. |
| `SYNOLOGY_PASSWORD` | ExternalEvent mode | Password for `SYNOLOGY_USER`. |
| `SYNOLOGY_EXTERNAL_EVENT_ID` | no | External event ID for ExternalEvent mode. Defaults to `1`. |

Set either `SYNOLOGY_WEBHOOK_URL` or the three ExternalEvent variables
`SYNOLOGY_BASE_URL`, `SYNOLOGY_USER`, and `SYNOLOGY_PASSWORD`.

## Recommended path for Proxmox, NAS, Home Assistant, or Homebridge users

The simplest deployment is usually a small Docker container on Proxmox or the
NAS. Home Assistant can also receive ONVIF events, but custom analytics event
names are camera-dependent; this bridge avoids that uncertainty by reading the
ONVIF event stream directly.

## Troubleshooting

1. Confirm ONVIF Device Manager or another ONVIF tool sees the analytics event
   fire before debugging Synology.
2. Run the container with `LOG_LEVEL=DEBUG` to inspect ignored ONVIF messages.
3. If Synology has no **Webhook** event source, use ExternalEvent mode and create
   an Action Rule from **External device** instead.
4. If HTTPS fails with a local self-signed certificate, either install a trusted
   certificate on the NAS or set `VERIFY_TLS=false` on a trusted LAN.
