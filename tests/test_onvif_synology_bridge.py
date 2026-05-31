import importlib
import sys
import types
import unittest


fake_onvif = types.ModuleType("onvif")
fake_onvif.ONVIFCamera = object
sys.modules.setdefault("onvif", fake_onvif)

fake_requests = types.ModuleType("requests")
fake_requests.Response = object
fake_requests.get = lambda *args, **kwargs: None
fake_requests.post = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

bridge = importlib.import_module("onvif_synology_bridge")


class FakeZeep:
    def __init__(self, values):
        object.__setattr__(self, "__values__", values)


class FakeCamera:
    def __init__(self):
        self.xaddrs = {}


class BridgeHelpersTest(unittest.TestCase):
    def test_subscription_address_reads_zeep_values(self):
        response = FakeZeep(
            {
                "SubscriptionReference": FakeZeep(
                    {"Address": FakeZeep({"_value_1": "http://camera/onvif/subscription/7"})}
                )
            }
        )

        self.assertEqual(
            bridge.subscription_address(response),
            "http://camera/onvif/subscription/7",
        )

    def test_set_and_read_pullpoint_xaddr(self):
        camera = FakeCamera()

        bridge.set_pullpoint_xaddr(camera, "http://camera/onvif/subscription/7")

        self.assertEqual(
            bridge.current_pullpoint_xaddr(camera),
            "http://camera/onvif/subscription/7",
        )

    def test_relative_xaddr_is_normalized_against_camera(self):
        config = bridge.Config(
            camera_host="10.0.69.11",
            camera_port=80,
            camera_user="admin",
            camera_password="password",
            event_name_patterns=("MyFieldDetector",),
            active_values=("true",),
            cooldown_seconds=20,
            poll_timeout="PT30S",
            message_limit=20,
            verify_tls=True,
            synology_webhook_url="https://nas.local/webhook",
            synology_base_url=None,
            synology_user=None,
            synology_password=None,
            synology_external_event_id=1,
            synology_timeout_seconds=10,
            pullpoint_xaddr=None,
            reconnect_seconds=15,
        )

        self.assertEqual(
            bridge.normalize_xaddr("/onvif/subscription/0", config),
            "http://10.0.69.11:80/onvif/subscription/0",
        )

    def test_parse_event_uses_matching_simple_item_name_not_whole_payload(self):
        config = bridge.Config(
            camera_host="10.0.69.11",
            camera_port=80,
            camera_user="admin",
            camera_password="password",
            event_name_patterns=("MyFieldDetector", "MyLineDetector"),
            active_values=("true",),
            cooldown_seconds=20,
            poll_timeout="PT30S",
            message_limit=20,
            verify_tls=True,
            synology_webhook_url="https://nas.local/webhook",
            synology_base_url=None,
            synology_user=None,
            synology_password=None,
            synology_external_event_id=1,
            synology_timeout_seconds=10,
            pullpoint_xaddr=None,
            reconnect_seconds=15,
        )
        message = {
            "Topic": {"_value_1": "tns1:RuleEngine/FieldDetector/Motion"},
            "Message": {
                "Source": {
                    "SimpleItem": [
                        {"Name": "VideoSourceConfigurationToken", "Value": "profile1"},
                        {"Name": "Rule", "Value": "MyFieldDetector1"},
                    ]
                },
                "Data": {"SimpleItem": {"Name": "State", "Value": "true"}},
            },
        }

        event = bridge.parse_event(message, config)

        self.assertIsNotNone(event)
        self.assertEqual(event.name, "MyFieldDetector1")
        self.assertTrue(event.active)


if __name__ == "__main__":
    unittest.main()
