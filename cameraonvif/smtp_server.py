from __future__ import annotations
import asyncio,email,hmac,logging,warnings
from dataclasses import dataclass
from email.message import Message
from typing import Any,Callable
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult,LoginPassword,SMTP
from .config import Config
LOGGER=logging.getLogger(__name__)

@dataclass(frozen=True)
class CameraEmail:
    sender:str; recipients:tuple[str,...]; subject:str; body:str
    @property
    def event_name(self): return self.subject.strip() or "Camera email alert"

def decode_header(value):
    parts=email.header.decode_header(value or ""); return "".join(p.decode(c or "utf-8",errors="replace") if isinstance(p,bytes) else p for p,c in parts).strip()
def decode_part(part:Message):
    raw=part.get_payload(decode=True)
    return (raw.decode(part.get_content_charset() or "utf-8",errors="replace") if raw is not None else str(part.get_payload() or ""))
def parse_email(content,sender,recipients):
    msg=email.message_from_bytes(content if isinstance(content,bytes) else content.encode())
    bodies=[]
    for part in msg.walk():
        if not part.is_multipart() and part.get_content_type() in {"text/plain","text/html"} and part.get_content_disposition()!="attachment": bodies.append(decode_part(part))
    return CameraEmail(sender or decode_header(msg.get("From")),recipients,decode_header(msg.get("Subject")),"\n".join(bodies))
def should_trigger(mail:CameraEmail,c:Config):
    subject,body=mail.subject.lower(),mail.body.lower()
    return not any(x.lower() in subject for x in c.ignore_subject_patterns) and (any(x.lower() in subject for x in c.match_subject_patterns) or any(x.lower() in body for x in c.match_body_patterns))

class Authenticator:
    def __init__(self,user,password): self.user=user.encode(); self.password=password.encode()
    def __call__(self,server,session,envelope,mechanism,data):
        ok=isinstance(data,LoginPassword) and hmac.compare_digest(data.login,self.user) and hmac.compare_digest(data.password,self.password)
        return AuthResult(success=ok,handled=ok,auth_data=data if ok else None)
class CameraSMTP(SMTP):
    async def smtp_AUTH(self,arg):
        legacy=bool(self.session and self.session.host_name and not self.session.extended_smtp)
        if legacy:self.session.extended_smtp=True
        try: await super().smtp_AUTH(arg)
        finally:
            if legacy:self.session.extended_smtp=False
class CameraController(Controller):
    def factory(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",UserWarning); return CameraSMTP(self.handler,**self.SMTP_kwargs)
class Handler:
    def __init__(self,c:Config,loop:asyncio.AbstractEventLoop,trigger:Callable):
        self.c=c; self.loop=loop; self.trigger=trigger
    async def handle_DATA(self,server,session,envelope):
        mail=parse_email(envelope.content,envelope.mail_from,tuple(envelope.rcpt_tos))
        LOGGER.info("Received SMTP alert: %s",mail.subject)
        if should_trigger(mail,self.c):
            asyncio.run_coroutine_threadsafe(self.trigger(),self.loop)
        else: LOGGER.info("Ignored SMTP message: %s",mail.subject)
        return "250 Message accepted"

def start_smtp(c:Config,loop,trigger):
    options={}
    if c.smtp_username:
        options={"authenticator":Authenticator(c.smtp_username,c.smtp_password),"auth_required":True,"auth_require_tls":False}
    else: options={"auth_exclude_mechanism":["LOGIN","PLAIN"]}
    controller=CameraController(Handler(c,loop,trigger),hostname=c.smtp_host,port=c.smtp_port,**options); controller.start()
    LOGGER.info("SMTP listening on %s:%s",c.smtp_host,c.smtp_port); return controller
