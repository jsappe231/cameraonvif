from __future__ import annotations
import asyncio,logging,time,uuid
from dataclasses import dataclass,field
LOGGER=logging.getLogger(__name__)

@dataclass
class MotionEvent:
    active: bool; timestamp: str; sequence: int

@dataclass
class Subscription:
    id: str; expires_at: float; queue: asyncio.Queue[MotionEvent]=field(default_factory=asyncio.Queue)

class MotionManager:
    def __init__(self,duration:float,ttl:float):
        self.duration=duration; self.ttl=ttl; self.active=False; self.sequence=0
        self.subscriptions:dict[str,Subscription]={}; self._clear_task:asyncio.Task|None=None
    def create_subscription(self)->Subscription:
        item=Subscription(uuid.uuid4().hex,time.monotonic()+self.ttl); self.subscriptions[item.id]=item
        LOGGER.info("Created PullPoint subscription %s",item.id); return item
    def get(self,sid:str)->Subscription|None:
        item=self.subscriptions.get(sid)
        if item and item.expires_at>time.monotonic(): return item
        if item: self.subscriptions.pop(sid,None)
        return None
    def renew(self,sid:str)->Subscription|None:
        item=self.get(sid)
        if item: item.expires_at=time.monotonic()+self.ttl
        return item
    def unsubscribe(self,sid:str)->bool: return self.subscriptions.pop(sid,None) is not None
    async def trigger(self)->None:
        if self._clear_task: self._clear_task.cancel()
        if not self.active:
            self.active=True; await self._publish(True); LOGGER.info("Synthetic motion ACTIVE")
        else: LOGGER.info("Synthetic motion extended")
        self._clear_task=asyncio.create_task(self._clear_after())
    async def _clear_after(self):
        try: await asyncio.sleep(self.duration)
        except asyncio.CancelledError: return
        self.active=False; await self._publish(False); LOGGER.info("Synthetic motion cleared")
    async def _publish(self,active:bool):
        from .onvif.xml import utc_now
        self.sequence+=1; event=MotionEvent(active,utc_now(),self.sequence)
        for item in list(self.subscriptions.values()):
            if self.get(item.id):
                await item.queue.put(event)
                LOGGER.info("Queued motion=%s for subscription %s",str(active).lower(),item.id)
    async def pull(self,sid:str,timeout:float,limit:int)->list[MotionEvent]:
        item=self.get(sid)
        if not item: raise KeyError(sid)
        events=[]
        try: events.append(await asyncio.wait_for(item.queue.get(),max(0,timeout)))
        except asyncio.TimeoutError: return []
        while len(events)<limit and not item.queue.empty(): events.append(item.queue.get_nowait())
        return events
