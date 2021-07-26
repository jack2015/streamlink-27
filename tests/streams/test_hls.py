import os
import unittest

import pytest
import requests_mock

from streamlink.compat import is_py3, str
from streamlink.session import Streamlink
from streamlink.stream import hls
from streamlink.utils.crypto import AES, pad
from tests.mixins.stream_hls import EventedHLSStreamWriter, Playlist, Segment, Tag, TestMixinStreamHLS
from tests.mock import Mock, call, patch
from tests.resources import text


class TagKey(Tag):
    path = "encryption.key"

    def __init__(self, method="NONE", uri=None, iv=None, keyformat=None, keyformatversions=None):
        attrs = {"METHOD": method}
        if uri is not False:  # pragma: no branch
            attrs.update({"URI": lambda tag, namespace: tag.val_quoted_string(tag.url(namespace))})
        if iv is not None:  # pragma: no branch
            attrs.update({"IV": self.val_hex(iv)})
        if keyformat is not None:  # pragma: no branch
            attrs.update({"KEYFORMAT": self.val_quoted_string(keyformat)})
        if keyformatversions is not None:  # pragma: no branch
            attrs.update({"KEYFORMATVERSIONS": self.val_quoted_string(keyformatversions)})
        super(TagKey, self).__init__("EXT-X-KEY", attrs)
        self.uri = uri

    def url(self, namespace):
        return self.uri.format(namespace=namespace) if self.uri else super(TagKey, self).url(namespace)


class SegmentEnc(Segment):
    def __init__(self, num, key, iv, *args, **kwargs):
        padding = kwargs.pop("padding", b"")
        append = kwargs.pop("append", b"")
        super(SegmentEnc, self).__init__(num, *args, **kwargs)
        aesCipher = AES.new(key, AES.MODE_CBC, iv)
        padded = self.content + padding if padding else pad(self.content, AES.block_size, style="pkcs7")
        self.content_plain = self.content
        self.content = aesCipher.encrypt(padded) + append


class TestHLSStreamRepr(unittest.TestCase):
    def test_repr(self):
        session = Streamlink()

        stream = hls.HLSStream(session, "https://foo.bar/playlist.m3u8")
        self.assertEqual(repr(stream), "<HLSStream('https://foo.bar/playlist.m3u8', None)>")

        stream = hls.HLSStream(session, "https://foo.bar/playlist.m3u8", "https://foo.bar/master.m3u8")
        self.assertEqual(repr(stream), "<HLSStream('https://foo.bar/playlist.m3u8', 'https://foo.bar/master.m3u8')>")


class TestHLSVariantPlaylist(unittest.TestCase):
    @classmethod
    def get_master_playlist(cls, playlist):
        with text(playlist) as pl:
            return pl.read()

    def subject(self, playlist, options=None):
        with requests_mock.Mocker() as mock:
            url = "http://mocked/{0}/master.m3u8".format(self.id())
            content = self.get_master_playlist(playlist)
            mock.get(url, text=content)

            session = Streamlink(options)

            return hls.HLSStream.parse_variant_playlist(session, url)

    def test_variant_playlist(self):
        streams = self.subject("hls/test_master.m3u8")
        self.assertEqual(
            [str(key) for key in streams.keys()],
            [u"720p", u"720p_alt", u"480p", u"360p", u"160p", u"1080p (source)", u"90k"],
            "Finds all streams in master playlist",
        )
        self.assertTrue(all([isinstance(stream, hls.HLSStream) for stream in streams.values()]), "Returns HLSStream instances")


class EventedHLSReader(hls.HLSStreamReader):
    __writer__ = EventedHLSStreamWriter


class EventedHLSStream(hls.HLSStream):
    __reader__ = EventedHLSReader


@patch("streamlink.stream.hls.HLSStreamWorker.wait", Mock(return_value=True))
class TestHLSStream(TestMixinStreamHLS, unittest.TestCase):
    def get_session(self, options=None, *args, **kwargs):
        session = super(TestHLSStream, self).get_session(options)
        session.set_option("hls-live-edge", 3)

        return session

    def test_offset_and_duration(self):
        thread, segments = self.subject(
            [Playlist(1234, [Segment(0), Segment(1, duration=0.5), Segment(2, duration=0.5), Segment(3)], end=True)],
            streamoptions={"start_offset": 1, "duration": 1},
        )

        data = self.await_read(read_all=True)
        self.assertEqual(data, self.content(segments, cond=lambda s: 0 < s.num < 3), "Respects the offset and duration")
        self.assertTrue(all([self.called(s) for s in segments.values() if 0 < s.num < 3]), "Downloads second and third segment")
        self.assertFalse(any([self.called(s) for s in segments.values() if 0 > s.num > 3]), "Skips other segments")


