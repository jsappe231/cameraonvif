# Camera SMTP to Synology Surveillance Station bridge

This repository now assumes the camera **does not publish smart analytics events
through ONVIF**. That matches the current finding from ONVIF Device Manager: ODM
only sees basic motion, while the camera's smart events still fire internally and
can use built-in linkage actions such as **Send Email**.

The bridge therefore uses the camera's email linkage instead of ONVIF:

```text
Camera smart event, e.g. intrusion / human / vehicle
        ↓
Camera built-in Send Email action
        ↓
Local fake SMTP listener in this container
        ↓
Synology Surveillance Station webhook or ExternalEvent API
        ↓
notification, bookmark, recording, or trigger motion event action
```

This avoids HeroSpeed/V247/OEM ONVIF limitations entirely. If the camera can send
an email for a smart event, this bridge can turn that email into a Synology event.

## Synology setup

If **Camera** is not a usable event source in your Action Rule screen, create an
Action Rule whose **event source** is one of these Synology-side sources:

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

## Camera setup

In the camera web UI:

1. Open the smart event you care about, such as intrusion, line crossing, human,
   or vehicle detection.
2. Enable the event and enable the **Send Email** linkage method.
3. Configure SMTP/email settings similar to:

| Camera SMTP field | Value |
| --- | --- |
| SMTP server | IP address of the Docker host / Proxmox VM / NAS running this bridge |
| SMTP port | `8025` by default |
| TLS/SSL | Off / disabled |
| Authentication | Off / disabled, if the camera allows it |
| Sender | Any address, for example `camera@example.local` |
| Recipient | Any address, for example `synology@example.local` |

If your camera requires port 25, map host port 25 to container port 8025 in
`docker-compose.yml` with `"25:8025"`. On Linux, binding to port 25 may require
root privileges or firewall/NAT port forwarding.

## Run with Docker Compose

Copy the example compose file and edit the environment values:

```bash
cp docker-compose.example.yml docker-compose.yml
```

Then start it:

```bash
docker compose up -d --build
```

Watch logs while triggering a smart event:

```bash
docker compose logs -f
```

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `SMTP_HOST` | no | SMTP bind address. Defaults to `0.0.0.0`. |
| `SMTP_PORT` | no | SMTP listen port inside the container. Defaults to `8025`. |
| `MATCH_SUBJECT_PATTERNS` | no | Comma-separated, case-insensitive subject substrings that should trigger Synology. Defaults to `intrusion,line crossing,human,vehicle,person,alarm`. |
| `MATCH_BODY_PATTERNS` | no | Optional comma-separated body substrings that should trigger Synology. Defaults to empty. |
| `IGNORE_SUBJECT_PATTERNS` | no | Comma-separated subject substrings to ignore. Defaults to `test email`. |
| `COOLDOWN_SECONDS` | no | Per-event-name suppression window. Defaults to `20`. |
| `MAX_BODY_CHARS` | no | Maximum email body characters included in the Synology payload. Defaults to `2000`. |
| `VERIFY_TLS` | no | Verify Synology HTTPS certificates. Defaults to `true`; set `false` only for self-signed local certificates you trust. |
| `SYNOLOGY_WEBHOOK_URL` | webhook mode | Full webhook URL copied from the Synology Action Rule event page. |
| `SYNOLOGY_WEBHOOK_METHOD` | no | `POST` or `GET` for webhook mode. Defaults to `POST`. |
| `SYNOLOGY_BASE_URL` | ExternalEvent mode | DSM base URL, for example `https://nas.local:5001`. |
| `SYNOLOGY_USER` | ExternalEvent mode | Synology account allowed to trigger Surveillance Station external events. |
| `SYNOLOGY_PASSWORD` | ExternalEvent mode | Password for `SYNOLOGY_USER`. |
| `SYNOLOGY_EXTERNAL_EVENT_ID` | no | External event ID for ExternalEvent mode. Defaults to `1`. |

Set either `SYNOLOGY_WEBHOOK_URL` or the three ExternalEvent variables
`SYNOLOGY_BASE_URL`, `SYNOLOGY_USER`, and `SYNOLOGY_PASSWORD`.

## Recommended first test

Before connecting this directly to Synology, you can run `smtp4dev` to discover
exactly what the camera sends:

```yaml
services:
  smtp4dev:
    image: rnwood/smtp4dev
    ports:
      - "8025:25"
      - "5000:80"
```

Point the camera at SMTP port `8025`, trigger the smart event, and inspect the
subject/body at `http://docker-host:5000`. Copy the useful words into
`MATCH_SUBJECT_PATTERNS` or `MATCH_BODY_PATTERNS`.

## Troubleshooting

1. If the camera has a **Test Email** button, use it first and watch
   `docker compose logs -f`.
2. If the camera says SMTP failed, confirm firewall rules and that the camera can
   reach the Docker host on the mapped port.
3. If test emails appear but smart events do not, confirm **Send Email** is
   enabled on the smart event's linkage/action page, not only on the global email
   settings page.
4. If Synology is not triggered, temporarily set `MATCH_SUBJECT_PATTERNS` to a
   very broad value from the logged subject, or set `MATCH_BODY_PATTERNS` based
   on the smtp4dev-discovered email body.
5. If your Synology webhook requires GET instead of POST, set
   `SYNOLOGY_WEBHOOK_METHOD=GET`.
