"""Register built-in sinks (order: stop marker → log → queue → meta)."""

from errors.sinks import (
    LogSink,
    MetaSink,
    QueueSink,
    StopMarkerSink,
    register_sink,
)

register_sink(StopMarkerSink())
register_sink(LogSink())
register_sink(QueueSink())
register_sink(MetaSink())
