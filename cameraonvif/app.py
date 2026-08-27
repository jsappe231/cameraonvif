from __future__ import annotations
import asyncio,logging,os,signal
from aiohttp import web
from .config import Config
from .motion import MotionManager
from .rtsp import RtspRelayRegistry
from .onvif.server import OnvifServer
from .smtp_server import start_smtp

async def run(c:Config):
    motion=MotionManager(c.motion_duration,c.subscription_ttl)
    relay=RtspRelayRegistry(c); server=OnvifServer(c,motion,relay)
    runner=web.AppRunner(server.app()); await runner.setup()
    site=web.TCPSite(runner,c.onvif_bind_host,c.onvif_port); await site.start()
    smtp=start_smtp(c,asyncio.get_running_loop(),motion.trigger); server.smtp_running=True
    logging.getLogger(__name__).info("ONVIF bridge listening on %s:%s",c.onvif_bind_host,c.onvif_port)
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT): loop.add_signal_handler(sig,stop.set)
    try: await stop.wait()
    finally: smtp.stop(); await runner.cleanup()

def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper(),format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try: asyncio.run(run(Config.from_env()))
    except Exception:
        logging.getLogger(__name__).exception("Bridge stopped"); return 1
    return 0
if __name__=="__main__": raise SystemExit(main())
