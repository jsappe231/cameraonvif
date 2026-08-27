from __future__ import annotations
import asyncio,json,logging
from xml.etree import ElementTree as ET
from aiohttp import web
from ..config import Config
from ..motion import MotionManager
from ..rtsp import RtspRelayRegistry
from .auth import authenticate,WSSE
from .device import response as device_response
from .events import duration_seconds,event_properties,pull_response,subscription_response,termination
from .upstream import proxy_media
from .xml import *
LOGGER=logging.getLogger(__name__)
DEVICE_ACTIONS={"GetCapabilities","GetServices","GetDeviceInformation","GetSystemDateAndTime","GetScopes","GetHostname","GetNetworkInterfaces"}

class OnvifServer:
    def __init__(self,c:Config,motion:MotionManager,relay:RtspRelayRegistry):
        self.c=c; self.motion=motion; self.relay=relay; self.smtp_running=False; self.upstream_camera=False
    def app(self):
        app=web.Application(client_max_size=2*1024*1024)
        app.router.add_get("/health",self.health)
        app.router.add_post("/debug/motion",self.debug_motion)
        app.router.add_post("/onvif/device_service",self.soap)
        app.router.add_post("/onvif/media_service",self.soap)
        app.router.add_post("/onvif/events_service",self.soap)
        app.router.add_post("/onvif/subscriptions/{sid}",self.soap)
        return app
    async def health(self,request):
        relay_health=await asyncio.to_thread(self.relay.health)
        return web.json_response({"status":"ok","upstreamCamera":self.upstream_camera,"smtp":self.smtp_running,"activeSubscriptions":len(self.motion.subscriptions),"motionActive":self.motion.active,"rtsp":relay_health})
    async def debug_motion(self,request):
        if not self.c.enable_debug_endpoints: raise web.HTTPNotFound()
        await self.motion.trigger(); return web.json_response({"motionActive":True})
    async def soap(self,request):
        data=await request.read()
        try:
            root=parse(data); action,node,soap=operation(root)
        except (ET.ParseError,ValueError) as error:
            return self.xml_response(fault(str(error)),400)
        LOGGER.info("%s requested on %s",action,request.path)
        if LOGGER.isEnabledFor(logging.DEBUG):
            clean=ET.fromstring(data)
            for security in clean.findall(f".//{{{WSSE}}}Security"): security.clear(); security.text="[redacted]"
            LOGGER.debug("SOAP request: %s",ET.tostring(clean,encoding="unicode"))
        if action!="GetSystemDateAndTime" and not authenticate(root,self.c.onvif_username,self.c.onvif_password,self.c.auth_clock_tolerance):
            LOGGER.warning("Rejected invalid ONVIF credentials for %s",action)
            return self.xml_response(fault("Invalid credentials",soap,"ter:NotAuthorized"),401)
        try:
            if request.path.endswith("device_service") and action in DEVICE_ACTIONS:
                return self.xml_response(device_response(action,self.c,soap))
            if request.path.endswith("media_service"):
                status,body,content_type=await asyncio.to_thread(proxy_media,data,request.content_type,request.headers.get("SOAPAction"),self.c,self.relay)
                self.upstream_camera=200 <= status < 500
                LOGGER.info("%s proxied to upstream camera",action)
                return web.Response(status=status,body=body,content_type=content_type.split(";")[0])
            if request.path.endswith("events_service"):
                if action=="GetEventProperties": return self.xml_response(event_properties(soap))
                if action=="CreatePullPointSubscription": return self.xml_response(subscription_response(self.motion,self.c.base_url,soap))
            if "/subscriptions/" in request.path:
                return await self.subscription(request,action,node,soap)
            return self.xml_response(fault(f"Unsupported SOAP action: {action}",soap),400)
        except KeyError:
            return self.xml_response(fault("Unknown or expired subscription",soap,"wsnt:ResourceUnknownFault"),404)
        except Exception:
            LOGGER.exception("SOAP action %s failed",action)
            return self.xml_response(fault(f"{action} failed",soap,"ter:Receiver"),502)
    async def subscription(self,request,action,node,soap):
        sid=request.match_info["sid"]
        if action=="PullMessages":
            subscription=self.motion.get(sid)
            if not subscription: raise KeyError(sid)
            timeout_node=next((x for x in node.iter() if x.tag.endswith("}Timeout")),None)
            limit_node=next((x for x in node.iter() if x.tag.endswith("}MessageLimit")),None)
            timeout=min(duration_seconds(timeout_node.text if timeout_node is not None else None),60)
            limit=max(1,min(int(limit_node.text if limit_node is not None and limit_node.text else 10),100))
            LOGGER.info("PullMessages long poll for subscription %s",sid)
            events=await self.motion.pull(sid,timeout,limit)
            for event in events: LOGGER.info("Delivered motion=%s to subscription %s",str(event.active).lower(),sid)
            return self.xml_response(pull_response(events,soap,subscription.expires_at))
        if action=="Renew":
            sub=self.motion.renew(sid)
            if not sub: raise KeyError(sid)
            response=ET.Element(q(WSNT,"RenewResponse")); ET.SubElement(response,q(WSNT,"TerminationTime")).text=termination(sub.expires_at)
            return self.xml_response(envelope(response,soap))
        if action=="Unsubscribe":
            if not self.motion.unsubscribe(sid): raise KeyError(sid)
            return self.xml_response(envelope(ET.Element(q(WSNT,"UnsubscribeResponse")),soap))
        return self.xml_response(fault(f"Unsupported subscription action: {action}",soap),400)
    @staticmethod
    def xml_response(body,status=200):
        return web.Response(status=status,body=body,content_type="application/soap+xml")
