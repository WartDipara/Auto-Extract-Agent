"""Device handlers (match order: first wins)."""

from prep.device_handlers.mumu import MuMuHandler
from prep.device_handlers.xiaomi import XiaomiHandler
from prep.device_router import register

_registered = False


def register_device_handlers() -> None:
    global _registered
    if _registered:
        return
    register(MuMuHandler())
    register(XiaomiHandler())
    _registered = True
