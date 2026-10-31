"""YouTube access without an LLM: channel RSS feeds and the Data API (v3)."""

import http.client
import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
API_URL = "https://www.googleapis.com/youtube/v3/{}"
TIMEOUT_S = 15

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


FEED_ERRORS_BEFORE_BLOCK = 3  # feeds failing with an HTTP error in one run (2026-10-31: 14/20 gave 404/500)

log = logging.getLogger("ytsum.digest")


class FeedError(Exception):
    """A channel feed could not be fetched or parsed; status is the HTTP code, if there was one."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class YouTubeBlocked(Exception):
    """YouTube is blocking this IP (Google /sorry page, HTTP 429, ...): the run must stop asking."""


class YouTubeApiError(Exception):
    """The Data API returned an error (bad key, quota exceeded, ...)."""


@dataclass
class FeedEntry:
    video_id: str
    channel_id: str
    channel_name: str
    title: str
    published: str
    description: str


@dataclass
class VideoMeta:
    video_id: str
    duration_s: int
    is_live: bool
    view_count: int


def parse_feed(xml_text: str) -> list[FeedEntry]:
    root = ET.fromstring(xml_text)
    entries = []
    for e in root.findall("atom:entry", NS):
        entries.append(FeedEntry(
            video_id=e.findtext("yt:videoId", "", NS),
            channel_id=e.findtext("yt:channelId", "", NS),
            channel_name=e.findtext("atom:author/atom:name", "", NS),
            title=e.findtext("atom:title", "", NS),
            published=e.findtext("atom:published", "", NS),
            description=(e.findtext("media:group/media:description", "", NS) or "").strip(),
        ))
    return entries


_sleep = time.sleep  # tests replace it, so no test waits for real


class Pacer:
    """A random wait within bounds (seconds) before each request of one kind, except the first."""

    def __init__(self, bounds: tuple[float, float], kind: str, sleep=None):
        self.low, self.high = bounds
        self.kind, self.sleep, self.started = kind, sleep, False

    def wait(self) -> None:
        if self.started and self.high > 0:
            delay = random.uniform(self.low, self.high)
            log.info("waiting %.1f s before the next %s request", delay, self.kind)
            (self.sleep or _sleep)(delay)
        self.started = True


def _is_sorry(url: Optional[str]) -> bool:
    parsed = urllib.parse.urlparse(url or "")
    return (parsed.hostname or "").endswith("google.com") and parsed.path.startswith("/sorry")


def fetch_feed(channel_id: str) -> list[FeedEntry]:
    """
    Raises:
        YouTubeBlocked: on HTTP 429 or a redirect to Google's /sorry page.
        FeedError: for anything else.
    """
    url = FEED_URL.format(urllib.parse.quote(channel_id))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
            if _is_sorry(r.geturl()):
                raise YouTubeBlocked(f"feed for {channel_id}: redirected to {r.geturl()}")
            return parse_feed(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 or _is_sorry(e.geturl()):
            raise YouTubeBlocked(f"feed for {channel_id}: HTTP {e.code} from {e.geturl()}") from e
        raise FeedError(f"feed for {channel_id}: {e}", status=e.code) from e
    except (OSError, http.client.HTTPException, ValueError, ET.ParseError) as e:
        # OSError covers URLError, timeouts and connection resets; ValueError covers bad UTF-8.
        raise FeedError(f"feed for {channel_id}: {e}") from e


class Feeds:
    """Feed reads for one run: spaced out, and a block once FEED_ERRORS_BEFORE_BLOCK feeds fail over HTTP."""

    def __init__(self, delay_s: tuple[float, float], sleep=None):
        self.pacer = Pacer(delay_s, "feed", sleep)
        self.http_errors = 0

    def fetch(self, channel_id: str) -> list[FeedEntry]:
        self.pacer.wait()
        try:
            return fetch_feed(channel_id)
        except FeedError as e:
            if e.status is not None:
                self.http_errors += 1
                if self.http_errors >= FEED_ERRORS_BEFORE_BLOCK:
                    raise YouTubeBlocked(f"{self.http_errors} feeds failed over HTTP this run, last: {e}") from e
            raise


_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_iso8601_duration(s: str) -> int:
    m = _DURATION.match(s or "")
    if not m:
        return 0
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + sec


def api_get(path: str, params: dict, api_key: str) -> dict:
    query = urllib.parse.urlencode({**params, "key": api_key})
    try:
        with urllib.request.urlopen(f"{API_URL.format(path)}?{query}", timeout=TIMEOUT_S) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        message = str(e)
        try:
            message = json.load(e.fp)["error"]["message"]
        except Exception:
            pass
        raise YouTubeApiError(f"{path}: HTTP {e.code}: {message}") from e
    except (OSError, http.client.HTTPException, ValueError) as e:
        # Connection resets, timeouts, and non-JSON replies (ValueError includes JSONDecodeError).
        raise YouTubeApiError(f"{path}: {e}") from e


def fetch_video_meta(video_ids: list[str], api_key: str) -> dict[str, VideoMeta]:
    meta = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        data = api_get("videos", {
            "part": "contentDetails,liveStreamingDetails,statistics,snippet",
            "id": ",".join(batch),
        }, api_key)
        for item in data.get("items", []):
            meta[item["id"]] = VideoMeta(
                video_id=item["id"],
                duration_s=parse_iso8601_duration(item.get("contentDetails", {}).get("duration", "")),
                is_live="liveStreamingDetails" in item
                        or item.get("snippet", {}).get("liveBroadcastContent", "none") != "none",
                view_count=int(item.get("statistics", {}).get("viewCount", 0)),
            )
    return meta


def skip_reason(meta: VideoMeta, shorts_max_seconds: int) -> Optional[str]:
    if meta.is_live:
        return "livestream"
    if meta.duration_s < shorts_max_seconds:
        return "short"
    return None
