import asyncio,base64,hashlib
from datetime import datetime,timezone
from types import SimpleNamespace
from xml.etree import ElementTree as ET
import unittest
try:
    from aiohttp.test_utils import TestClient,TestServer
    from cameraonvif.onvif.server import OnvifServer
except ModuleNotFoundError:
    TestClient=TestServer=OnvifServer=None

from cameraonvif.config import Config
from cameraonvif.motion import MotionManager
from cameraonvif.onvif.auth import WSSE,WSU,authenticate
from cameraonvif.onvif.events import event_properties,notification,subscription_response
from cameraonvif.onvif.xml import MOTION_TOPIC,SOAP12,TEV,TT,WSNT,envelope,q
from cameraonvif.smtp_server import CameraEmail,Handler,should_trigger

def config(**changes):
    values=dict(onvif_bind_host="127.0.0.1",onvif_port=8080,onvif_advertised_host="192.168.88.10",
        onvif_username="protect",onvif_password="secret",camera_host="192.168.88.20",camera_port=80,
        camera_username="camera",camera_password="camera-secret",camera_media_url="http://192.168.88.20/onvif/media_service",
        smtp_host="127.0.0.1",smtp_port=8025,smtp_username=None,smtp_password=None,
        match_subject_patterns=("human","person","alarm"),match_body_patterns=(),ignore_subject_patterns=("test email","smtp test"),
        motion_duration=.04,motion_cooldown=.01,subscription_ttl=3600,auth_clock_tolerance=300,
        verify_upstream_tls=True,enable_debug_endpoints=False,stable_uuid="stable-test-uuid")
    values.update(changes); return Config(**values)

def soap(action,namespace=TEV,username="protect",password="secret"):
    root=ET.Element(q(SOAP12,"Envelope")); header=ET.SubElement(root,q(SOAP12,"Header"))
    security=ET.SubElement(header,q(WSSE,"Security")); token=ET.SubElement(security,q(WSSE,"UsernameToken"))
    ET.SubElement(token,q(WSSE,"Username")).text=username; ET.SubElement(token,q(WSSE,"Password")).text=password
    body=ET.SubElement(root,q(SOAP12,"Body")); ET.SubElement(body,q(namespace,action))
    return ET.tostring(root)

class MotionTests(unittest.IsolatedAsyncioTestCase):
    async def test_true_then_false(self):
        manager=MotionManager(.02,60); sub=manager.create_subscription()
        await manager.trigger(); self.assertTrue((await manager.pull(sub.id,.01,10))[0].active)
        await asyncio.sleep(.03); self.assertFalse((await manager.pull(sub.id,.01,10))[0].active)

    async def test_repeated_motion_extends_timeout(self):
        manager=MotionManager(.04,60); sub=manager.create_subscription()
        await manager.trigger(); await manager.pull(sub.id,.01,10); await asyncio.sleep(.025); await manager.trigger()
        await asyncio.sleep(.025); self.assertTrue(manager.active)
        await asyncio.sleep(.025); self.assertFalse((await manager.pull(sub.id,.02,10))[0].active)

    async def test_long_poll_timeout(self):
        manager=MotionManager(1,60); sub=manager.create_subscription(); start=asyncio.get_running_loop().time()
        self.assertEqual(await manager.pull(sub.id,.02,10),[])
        self.assertGreaterEqual(asyncio.get_running_loop().time()-start,.018)

    async def test_multiple_subscriptions_receive_event(self):
        manager=MotionManager(1,60); one=manager.create_subscription(); two=manager.create_subscription()
        await manager.trigger()
        self.assertTrue((await manager.pull(one.id,.01,1))[0].active)
        self.assertTrue((await manager.pull(two.id,.01,1))[0].active)
        manager._clear_task.cancel()

    async def test_smtp_human_triggers_and_test_is_ignored(self):
        manager=MotionManager(1,60); sub=manager.create_subscription(); c=config()
        handler=Handler(c,asyncio.get_running_loop(),manager.trigger)
        email=b"From: camera@local\r\nTo: x@local\r\nSubject: Human Detection Alarm\r\n\r\nDetected"
        await handler.handle_DATA(None,None,SimpleNamespace(content=email,mail_from="camera@local",rcpt_tos=["x@local"]))
        await asyncio.sleep(.01); self.assertTrue((await manager.pull(sub.id,.1,1))[0].active)
        manager._clear_task.cancel()
        ignored=CameraEmail("camera",("x",),"IP Camera: SMTP Test","")
        self.assertFalse(should_trigger(ignored,c))

