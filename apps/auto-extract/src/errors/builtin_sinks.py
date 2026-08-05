from errors.sinks import (
    LogSink,
    MetaSink,
    QueueSink,
    StopMarkerSink,
    register_sink,
)

_registered = False


def register_builtin_sinks() -> None:
    global _registered
    if _registered:
        return
    register_sink(StopMarkerSink())
    register_sink(LogSink())
    register_sink(QueueSink())
    register_sink(MetaSink())
    _registered = True
