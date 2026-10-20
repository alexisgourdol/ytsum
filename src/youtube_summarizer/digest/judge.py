"""One batched LLM call per run: is each candidate on topic, and is it a fully sponsored video?"""

import json
import re
from dataclasses import dataclass

from youtube_summarizer.digest import llm
from youtube_summarizer.digest.config import Config
from youtube_summarizer.digest.youtube import FeedEntry

TOPIC_DEFINITION = (
    "AI models and tooling: releases from any lab (Anthropic, OpenAI, Google, Mistral, DeepSeek, "
    "open-weight models…), agents, coding assistants, reasoning and research trends, "
    "AI engineering and automation."
)
TRANSCRIPT_HEAD_CHARS = 4000

SYSTEM_PROMPT = f"""You triage YouTube videos for a daily AI digest.

For every video below, decide:
- on_topic: true if the video is about {TOPIC_DEFINITION} Be broad: any lab, any model, any trend in this space counts.
- fully_sponsored: true only if the whole video is paid promotion of one product. A sponsor segment inside a normal video is never a reason to skip; only a video that is entirely paid promotion of one product is fully sponsored.
- reason: a few words explaining the decision.

Answer with a JSON array and nothing else, one object per video:
[{{"video_id": "...", "on_topic": true, "fully_sponsored": false, "reason": "..."}}]"""


class JudgeError(Exception):
    """The judge's reply could not be used."""


@dataclass
class Verdict:
    video_id: str
    on_topic: bool
    fully_sponsored: bool
    reason: str


def build_judge_prompt(items: list[tuple[FeedEntry, str]]) -> tuple[str, str]:
    blocks = []
    for entry, transcript in items:
        blocks.append(
            f"### video_id: {entry.video_id}\n"
            f"Title: {entry.title}\n"
            f"Channel: {entry.channel_name}\n"
            f"Description: {entry.description}\n"
            f"Transcript (start): {transcript[:TRANSCRIPT_HEAD_CHARS]}"
        )
    return SYSTEM_PROMPT, "\n\n".join(blocks)


def parse_verdicts(text: str, expected_ids: set[str]) -> dict[str, Verdict]:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = fenced.group(1) if fenced else text
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise JudgeError(f"judge reply is not JSON: {text[:200]}") from e
    if not isinstance(data, list):
        raise JudgeError("judge reply is not a JSON array")
    verdicts = {}
    for item in data:
        try:
            v = Verdict(str(item["video_id"]), bool(item["on_topic"]),
                        bool(item["fully_sponsored"]), str(item.get("reason", "")))
        except (KeyError, TypeError) as e:
            raise JudgeError(f"bad judge item {item!r}") from e
        verdicts[v.video_id] = v
    missing = sorted(expected_ids - set(verdicts))
    if missing:
        raise JudgeError(f"judge reply is missing {', '.join(missing)}")
    return verdicts


def judge(items: list[tuple[FeedEntry, str]], cfg: Config) -> dict[str, Verdict]:
    if not items:
        return {}
    system, user = build_judge_prompt(items)
    r = llm.complete(system, user, model=cfg.judge_model, mode=cfg.mode, kind="judge")
    return parse_verdicts(r.text, {e.video_id for e, _ in items})