@patch("streamlink.stream.hls.HLSStreamWorker.wait", Mock(return_value=True))
class TestHLSStreamEncrypted(TestMixinStreamHLS, unittest.TestCase):
    __stream__ = EventedHLSStream

    def get_session(self, options=None, *args, **kwargs):
        session = super(TestHLSStreamEncrypted, self).get_session(options)
        session.set_option("hls-live-edge", 3)
        session.set_option("http-headers", {"X-FOO": "BAR"})

        return session

    def gen_key(self, aes_key=None, aes_iv=None, method="AES-128", uri=None, keyformat="identity", keyformatversions=1):
        aes_key = aes_key or os.urandom(16)
        aes_iv = aes_iv or os.urandom(16)

        key = TagKey(method=method, uri=uri, iv=aes_iv, keyformat=keyformat, keyformatversions=keyformatversions)
        self.mock("GET", key.url(self.id()), content=aes_key)

        return aes_key, aes_iv, key

    def test_hls_encrypted_aes128(self):
        aesKey, aesIv, key = self.gen_key()

        # noinspection PyTypeChecker
        thread, segments = self.subject(
            [
                Playlist(0, [key] + [SegmentEnc(num, aesKey, aesIv) for num in range(0, 4)]),
                Playlist(4, [key] + [SegmentEnc(num, aesKey, aesIv) for num in range(4, 8)], end=True),
            ]
        )

        self.await_write(3 + 4)
        data = self.await_read(read_all=True)
        expected = self.content(segments, prop="content_plain", cond=lambda s: s.num >= 1)
        self.assertEqual(data, expected, "Decrypts the AES-128 identity stream")
        self.assertTrue(self.called(key), "Downloads encryption key")
        self.assertEqual(self.get_mock(key).last_request._request.headers.get("X-FOO"), "BAR")
        self.assertFalse(any([self.called(s) for s in segments.values() if s.num < 1]), "Skips first segment")
        self.assertTrue(all([self.called(s) for s in segments.values() if s.num >= 1]), "Downloads all remaining segments")
        self.assertEqual(self.get_mock(segments[1]).last_request._request.headers.get("X-FOO"), "BAR")

    def test_hls_encrypted_aes128_key_uri_override(self):
        aesKey, aesIv, key = self.gen_key(uri="http://real-mocked/{namespace}/encryption.key?foo=bar")
        aesKeyInvalid = bytes([ord(aesKey[i : i + 1]) ^ 0xFF for i in range(16)])
        _, __, key_invalid = self.gen_key(aesKeyInvalid, aesIv, uri="http://mocked/{namespace}/encryption.key?foo=bar")

        # noinspection PyTypeChecker
        thread, segments = self.subject(
            [
                Playlist(0, [key_invalid] + [SegmentEnc(num, aesKey, aesIv) for num in range(0, 4)]),
                Playlist(4, [key_invalid] + [SegmentEnc(num, aesKey, aesIv) for num in range(4, 8)], end=True),
            ],
            options={"hls-segment-key-uri": "{scheme}://real-{netloc}{path}?{query}"},
        )

        self.await_write(3 + 4)
        data = self.await_read(read_all=True)
        expected = self.content(segments, prop="content_plain", cond=lambda s: s.num >= 1)
        self.assertEqual(data, expected, "Decrypts stream from custom key")
        self.assertFalse(self.called(key_invalid), "Skips encryption key")
        self.assertTrue(self.called(key), "Downloads custom encryption key")
        self.assertEqual(self.get_mock(key).last_request._request.headers.get("X-FOO"), "BAR")

    @patch("streamlink.stream.hls.log")
    def test_hls_encrypted_aes128_incorrect_block_length(self, mock_log):
        aesKey, aesIv, key = self.gen_key()

        # noinspection PyTypeChecker
        thread, segments = self.subject(
            [
                Playlist(
                    0,
                    [key]
                    + [
                        SegmentEnc(0, aesKey, aesIv, append=b"?" * 1),
                        SegmentEnc(1, aesKey, aesIv, append=b"?" * (AES.block_size - 1)),
                    ],
                    end=True,
                )
            ]
        )

        self.await_write(2)
        data = self.await_read(read_all=True)
        expected = self.content(segments, prop="content_plain")
        self.assertEqual(data, expected, "Removes garbage data from segments")
        self.assertIn(call("Cutting off 1 bytes of garbage before decrypting"), mock_log.debug.mock_calls)
        self.assertIn(call("Cutting off 15 bytes of garbage before decrypting"), mock_log.debug.mock_calls)

    def test_hls_encrypted_aes128_incorrect_padding_length(self):
        aesKey, aesIv, key = self.gen_key()

        padding = b"\x00" * (AES.block_size - len(b"[0]"))
        self.subject([Playlist(0, [key, SegmentEnc(0, aesKey, aesIv, padding=padding)], end=True)])

        with self.assertRaises(ValueError) as cm:
            self.await_write()
        self.assertEqual(str(cm.exception), "Padding is incorrect.", "Crypto.Util.Padding.unpad exception")

    def test_hls_encrypted_aes128_incorrect_padding_content(self):
        aesKey, aesIv, key = self.gen_key()

        padding = (b"\x00" * (AES.block_size - len(b"[0]") - 1)) + bytes([AES.block_size])
        with self.assertRaises(ValueError) as cm:
            self.subject([Playlist(0, [key, SegmentEnc(0, aesKey, aesIv, padding=padding)], end=True)])
            self.await_write()
        if is_py3:
            self.assertEqual(str(cm.exception), "PKCS#7 padding is incorrect.", "Crypto.Util.Padding.unpad exception")
        else:
            self.assertEqual(str(cm.exception), "Data must be padded to 16 byte boundary in CBC mode",
                             "streamlink.utils.crypto.unpad exception")


