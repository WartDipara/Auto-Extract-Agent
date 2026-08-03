"""Register device handlers in match order (first match wins)."""

from prep.device_handlers.mumu import MuMuHandler
from prep.device_handlers.xiaomi import XiaomiHandler
from prep.device_router import register

register(MuMuHandler())
register(XiaomiHandler())
