from __future__ import annotations
import base64,hashlib,os
from datetime import datetime,timezone
from xml.etree import ElementTree as ET
import requests
from ..config import Config
from .auth import WSSE,WSU
from .xml import SOAP11,SOAP12,q
PASSWORD_DIGEST_URI="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
BASE64_URI="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"

def upstream_security(data:bytes,c:Config)->bytes:
    root=ET.fromstring(data); soap=root.tag[1:].split("}",1)[0]
    header=root.find(q(soap,"Header"))
    if header is None: header=ET.Element(q(soap,"Header")); root.insert(0,header)
    for old in list(header):
        if old.tag==q(WSSE,"Security"): header.remove(old)
    security=ET.SubElement(header,q(WSSE,"Security"),{q(soap,"mustUnderstand"):"true"}); token=ET.SubElement(security,q(WSSE,"UsernameToken"))
    ET.SubElement(token,q(WSSE,"Username")).text=c.camera_username
    nonce=os.urandom(16); created=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
    digest=base64.b64encode(hashlib.sha1(nonce+created.encode()+c.camera_password.encode()).digest()).decode()
    ET.SubElement(token,q(WSSE,"Password"),{"Type":PASSWORD_DIGEST_URI}).text=digest
    ET.SubElement(token,q(WSSE,"Nonce"),{"EncodingType":BASE64_URI}).text=base64.b64encode(nonce).decode()
    ET.SubElement(token,q(WSU,"Created")).text=created
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)

def proxy_media(data:bytes,content_type:str,soap_action:str|None,c:Config)->tuple[int,bytes,str]:
    headers={"Content-Type":content_type}
    if soap_action: headers["SOAPAction"]=soap_action
    response=requests.post(c.camera_media_url,data=upstream_security(data,c),headers=headers,timeout=15,verify=c.verify_upstream_tls)
    body=response.content
    # Rewrite upstream HTTP ONVIF service addresses while deliberately retaining RTSP URIs.
    if response.ok:
        try:
            root=ET.fromstring(body)
            for node in root.iter():
                if node.text and node.text.startswith(("http://","https://")) and "/onvif/" in node.text:
                    path="media_service" if "media" in node.text.lower() else "device_service"
                    node.text=f"{c.base_url}/onvif/{path}"
            body=ET.tostring(root,encoding="utf-8",xml_declaration=True)
        except ET.ParseError: pass
    return response.status_code,body,response.headers.get("Content-Type","application/soap+xml")
