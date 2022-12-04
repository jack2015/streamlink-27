from threading import Event

from streamlink.stream.stream import StreamIO


class FilteredStream(StreamIO):
    """StreamIO mixin for being able to pause read calls while filtering content"""

    # buffer: Buffer

    def __init__(self, *args, **kwargs):
        self._event_filter = Event()
        self._event_filter.set()
        super(FilteredStream, self).__init__(*args, **kwargs)

    def read(self, *args, **kwargs):
        # type: () -> bytes
        read = super(FilteredStream, self).read
        while True:
            try:
                return read(*args, **kwargs)
            except (IOError, OSError):
                # wait indefinitely until filtering ends
                self._event_filter.wait()
                if self.buffer.closed:
                    return b""
                # if data is available, try reading again
                if self.buffer.length > 0:
                    continue
                # raise if not filtering and no data available
                raise

    def close(self):
        # type: () -> None
        super(FilteredStream, self).close()
        self._event_filter.set()

    def is_paused(self):
        # type: () -> bool
        return not self._event_filter.is_set()

    def pause(self):
        # type: () -> None
        self._event_filter.clear()

    def resume(self):
        # type: () -> None
        self._event_filter.set()

    def filter_wait(self, timeout=None):
        return self._event_filter.wait(timeout)
