import logging

from streamlink.stream.filtered import FilteredStream
from streamlink.stream.hls import HLSStreamReader, HLSStreamWriter

log = logging.getLogger(__name__)


class FilteredHLSStreamWriter(HLSStreamWriter):
    def should_filter_sequence(self, sequence):
        return False

    def write(self, sequence, result, *data):
        if not self.should_filter_sequence(sequence):
            log.debug("Writing segment {0} to output".format(sequence.num))
            try:
                return super(FilteredHLSStreamWriter, self).write(sequence, result, *data)
            finally:
                # unblock reader thread after writing data to the buffer
                if self.reader.is_paused():
                    log.info("Resuming stream output")
                    self.reader.resume()
        else:
            log.debug("Discarding segment {0}".format(sequence.num))

            # Read and discard any remaining HTTP response data in the response connection.
            # Unread data in the HTTPResponse connection blocks the connection from being released back to the pool.
            result.raw.drain_conn()

            # block reader thread if filtering out segments
            if not self.reader.is_paused():
                log.info("Filtering out segments and pausing stream output")
                self.reader.pause()


class FilteredHLSStreamReader(FilteredStream, HLSStreamReader):
    def __init__(self, *args, **kwargs):
        super(FilteredHLSStreamReader, self).__init__(*args, **kwargs)