@patch("streamlink.stream.hls.HLSStreamWorker.wait", Mock(return_value=True))
@patch("streamlink.stream.hls.HLSStreamWriter.run", Mock(return_value=True))
class TestHlsPlaylistReloadTime(TestMixinStreamHLS, unittest.TestCase):
    segments = [Segment(0, "", 11), Segment(1, "", 7), Segment(2, "", 5), Segment(3, "", 3)]

    def get_session(self, options=None, reload_time=None, *args, **kwargs):
        return super(TestHlsPlaylistReloadTime, self).get_session(
            dict(options or {}, **{"hls-live-edge": 3, "hls-playlist-reload-time": reload_time})
        )

    def subject(self, *args, **kwargs):
        thread, _ = super(TestHlsPlaylistReloadTime, self).subject(*args, **kwargs)
        self.await_read(read_all=True)

        return thread.reader.worker.playlist_reload_time

    def test_hls_playlist_reload_time_default(self):
        time = self.subject([Playlist(0, self.segments, end=True, targetduration=4)], reload_time="default")
        self.assertEqual(time, 4, "default sets the reload time to the playlist's target duration")

    def test_hls_playlist_reload_time_segment(self):
        time = self.subject([Playlist(0, self.segments, end=True, targetduration=4)], reload_time="segment")
        self.assertEqual(time, 3, "segment sets the reload time to the playlist's last segment")

    def test_hls_playlist_reload_time_segment_no_segments(self):
        time = self.subject([Playlist(0, [], end=True, targetduration=4)], reload_time="segment")
        self.assertEqual(time, 4, "segment sets the reload time to the targetduration if no segments are available")

    def test_hls_playlist_reload_time_segment_no_segments_no_targetduration(self):
        time = self.subject([Playlist(0, [], end=True, targetduration=0)], reload_time="segment")
        self.assertEqual(time, 6, "sets reload time to 6 seconds when no segments and no targetduration are available")

    def test_hls_playlist_reload_time_live_edge(self):
        time = self.subject([Playlist(0, self.segments, end=True, targetduration=4)], reload_time="live-edge")
        self.assertEqual(time, 8, "live-edge sets the reload time to the sum of the number of segments of the live-edge")

    def test_hls_playlist_reload_time_live_edge_no_segments(self):
        time = self.subject([Playlist(0, [], end=True, targetduration=4)], reload_time="live-edge")
        self.assertEqual(time, 4, "live-edge sets the reload time to the targetduration if no segments are available")

    def test_hls_playlist_reload_time_live_edge_no_segments_no_targetduration(self):
        time = self.subject([Playlist(0, [], end=True, targetduration=0)], reload_time="live-edge")
        self.assertEqual(time, 6, "sets reload time to 6 seconds when no segments and no targetduration are available")

    def test_hls_playlist_reload_time_number(self):
        time = self.subject([Playlist(0, self.segments, end=True, targetduration=4)], reload_time="2")
        self.assertEqual(time, 2, "number values override the reload time")

    def test_hls_playlist_reload_time_number_invalid(self):
        time = self.subject([Playlist(0, self.segments, end=True, targetduration=4)], reload_time="0")
        self.assertEqual(time, 4, "invalid number values set the reload time to the playlist's targetduration")

    def test_hls_playlist_reload_time_no_target_duration(self):
        time = self.subject([Playlist(0, self.segments, end=True, targetduration=0)], reload_time="default")
        self.assertEqual(time, 8, "uses the live-edge sum if the playlist is missing the targetduration data")

    def test_hls_playlist_reload_time_no_data(self):
        time = self.subject([Playlist(0, [], end=True, targetduration=0)], reload_time="default")
        self.assertEqual(time, 6, "sets reload time to 6 seconds when no data is available")


