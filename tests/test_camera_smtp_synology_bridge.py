import importlib
import sys
import types
import unittest


fake_controller_module = types.ModuleType("aiosmtpd.controller")
fake_controller_module.Controller = object
sys.modules.setdefault("aiosmtpd", types.ModuleType("aiosmtpd"))
sys.modules.setdefault("aiosmtpd.controller", fake_controller_module)

fake_requests = types.ModuleType("requests")
fake_requests.Response = object
fake_requests.get = lambda *args, **kwargs: None
fake_requests.post = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

bridge = importlib.import_module("camera_smtp_synology_bridge")


class CameraSmtpBridgeTest(unittest.TestCase):
    def config(self):
        return bridge.Config(
            smtp_host="0.0.0.0",
            smtp_port=8025,
            match_subject_patterns=("intrusion", "human"),
            match_body_patterns=("line crossing",),
            ignore_subject_patterns=("test email",),
            cooldown_seconds=20,
            synology_webhook_url="https://nas.local/webhook",
            synology_webhook_method="POST",
            synology_base_url=None,
            synology_user=None,
            synology_password=None,
            synology_external_event_id=1,
            synology_timeout_seconds=10,
            verify_tls=True,
            max_body_chars=2000,
        )

    def test_parse_plain_email(self):
        raw = (
            b"From: camera@example.local\r\n"
            b"To: synology@example.local\r\n"
            b"Subject: Intrusion Detection Alarm\r\n"
            b"Message-ID: <abc@example.local>\r\n"
            b"\r\n"
            b"Smart event triggered.\r\n"
        )

        parsed = bridge.parse_camera_email(
            raw,
            "camera@example.local",
            ("synology@example.local",),
            2000,
        )

        self.assertEqual(parsed.subject, "Intrusion Detection Alarm")
        self.assertIn("Smart event", parsed.body)
        self.assertEqual(parsed.message_id, "<abc@example.local>")
        self.assertEqual(parsed.attachment_count, 0)

    def test_matching_subject_forwards(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("synology@example.local",),
            subject="Human Detection Alarm",
            body="",
            message_id="",
            attachment_count=0,
        )

        self.assertTrue(bridge.should_forward(camera_email, self.config()))

    def test_ignore_test_email(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("synology@example.local",),
            subject="Test Email - Human Detection",
            body="",
            message_id="",
            attachment_count=0,
        )

        self.assertFalse(bridge.should_forward(camera_email, self.config()))

    def test_matching_body_forwards(self):
        camera_email = bridge.CameraEmail(
            mail_from="camera@example.local",
            rcpt_tos=("synology@example.local",),
            subject="Camera Alarm",
            body="Line crossing detected on channel 1",
            message_id="",
            attachment_count=0,
        )

        self.assertTrue(bridge.should_forward(camera_email, self.config()))


if __name__ == "__main__":
    unittest.main()
