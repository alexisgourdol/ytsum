"""Tests for the channel list file"""

from youtube_summarizer.digest import channels as ch


def test_channels_roundtrip():
    chs = [
        ch.Channel("UC1", 'Nate Herk | AI "Automation"', "vault", pinned=True),
        ch.Channel("UC2", "Back\\slash", "discovery"),
    ]
    ch.save_channels(chs)
    assert ch.load_channels() == chs


def test_load_channels_missing_is_empty():
    assert ch.load_channels() == []