@patch("streamlink.stream.hls.FFMPEGMuxer.is_usable", Mock(return_value=True))
class TestHlsExtAudio(unittest.TestCase):
    @property
    def playlist(self):
        with text("hls/test_2.m3u8") as pl:
            return pl.read()

    def run_streamlink(self, playlist, audio_select=None):
        streamlink = Streamlink()

        if audio_select:
            streamlink.set_option("hls-audio-select", audio_select)

        master_stream = hls.HLSStream.parse_variant_playlist(streamlink, playlist)

        return master_stream

    def test_hls_ext_audio_not_selected(self):
        master_url = "http://mocked/path/master.m3u8"

        with requests_mock.Mocker() as mock:
            mock.get(master_url, text=self.playlist)
            master_stream = self.run_streamlink(master_url)["video"]

        with pytest.raises(AttributeError):
            master_stream.substreams

        assert master_stream.url == "http://mocked/path/playlist.m3u8"

    def test_hls_ext_audio_en(self):
        """
        m3u8 with ext audio but no options should not download additional streams
        :return:
        """

        master_url = "http://mocked/path/master.m3u8"
        expected = ["http://mocked/path/playlist.m3u8", "http://mocked/path/en.m3u8"]

        with requests_mock.Mocker() as mock:
            mock.get(master_url, text=self.playlist)
            master_stream = self.run_streamlink(master_url, "en")

        substreams = master_stream["video"].substreams
        result = [x.url for x in substreams]

        # Check result
        self.assertEqual(result, expected)

    def test_hls_ext_audio_es(self):
        """
        m3u8 with ext audio but no options should not download additional streams
        :return:
        """

        master_url = "http://mocked/path/master.m3u8"
        expected = ["http://mocked/path/playlist.m3u8", "http://mocked/path/es.m3u8"]

        with requests_mock.Mocker() as mock:
            mock.get(master_url, text=self.playlist)
            master_stream = self.run_streamlink(master_url, "es")

        substreams = master_stream["video"].substreams

        result = [x.url for x in substreams]

        # Check result
        self.assertEqual(result, expected)

    def test_hls_ext_audio_all(self):
        """
        m3u8 with ext audio but no options should not download additional streams
        :return:
        """

        master_url = "http://mocked/path/master.m3u8"
        expected = ["http://mocked/path/playlist.m3u8", "http://mocked/path/en.m3u8", "http://mocked/path/es.m3u8"]

        with requests_mock.Mocker() as mock:
            mock.get(master_url, text=self.playlist)
            master_stream = self.run_streamlink(master_url, "en,es")

        substreams = master_stream["video"].substreams

        result = [x.url for x in substreams]

        # Check result
        self.assertEqual(result, expected)

    def test_hls_ext_audio_wildcard(self):
        master_url = "http://mocked/path/master.m3u8"
        expected = ["http://mocked/path/playlist.m3u8", "http://mocked/path/en.m3u8", "http://mocked/path/es.m3u8"]

        with requests_mock.Mocker() as mock:
            mock.get(master_url, text=self.playlist)
            master_stream = self.run_streamlink(master_url, "*")

        substreams = master_stream["video"].substreams

        result = [x.url for x in substreams]

        # Check result
        self.assertEqual(result, expected)
