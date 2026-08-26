import importlib
import unittest

import requests
from aiosmtpd.smtp import LoginPassword

bridge = importlib.import_module("camera_smtp_unifi_protect_bridge")


class CameraSmtpBridgeTest(unittest.TestCase):
    def config(self):
        return bridge.Config(
            smtp_host="0.0.0.0",
            smtp_port=8025,
            smtp_username="camera",
            smtp_password="password",
            match_subject_patterns=("intrusion", "human"),
            match_body_patterns=("line crossing",),
            ignore_subject_patterns=("test email",),
            cooldown_seconds=20,
            unifi_protect_event_url="https://automation.local/hooks/camera-event",
            unifi_protect_api_key="secret",
            unifi_protect_camera_id="camera-id",
            unifi_protect_timeout_seconds=10,
            verify_tls=True,
            max_body_chars=2000,
        )

    def test_parse_plain_email(self):
        raw = (
            b"From: camera@example.local\r\n"
            b"To: protect@example.local\r\n"
            b"Subject: Intrusion Detection Alarm\r\n"
            b"Message-ID: <abc@example.local>\r\n"
            b"\r\n"
            b"Smart event triggered.\r\n"
        )

        parsed = bridge.parse_camera_email(
            raw,
            "camera@example.local",
            ("protect@example.local",),
            2000,
        )

        self.assertEqual(parsed.subject, "Intrusion Detection Alarm")
        self.assertIn("Smart event", parsed.body)
        self.assertEqual(parsed.message_id, "<abc@example.local>")
        self.assertEqual(parsed.attachment_count, 0)

    def test_matching_subject_forwards(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("protect@example.local",),
            subject="Human Detection Alarm",
            body="",
            message_id="",
            attachment_count=0,
        )

        self.assertTrue(bridge.should_forward(camera_email, self.config()))

    def test_ignore_test_email(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("protect@example.local",),
            subject="Test Email - Human Detection",
            body="",
            message_id="",
            attachment_count=0,
        )

        self.assertFalse(bridge.should_forward(camera_email, self.config()))

    def test_ignore_camera_smtp_test(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("protect@example.local",),
            subject="IP Camera: Smtp Test",
            body="",
            message_id="",
            attachment_count=0,
        )
        config = self.config()
        config = bridge.Config(
            **{
                **config.__dict__,
                "ignore_subject_patterns": ("test email", "smtp test"),
            }
        )

        self.assertFalse(bridge.should_forward(camera_email, config))

    def test_matching_body_forwards(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("protect@example.local",),
            subject="Camera Alarm",
            body="Line crossing detected on channel 1",
            message_id="",
            attachment_count=0,
        )

        self.assertTrue(bridge.should_forward(camera_email, self.config()))

    def test_posts_normalized_event_with_api_key(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("protect@example.local",),
            subject="Human Detection Alarm",
            body="Person detected",
            message_id="<event@camera.local>",
            attachment_count=1,
        )
        calls = []
        original_post = bridge.requests.post
        bridge.requests.post = lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse()
        try:
            bridge.send_to_unifi_protect(camera_email, self.config())
        finally:
            bridge.requests.post = original_post

        args, kwargs = calls[0]
        self.assertEqual(args[0], "https://automation.local/hooks/camera-event")
        self.assertEqual(kwargs["headers"]["X-API-Key"], "secret")
        self.assertEqual(kwargs["json"]["type"], "camera-email-alarm")
        self.assertEqual(kwargs["json"]["cameraId"], "camera-id")
        self.assertEqual(kwargs["json"]["attachmentCount"], 1)

    def test_smtp_authenticator_accepts_matching_credentials(self):
        authenticator = bridge.SmtpAuthenticator("camera", "password")

        result = authenticator(None, None, None, "LOGIN", LoginPassword(b"camera", b"password"))

        self.assertTrue(result.success)

    def test_smtp_authenticator_rejects_bad_credentials(self):
        authenticator = bridge.SmtpAuthenticator("camera", "password")

        result = authenticator(None, None, None, "LOGIN", LoginPassword(b"camera", b"wrong"))

        self.assertFalse(result.success)
        self.assertFalse(result.handled)

    def test_405_explains_that_console_is_not_an_event_receiver(self):
        response = requests.Response()
        response.status_code = 405
        response.url = "https://unifi.example.local/protect-event"

        with self.assertRaisesRegex(requests.HTTPError, "not an inbound event endpoint"):
            bridge.check_response(response)


class FakeResponse:
    status_code = 200
    url = "https://automation.local/hooks/camera-event"
    headers = {"content-type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return {"success": True}


if __name__ == "__main__":
    unittest.main()
