# Camera SMTP to synthetic ONVIF motion bridge

This service presents a third-party camera to UniFi Protect through a bridge
ONVIF endpoint. Device identity and service addresses belong to the bridge,
Media requests are authenticated and proxied to the real camera, and RTSP URIs
remain pointed at the real camera. Smart-detection email becomes a standard
ONVIF CellMotionDetector/Motion property change.

> The bridge converts proprietary camera smart detections received by SMTP into
> standard ONVIF motion events. UniFi Protect sees these as ordinary third-party
> ONVIF motion events, not native UniFi AI/person detections.

~~~text
                         +-- bridge Device service
Protect -- ONVIF ------>+-- proxied real-camera Media service
                         +-- synthetic PullPoint Events service
Protect -- RTSP -----------------------------> real camera
Camera  -- SMTP -------> bridge -- motion true/false --> Protect PullPoint
~~~

No video is decoded, relayed, or re-encoded.

## Implemented ONVIF subset

* Device: GetCapabilities, GetServices, GetDeviceInformation,
  GetSystemDateAndTime, GetScopes, and GetHostname.
* Media: transparent SOAP proxy for profiles, stream URI, and configuration
  calls. HTTP ONVIF XAddrs are rewritten to the bridge; RTSP values remain real.
* Events: GetEventProperties, CreatePullPointSubscription, long-polling
  PullMessages, Renew, and Unsubscribe.
* WS-Security UsernameToken plaintext and PasswordDigest authentication with
  nonce, Created time, constant-time comparison, and clock tolerance.
* Unknown actions return a SOAP fault without stopping the process.

The emitted and advertised topic is
tns1:RuleEngine/CellMotionDetector/Motion. Notifications carry an ONVIF
tt:Message property change with Data/SimpleItem Name=IsMotion set first to true
and later false. A retrigger resets the clear timer.

## Prerequisites and limitations

* The real camera needs working ONVIF Media and RTSP services.
* Protect must be added manually by bridge IP in this milestone. WS-Discovery
  UDP 3702 is not implemented yet.
* The default upstream Media URL is
  http://CAMERA_ONVIF_HOST:CAMERA_ONVIF_PORT/onvif/media_service. Override
  CAMERA_MEDIA_URL for cameras with a nonstandard XAddr.
* Protect commonly applies adopted ONVIF credentials to RTSP. For the simplest
  playable setup, use bridge credentials that also work for camera RTSP.
  Upstream SOAP always uses CAMERA_USERNAME and CAMERA_PASSWORD.
* This creates ordinary motion markers, not Protect AI metadata.
* Protect firmware sequences vary. DEBUG logging and standards SOAP faults make
  it possible to add narrowly scoped missing actions.

## Docker setup

~~~bash
cp docker-compose.example.yml docker-compose.yml
# Edit every address and password.
docker compose up -d --build
docker compose logs -f
~~~

| Port | Purpose |
| --- | --- |
| TCP 8080 | ONVIF Device, Media, Events, health |
| TCP 8025 | Camera SMTP receiver |
| UDP 3702 | Not exposed; discovery is not implemented |
| RTSP | Not exposed; Protect connects to the camera |

Secrets are environment variables only. Do not commit the edited Compose file.

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| ONVIF_ADVERTISED_HOST | yes | LAN IP or hostname Protect uses; never 0.0.0.0. |
| ONVIF_USERNAME / ONVIF_PASSWORD | yes | Credentials entered in Protect. |
| ONVIF_BIND_HOST / ONVIF_PORT | no | HTTP bind; default 0.0.0.0:8080. |
| ONVIF_DEVICE_UUID | no | Stable bridge identity; do not change after adoption. |
| ONVIF_AUTH_CLOCK_TOLERANCE_SECONDS | no | UsernameToken tolerance; default 300. |
| CAMERA_ONVIF_HOST | yes | Real camera address. |
| CAMERA_ONVIF_PORT | no | Real camera ONVIF port; default 80. |
| CAMERA_USERNAME / CAMERA_PASSWORD | yes | Upstream SOAP credentials. |
| CAMERA_MEDIA_URL | no | Full upstream Media service URL override. |
| VERIFY_UPSTREAM_TLS | no | Upstream certificate verification; default true. |
| SMTP_HOST / SMTP_PORT | no | SMTP bind; default 0.0.0.0:8025. |
| SMTP_USERNAME / SMTP_PASSWORD | no | Optional LOGIN/PLAIN pair. |
| MATCH_SUBJECT_PATTERNS | no | Default human,person,intrusion,line crossing,vehicle,alarm. |
| MATCH_BODY_PATTERNS | no | Optional body substrings. |
| IGNORE_SUBJECT_PATTERNS | no | Default test email,smtp test. |
| MOTION_EVENT_DURATION_SECONDS | no | Active duration; default 5, retriggers reset it. |
| MOTION_COOLDOWN_SECONDS | no | Reserved for future de-duplication; active retriggers extend. |
| ONVIF_SUBSCRIPTION_TTL_SECONDS | no | Subscription lifetime; default 3600. |
| ENABLE_DEBUG_ENDPOINTS | no | Enables POST /debug/motion; default false. |
| LOG_LEVEL | no | Use DEBUG for sanitized SOAP logging. |

## Camera SMTP setup

Enable Send Email on each desired smart rule:

| Setting | Value |
| --- | --- |
| Server | Docker host address |
| Port | 8025 |
| TLS | Off |
| Authentication | Off, or configured SMTP credentials |
| Sender / recipient | Any valid-looking local addresses |

LOGIN and PLAIN, including legacy HELO followed by AUTH, are supported. Plain
SMTP credentials are unencrypted, so isolate the camera LAN.

## Protect adoption

1. Confirm curl http://BRIDGE:8080/health returns status ok.
2. Add a third-party ONVIF camera manually using the bridge address, port 8080,
   and ONVIF_USERNAME / ONVIF_PASSWORD.
3. Protect should query bridge Device, proxy Media through the bridge, receive a
   real-camera RTSP URI, and create a PullPoint subscription.
4. Trigger a human rule and look for Synthetic motion ACTIVE, Delivered
   motion=true, and later Delivered motion=false.

## Diagnostics

GET /health returns status, SMTP state, subscription count, and motion state.
For an end-to-end test, temporarily enable ENABLE_DEBUG_ENDPOINTS and run:

~~~bash
curl -X POST http://BRIDGE:8080/debug/motion
~~~

Disable it afterward. It uses the same motion path as SMTP.

LOG_LEVEL=DEBUG logs SOAP actions and sanitized XML. The WS-Security node is
replaced by [redacted], so authentication material is not logged.

## Troubleshooting

* Protect cannot connect: use bridge IP and port 8080 and ensure
  ONVIF_ADVERTISED_HOST is reachable from the console.
* GetProfiles fails: inspect the camera Media XAddr and set CAMERA_MEDIA_URL.
* Video authentication fails: use bridge credentials accepted by camera RTSP.
* SMTP stops at AUTH LOGIN: match SMTP credentials on camera and bridge.
* No event: verify a subscription exists and the subject is not ignored.
* Unknown action: enable DEBUG, capture its name and sanitized request, and add
  the missing narrow handler.
