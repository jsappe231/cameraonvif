from datetime import datetime,timezone
from xml.etree import ElementTree as ET
from ..config import Config
from .xml import *

def response(action:str,c:Config,soap:str)->bytes:
    node=ET.Element(q(TDS,action+"Response"))
    if action=="GetCapabilities":
        caps=ET.SubElement(node,q(TDS,"Capabilities"))
        for name,path,ns in [("Device","device_service",TDS),("Media","media_service",TRT),("Events","events_service",TEV)]:
            child=ET.SubElement(caps,q(TT,name)); ET.SubElement(child,q(TT,"XAddr")).text=f"{c.base_url}/onvif/{path}"
            if name=="Events":
                child.set("WSSubscriptionPolicySupport","false"); child.set("WSPullPointSupport","true"); child.set("WSPausableSubscriptionManagerInterfaceSupport","false")
    elif action=="GetServices":
        for ns,path in [(TDS,"device_service"),(TRT,"media_service"),(TEV,"events_service")]:
            service=ET.SubElement(node,q(TDS,"Service")); ET.SubElement(service,q(TDS,"Namespace")).text=ns
            ET.SubElement(service,q(TDS,"XAddr")).text=f"{c.base_url}/onvif/{path}"
            version=ET.SubElement(service,q(TDS,"Version")); ET.SubElement(version,q(TT,"Major")).text="2"; ET.SubElement(version,q(TT,"Minor")).text="6"
    elif action=="GetDeviceInformation":
        for name,value in [("Manufacturer","CameraONVIF Bridge"),("Model","SMTP Motion Proxy"),("FirmwareVersion","1.0"),("SerialNumber",c.stable_uuid),("HardwareId","cameraonvif")]: ET.SubElement(node,q(TDS,name)).text=value
    elif action=="GetSystemDateAndTime":
        dt=datetime.now(timezone.utc); system=ET.SubElement(node,q(TDS,"SystemDateAndTime"))
        ET.SubElement(system,q(TT,"DateTimeType")).text="NTP"; ET.SubElement(system,q(TT,"DaylightSavings")).text="false"
        utc=ET.SubElement(system,q(TT,"UTCDateTime")); t=ET.SubElement(utc,q(TT,"Time"))
        for n,v in [("Hour",dt.hour),("Minute",dt.minute),("Second",dt.second)]: ET.SubElement(t,q(TT,n)).text=str(v)
        d=ET.SubElement(utc,q(TT,"Date"))
        for n,v in [("Year",dt.year),("Month",dt.month),("Day",dt.day)]: ET.SubElement(d,q(TT,n)).text=str(v)
    elif action=="GetScopes":
        for value in ["onvif://www.onvif.org/type/video_encoder","onvif://www.onvif.org/Profile/Streaming","onvif://www.onvif.org/name/CameraONVIF-Bridge",f"onvif://www.onvif.org/hardware/{c.stable_uuid}"]:
            scope=ET.SubElement(node,q(TDS,"Scopes")); ET.SubElement(scope,q(TT,"ScopeDef")).text="Fixed"; ET.SubElement(scope,q(TT,"ScopeItem")).text=value
    elif action=="GetHostname":
        info=ET.SubElement(node,q(TDS,"HostnameInformation")); ET.SubElement(info,q(TT,"FromDHCP")).text="false"; ET.SubElement(info,q(TT,"Name")).text="cameraonvif-bridge"
    elif action=="GetNetworkInterfaces":
        interface=ET.SubElement(node,q(TDS,"NetworkInterfaces"),{"token":"eth0"})
        ET.SubElement(interface,q(TT,"Enabled")).text="true"
        info=ET.SubElement(interface,q(TT,"Info")); ET.SubElement(info,q(TT,"Name")).text="eth0"
        ipv4=ET.SubElement(interface,q(TT,"IPv4")); ET.SubElement(ipv4,q(TT,"Enabled")).text="true"
        config=ET.SubElement(ipv4,q(TT,"Config"))
        manual=ET.SubElement(config,q(TT,"Manual")); ET.SubElement(manual,q(TT,"Address")).text=c.onvif_advertised_host
        ET.SubElement(manual,q(TT,"PrefixLength")).text=str(c.network_prefix_length)
        ET.SubElement(config,q(TT,"DHCP")).text="false"
    return envelope(node,soap)
