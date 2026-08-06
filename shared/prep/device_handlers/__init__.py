from .mumu import MuMuHandler
from .xiaomi import XiaomiHandler
from ..device_router import register

_registered = False


def register_device_handlers() -> None:
    global _registered
    if _registered:
        return
    register(MuMuHandler())
    register(XiaomiHandler())
    _registered = True
