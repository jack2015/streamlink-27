import json
import re

from streamlink.plugin import Plugin
from streamlink.stream import HLSStream

_url_re = re.compile(r"http(?:s)?://(?:\w+\.)?rtl.nl/video/(?P<uuid>.*?)\Z", re.IGNORECASE)


class RTLxl(Plugin):
    @classmethod
    def can_handle_url(cls, url):
        return _url_re.match(url)

    def _get_streams(self):
        match = _url_re.match(self.url)
        uuid = match.group("uuid")
        videourlfeed = self.session.http.get(
            'https://tm-videourlfeed.rtl.nl/api/url/{}?device=pc&drm&format=hls'.format(uuid)
        ).text

        videourlfeedjson = json.loads(videourlfeed)
        playlist_url = videourlfeedjson["url"]

        return HLSStream.parse_variant_playlist(self.session, playlist_url)


__plugin__ = RTLxl
