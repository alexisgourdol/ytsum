"""Tests for the batched topic / sponsorship judge"""

import json

import pytest

from youtube_summarizer.digest import judge as jd
from youtube_summarizer.digest.config import Config
from youtube_summarizer.digest.youtube import FeedEntry


def _entry(video_id, title="T", description="D"):
    return FeedEntry(video_id, "UC1", "Chan", title, "2026-10-20T00:00:00+00:00", description)


def test_prompt_contains_rules():
    long_transcript = "x" * 5000 + "TAIL_MARKER"
    system, user = jd.build_judge_prompt([(_entry("v1", "Mistral Large 3 is out", "release notes"), long_transcript)])
    assert jd.TOPIC_DEFINITION in system
    assert "sponsor segment inside a normal video is never a reason to skip" in system
    assert "JSON" in system
    assert "v1" in user and "Mistral Large 3 is out" in user and "release notes" in user
    assert "x" * 4000 in user and "TAIL_MARKER" not in user


def test_parse_verdicts_fenced():
    text = '```json\n[{"video_id": "v1", "on_topic": true, "fully_sponsored": false, "reason": "agents"}]\n```'
    verdicts = jd.parse_verdicts(text, {"v1"})
    assert verdicts["v1"] == jd.Verdict("v1", True, False, "agents")


def test_parse_verdicts_missing_id_raises():
    text = json.dumps([{"video_id": "v1", "on_topic": True, "fully_sponsored": False, "reason": ""}])
    with pytest.raises(jd.JudgeError, match="v2"):
        jd.parse_verdicts(text, {"v1", "v2"})


def test_parse_verdicts_not_json_raises():
    with pytest.raises(jd.JudgeError):
        jd.parse_verdicts("Sure! Here are my thoughts...", {"v1"})


def test_judge_empty_makes_no_call(mocker):
    complete = mocker.patch("youtube_summarizer.digest.llm.complete")
    assert jd.judge([], Config()) == {}
    complete.assert_not_called()


def test_judge_uses_judge_model_and_mode(mocker):
    reply = json.dumps([{"video_id": "v1", "on_topic": False, "fully_sponsored": False, "reason": "cooking vlog"}])
    complete = mocker.patch("youtube_summarizer.digest.llm.complete", return_value=mocker.MagicMock(text=reply))
    verdicts = jd.judge([(_entry("v1"), "transcript")], Config(mode="subscription"))
    assert verdicts["v1"].on_topic is False
    kwargs = complete.call_args.kwargs
    assert (kwargs["kind"], kwargs["model"], kwargs["mode"]) == ("judge", "claude-haiku-5-5", "subscription")