class XmlTests(unittest.TestCase):
    def test_event_properties_matches_notification_topic(self):
        properties=event_properties(SOAP12).decode(); event=notification(SimpleNamespace(active=True,timestamp="2026-01-01T00:00:00Z",sequence=1))
        self.assertIn("CellMotionDetector",properties); self.assertEqual(event.find(q(WSNT,"Topic")).text,MOTION_TOPIC)
        self.assertEqual(event.find(f".//{{{TT}}}SimpleItem[@Name='IsMotion']").attrib["Value"],"true")

    def test_subscription_has_bridge_address(self):
        manager=MotionManager(1,60); xml=subscription_response(manager,"http://bridge:8080",SOAP12).decode()
        self.assertIn("http://bridge:8080/onvif/subscriptions/",xml)

    def test_password_digest_auth_and_bad_password(self):
        nonce=b"1234567890123456"; created=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
        digest=base64.b64encode(hashlib.sha1(nonce+created.encode()+b"secret").digest()).decode()
        root=ET.Element("root"); token=ET.SubElement(root,q(WSSE,"UsernameToken"))
        ET.SubElement(token,q(WSSE,"Username")).text="protect"
        ET.SubElement(token,q(WSSE,"Password"),{"Type":"PasswordDigest"}).text=digest
        ET.SubElement(token,q(WSSE,"Nonce")).text=base64.b64encode(nonce).decode()
        ET.SubElement(token,q(WSU,"Created")).text=created
        self.assertTrue(authenticate(root,"protect","secret",300)); self.assertFalse(authenticate(root,"protect","wrong",300))

@unittest.skipIf(OnvifServer is None,"aiohttp is not installed")
class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.motion=MotionManager(1,60); self.server=OnvifServer(config(),self.motion)
        self.client=TestClient(TestServer(self.server.app())); await self.client.start_server()
    async def asyncTearDown(self): await self.client.close()

    async def test_device_urls_rewritten_to_bridge(self):
        response=await self.client.post("/onvif/device_service",data=soap("GetCapabilities","http://www.onvif.org/ver10/device/wsdl"))
        text=await response.text(); self.assertEqual(response.status,200)
        self.assertIn("http://192.168.88.10:8080/onvif/events_service",text)
        self.assertNotIn("192.168.88.20/onvif",text)

    async def test_invalid_auth_rejected(self):
        response=await self.client.post("/onvif/events_service",data=soap("GetEventProperties",password="wrong"))
        self.assertEqual(response.status,401); self.assertIn("NotAuthorized",await response.text())

    async def test_create_and_pull_messages(self):
        created=await self.client.post("/onvif/events_service",data=soap("CreatePullPointSubscription"))
        text=await created.text(); sid=text.split("/subscriptions/")[1].split("<")[0]
        await self.motion.trigger()
        pull=await self.client.post(f"/onvif/subscriptions/{sid}",data=soap("PullMessages"))
        body=await pull.text(); self.assertIn('Name="IsMotion" Value="true"',body)
        self.motion._clear_task.cancel()

    async def test_get_stream_uri_remains_upstream(self):
        import cameraonvif.onvif.server as module
        original=module.proxy_media
        upstream=envelope(ET.Element(q("http://www.onvif.org/ver10/media/wsdl","GetStreamUriResponse")))
        root=ET.fromstring(upstream); body=root.find(q(SOAP12,"Body"))[0]
        media=ET.SubElement(body,q(TT,"MediaUri")); ET.SubElement(media,q(TT,"Uri")).text="rtsp://192.168.88.20:554/stream1"
        module.proxy_media=lambda *args:(200,ET.tostring(root),"application/soap+xml")
        try:
            response=await self.client.post("/onvif/media_service",data=soap("GetStreamUri","http://www.onvif.org/ver10/media/wsdl"))
            self.assertIn("rtsp://192.168.88.20:554/stream1",await response.text())
        finally: module.proxy_media=original
