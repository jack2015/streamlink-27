Twitch
======

Authentication
--------------

Official authentication support for Twitch via the ``--twitch-oauth-token`` and ``--twitch-oauth-authenticate`` CLI arguments
had to be disabled in Streamlink's :ref:`1.3.0 release in November 2019 <changelog:streamlink 1.3.0 (2019-11-22)>` and both
arguments were finally removed in the :ref:`1.27.1.0 release in December 2020 <changelog:streamlink 1.27.1.0 (2020-12-22)>` due to
`restrictive changes`_ on Twitch's private REST API which prevented proper authentication flows from third party applications
like Streamlink.

The issue was that authentication data generated from third party applications could not be sent while acquiring streaming
access tokens which are required for watching streams. Only authentication data generated by Twitch's website was accepted by
the Twitch API. Later on in January 2021, Twitch moved the respective API endpoints to their GraphQL API which was already
in use by their website for several years and shut down the old, private REST API.

This means that authentication data, aka. the "OAuth token", needs to be read from the web browser after logging in on Twitch's
website and it then needs to be set as a certain request header on these API endpoints. This unfortunately can't be automated
easily by applications like Streamlink, so a new authentication feature was never implemented.

**In order to get the personal OAuth token from Twitch's website which identifies your account**, open Twitch.tv in your web
browser and after a successful login, open the developer tools by pressing :kbd:`F12` or :kbd:`CTRL+SHIFT+I`. Then navigate to
the "Console" tab or its equivalent of your web browser and execute the following JavaScript snippet, which reads the value of
the ``auth-token`` cookie, if it exists:

.. code-block:: javascript

    document.cookie.split("; ").find(item=>item.startsWith("auth-token="))?.split("=")[1]

Copy the resulting string consisting of 30 alphanumerical characters without any quotations.

The final ``Authorization`` header which will identify your account while requesting a streaming access token can then be set
via Streamlink's :option:`--http-header` or :option:`--twitch-api-header` CLI arguments. The former will set the header on any
HTTP request made by Streamlink, even HLS Streams, while the latter will only do that on Twitch API requests, which is what
should be done when authenticating and which is the reason why this CLI argument was added.

The value of the ``Authorization`` header must be in the format of ``OAuth YOUR_TOKEN``. Notice the space character in the
argument value, which requires quotation on command line shells:

.. code-block:: console

    $ streamlink "--twitch-api-header=Authorization=OAuth abcdefghijklmnopqrstuvwxyz0123" twitch.tv/CHANNEL best

The entire argument can optionally be added to Streamlink's (Twitch plugin specific)
:ref:`configuration file <cli:Plugin specific configuration file>`, which :ref:`configuration file <cli:Syntax>`:

.. code-block:: text

    twitch-api-header=Authorization=OAuth abcdefghijklmnopqrstuvwxyz0123


.. _restrictive changes: https://github.com/streamlink/streamlink/issues/2680#issuecomment-557605851


Embedded ads
------------

In 2019, Twitch has started sporadically embedding ads directly into streams in addition to their regular advertisement program
on their website which can only overlay ads. The embedded ads situation has been an ongoing thing since then and has been turned
off and on several times throughout the months and years, also with variations between regions, and it has recently been pushed
more and more aggressively with long pre-roll ads.

While this may be an annoyance for end-users who are used to using ad-blocker extensions in their web-browsers for blocking
regular overlaying ads, applications like Streamlink face another problem, namely stream discontinuities when there's a
transition between an ad and the regular stream content or another follow-up ad.

Since Streamlink does only output a single progressive stream from reading Twitch's segmented HLS stream, ads can cause issues
in certain players, as the output is not a cohesively encoded stream of audio and video data anymore during an ad transition.
One of the problematic players is :ref:`VLC <players:Players>`, which is known to crash during these stream discontinuities in
certain cases.

Unfortunately, entirely preventing embedded ads is not possible unless a loophole on Twitch gets discovered which can be
exploited. This has been the case a couple of times now and ad-workarounds have been implemented in Streamlink (see #3210) and
various ad-blockers, but the solutions did only last for a couple of weeks or even days until Twitch patched these exploits.

**To filter out ads and to prevent stream discontinuities in Streamlink's output**, the :option:`--twitch-disable-ads` argument
was introduced in :ref:`Streamlink 1.1.0 in 2019 <changelog:streamlink 1.1.0 (2019-03-31)>`, which filters out advertisement
segments from Twitch's HLS streams and pauses the stream output until regular content becomes available again. The filtering
logic has seen several iterations since then, with the latest big overhaul in
:ref:`Streamlink 1.7.0 in 2020 <changelog:streamlink 1.7.0 (2020-10-18)>`.

**In addition to that**, special API request headers can be set via :option:`--twitch-api-header` that can prevent ads from
being embedded into the stream, either :ref:`authentication data <cli/plugins/twitch:Authentication>` or other data discovered
by the community.


Low latency streaming
---------------------

Low latency streaming on Twitch can be enabled by setting the :option:`--twitch-low-latency` argument and (optionally)
configuring the :ref:`player <players:Players>` via :option:`--player-args` and reducing its own buffer to a bare minimum.

Setting :option:`--twitch-low-latency` will make Streamlink prefetch future HLS segments that are included in the HLS playlist
and which can be requested ahead of time. As soon as content becomes available, Streamlink can download it without having to
waste time on waiting for another HLS playlist refresh that might include new segments.

In addition to that, :option:`--twitch-low-latency` also reduces :option:`--hls-live-edge` to a value of at most ``2``, and it
also sets the :option:`--hls-segment-stream-data` argument.

:option:`--hls-live-edge` defines how many HLS segments Streamlink should stay behind the stream's live edge, so that it can
refresh playlists and download segments in time without causing buffering. Setting the value to ``1`` is not advised due to how
prefetching works.

:option:`--hls-segment-stream-data` lets Streamlink write the content of in-progress segment downloads to the output buffer
instead waiting for the entire segment to complete first before data gets written. Since HLS segments on Twitch have a playback
duration of 2 seconds for most streams, this further reduces output delay.

.. note::

    Low latency streams have to be enabled by the broadcasters on Twitch themselves. Regular streams can cause buffering issues
    with this option enabled due to the reduced :option:`--hls-live-edge` value.

    Unfortunately, there is no way to check whether a channel is streaming in low-latency mode before accessing the stream.

Player buffer tweaks
^^^^^^^^^^^^^^^^^^^^

Since players do have their own input buffer, depending on how much data the player wants to keep in its buffer before it starts
playing the stream, this can cause an unnecessary delay while trying to watch low latency streams. Player buffer sizes should
therefore be tweaked via the :option:`--player-args` CLI argument or via the player's configuration options.

The delay introduced by the player depends on the stream's bitrate and how much data is necessary to allow for a smooth playback
without causing any stuttering, e.g. when running out out available data.

Please refer to the player's own documentation for the available options.
