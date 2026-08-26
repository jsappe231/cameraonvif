from __future__ import annotations
import re,time
from datetime import datetime,timezone
from xml.etree import ElementTree as ET
from ..motion import MotionEvent,MotionManager
from .xml import *

def duration_seconds(text:str|None,default=30.0)->float:
    if not text:return default
    match=re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)S)?",text)
    return float(match.group(1) or 0) if match else default

def termination(expires_at:float)->str:
    seconds=max(0,expires_at-time.monotonic())
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+seconds,timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def event_properties(soap):
    response=ET.Element(q(TEV,"GetEventPropertiesResponse"))
    ET.SubElement(response,q(TEV,"TopicNamespaceLocation")).text="http://www.onvif.org/onvif/ver10/topics/topicns.xml"
    fixed=ET.SubElement(response,q(WSNT,"FixedTopicSet")); fixed.text="true"
    topicset=ET.SubElement(response,q(TEV,"TopicSet"))
    rule=ET.SubElement(topicset,q(TOPICS,"RuleEngine"),{q(WSTOP,"topic"):"true"})
    cell=ET.SubElement(rule,q(TOPICS,"CellMotionDetector"),{q(WSTOP,"topic"):"true"})
    motion=ET.SubElement(cell,q(TOPICS,"Motion"),{q(WSTOP,"topic"):"true"})
    message=ET.SubElement(motion,q(TT,"MessageDescription"),{"IsProperty":"true"})
    data=ET.SubElement(message,q(TT,"Data")); ET.SubElement(data,q(TT,"SimpleItemDescription"),{"Name":"IsMotion","Type":"xs:boolean"})
    ET.SubElement(response,q(TEV,"TopicExpressionDialect")).text=TOPIC_DIALECT
    ET.SubElement(response,q(TEV,"MessageContentFilterDialect")).text="http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter"
    ET.SubElement(response,q(TEV,"MessageContentSchemaLocation")).text="http://www.onvif.org/onvif/ver10/schema/onvif.xsd"
    return envelope(response,soap)

def subscription_response(manager:MotionManager,base_url:str,soap:str):
    sub=manager.create_subscription(); response=ET.Element(q(TEV,"CreatePullPointSubscriptionResponse"))
    ref=ET.SubElement(response,q(TEV,"SubscriptionReference")); ET.SubElement(ref,q(WSA,"Address")).text=f"{base_url}/onvif/subscriptions/{sub.id}"
    ET.SubElement(response,q(TEV,"CurrentTime")).text=utc_now(); ET.SubElement(response,q(TEV,"TerminationTime")).text=termination(sub.expires_at)
    return envelope(response,soap)

def notification(event:MotionEvent):
    n=ET.Element(q(WSNT,"NotificationMessage"))
    topic=ET.SubElement(n,q(WSNT,"Topic"),{"Dialect":TOPIC_DIALECT,"xmlns:tns1":TOPICS}); topic.text=MOTION_TOPIC
    holder=ET.SubElement(n,q(WSNT,"Message"))
    msg=ET.SubElement(holder,q(TT,"Message"),{"UtcTime":event.timestamp,"PropertyOperation":"Changed"})
    source=ET.SubElement(msg,q(TT,"Source")); ET.SubElement(source,q(TT,"SimpleItem"),{"Name":"VideoSourceConfigurationToken","Value":"VideoSource_1"})
    data=ET.SubElement(msg,q(TT,"Data")); ET.SubElement(data,q(TT,"SimpleItem"),{"Name":"IsMotion","Value":str(event.active).lower()})
    return n

def pull_response(events:list[MotionEvent],soap,expires_at:float|None=None):
    response=ET.Element(q(TEV,"PullMessagesResponse")); ET.SubElement(response,q(TEV,"CurrentTime")).text=utc_now()
    ET.SubElement(response,q(TEV,"TerminationTime")).text=termination(expires_at) if expires_at else utc_now()
    for event in events: response.append(notification(event))
    return envelope(response,soap)
