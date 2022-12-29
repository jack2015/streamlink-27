"""
$description Russian live-streaming platform for gaming and esports, owned by VKontakte.
$url vkplay.live
$type live
"""

import logging
import re

from streamlink.plugin import Plugin, pluginmatcher
from streamlink.plugin.api import validate
from streamlink.stream.hls import HLSStream

log = logging.getLogger(__name__)


@pluginmatcher(re.compile(
    r"https?://vkplay\.live/(?P<channel_name>\w+)/?$",
))
class VKplay(Plugin):
    API_URL = "https://api.vkplay.live/v1"

    def _get_streams(self):
        self.author = self.match.group("channel_name")
        log.debug("Channel name: {0}".format(self.author))

        data = self.session.http.get(
            "{0}/blog/{1}/public_video_stream".format(self.API_URL, self.author),
            headers={"Referer": self.url},
            acceptable_status=(200, 404),
            schema=validate.Schema(
                validate.parse_json(),
                validate.any(
                    validate.all(
                        {"error": validate.text, "error_description": validate.text},
                        validate.get("error_description"),
                    ),
                    validate.all(
                        {
                            "category": {
                                "title": validate.text,
                            },
                            "title": validate.text,
                            "data": validate.any(
                                [
                                    validate.all(
                                        {
                                            "vid": validate.text,
                                            "playerUrls": [
                                                validate.all(
                                                    {
                                                        "type": validate.text,
                                                        "url": validate.any("", validate.url()),
                                                    },
                                                    validate.union_get("type", "url"),
                                                ),
                                            ],
                                        },
                                        validate.union_get("vid", "playerUrls"),
                                    ),
                                ],
                                [],
                            ),
                        },
                        validate.union_get(
                            ("category", "title"),
                            "title",
                            ("data", 0),
                        ),
                    ),
                ),
            ),
        )
        if type(data) is validate.text:
            log.error(data)
            return

        self.category, self.title, streamdata = data
        if not streamdata:
            return

        self.id, streams = streamdata

        for streamtype, streamurl in streams:
            if streamurl and streamtype == "live_hls":
                return HLSStream.parse_variant_playlist(self.session, streamurl)


__plugin__ = VKplay
