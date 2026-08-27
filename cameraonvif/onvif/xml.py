from datetime import datetime, timezone
from xml.etree import ElementTree as ET
SOAP12="http://www.w3.org/2003/05/soap-envelope"; SOAP11="http://schemas.xmlsoap.org/soap/envelope/"
TDS="http://www.onvif.org/ver10/device/wsdl"; TRT="http://www.onvif.org/ver10/media/wsdl"
TEV="http://www.onvif.org/ver10/events/wsdl"; TT="http://www.onvif.org/ver10/schema"
WSNT="http://docs.oasis-open.org/wsn/b-2"; WSA="http://www.w3.org/2005/08/addressing"
WSTOP="http://docs.oasis-open.org/wsn/t-1"; TOPICS="http://www.onvif.org/ver10/topics"
TOPIC_DIALECT="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet"
MOTION_TOPIC="tns1:RuleEngine/CellMotionDetector/Motion"
TER="http://www.onvif.org/ver10/error"
for prefix,uri in {"s":SOAP12,"tds":TDS,"trt":TRT,"tev":TEV,"tt":TT,"wsnt":WSNT,"wsa5":WSA,"wstop":WSTOP,"tns1":TOPICS}.items(): ET.register_namespace(prefix,uri)
def q(ns,name): return f"{{{ns}}}{name}"
def utc_now(): return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
def parse(data): return ET.fromstring(data)
def envelope(child, soap_ns=SOAP12):
    root=ET.Element(q(soap_ns,"Envelope")); ET.SubElement(root,q(soap_ns,"Header")); ET.SubElement(root,q(soap_ns,"Body")).append(child)
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)
def operation(root):
    soap=root.tag[1:].split("}",1)[0]; body=root.find(q(soap,"Body"))
    if body is None or not len(body): raise ValueError("SOAP Body is empty")
    return body[0].tag.rsplit("}",1)[-1],body[0],soap
def fault(reason,soap_ns=SOAP12,subcode="ter:ActionNotSupported"):
    node=ET.Element(q(soap_ns,"Fault"))
    if soap_ns==SOAP12:
        code=ET.SubElement(node,q(soap_ns,"Code")); ET.SubElement(code,q(soap_ns,"Value")).text="s:Sender"
        sub=ET.SubElement(code,q(soap_ns,"Subcode")); value=ET.SubElement(sub,q(soap_ns,"Value"),{"xmlns:ter":TER}); value.text=subcode
        rsn=ET.SubElement(node,q(soap_ns,"Reason")); ET.SubElement(rsn,q(soap_ns,"Text")).text=reason
    else: ET.SubElement(node,"faultcode").text="s:Client"; ET.SubElement(node,"faultstring").text=reason
    return envelope(node,soap_ns)
