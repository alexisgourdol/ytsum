"""Tests for vault notes: paths, frontmatter, deep-dive flags, digest note"""

from datetime import date

from youtube_summarizer.digest import notes as nt
from youtube_summarizer.digest.state import VideoRecord

DAY = date(2026, 10, 21)


def _rec(video_id="vid00000001", title="Claude Code tips"):
    return VideoRecord(video_id, "UC1", "Sam Witteveen", title, "2026-10-20T14:00:00+00:00", "pending", duration_s=1510)


def _write_note(tmp_path, name, frontmatter: str):
    path = tmp_path / name
    path.write_text(f"---\n{frontmatter}\n---\n\n# Title\n\nBody\n")
    return path


def test_note_paths_follow_convention(tmp_path):
    short, transcript, deep = nt.note_paths(tmp_path, DAY, "AI: agents?", "vid00000001")
    assert short.name == "2026-10-21 LLM - AI- agents-.md"
    assert transcript.name == "2026-10-21 LLM - AI- agents- - transcript.md"
    assert deep.name == "2026-10-21 LLM - AI- agents- - deep dive.md"


def test_note_paths_never_collide(tmp_path):
    first, _, _ = nt.note_paths(tmp_path, DAY, "Same", "AAAAAAAAAAA")
    first.write_text(nt.render_short_note(_rec("AAAAAAAAAAA", "Same"), "body", False, DAY, "x - transcript"))
    again, _, _ = nt.note_paths(tmp_path, DAY, "Same", "AAAAAAAAAAA")
    assert again == first  # same video: same file
    other, other_t, _ = nt.note_paths(tmp_path, DAY, "Same", "BBBBBBBBBBB")
    assert "(BBBBBBBBBBB)" in other.name and other != first
    assert "(BBBBBBBBBBB)" in other_t.name
    blank, _, _ = nt.note_paths(tmp_path, DAY, "???", "CCCCCCCCCCC")
    assert "CCCCCCCCCCC" in blank.name


def test_render_short_note_frontmatter_and_links():
    text = nt.render_short_note(_rec(), "## Summary\n\nProse.", True, DAY, "2026-10-21 LLM - Claude Code tips - transcript")
    fm = text.split("---")[1]
    for line in ["video_id: vid00000001", "url: https://www.youtube.com/watch?v=vid00000001",
                 'channel: "Sam Witteveen"', "digest_date: 2026-10-21", "deep_dive_suggested: true",
                 "deep_dive: false", 'deep_dive_note: ""', "duration: 25:10"]:
        assert line in fm
    assert "# Claude Code tips" in text
    assert "**Channel**: Sam Witteveen" in text and "**Topic**: LLM" in text
    assert "[[2026-10-21 LLM - Claude Code tips - transcript]]" in text


def test_render_transcript():
    assert nt.render_transcript("hello").startswith("## Transcript\n\nhello")


def test_flag_detection_tolerates_obsidian_edits(tmp_path):
    _write_note(tmp_path, "2026-10-19 LLM - a.md", 'digest_date: 2026-10-19\ndeep_dive: True\ndeep_dive_note: ""')
    _write_note(tmp_path, "2026-10-20 LLM - b.md", 'tags:\n  - ai\ndeep_dive_note: ""\ndeep_dive: yes\ndigest_date: 2026-10-20')
    _write_note(tmp_path, "2026-10-21 LLM - c.md", 'digest_date: 2026-10-21\ndeep_dive: false\ndeep_dive_suggested: true\ndeep_dive_note: ""')
    _write_note(tmp_path, "2026-10-21 LLM - done.md", 'digest_date: 2026-10-21\ndeep_dive: true\ndeep_dive_note: "[[x]]"')
    _write_note(tmp_path, "2026-10-21 LLM - not digest.md", 'deep_dive: true')
    (tmp_path / "2026-10-21 LLM - c - transcript.md").write_text("## Transcript\n\ndigest_date: nope")

    found = [p.name for p in nt.find_deep_dive_requests(tmp_path, cap=3)]
    assert found == ["2026-10-20 LLM - b.md", "2026-10-19 LLM - a.md", "2026-10-21 LLM - c.md"]
    assert len(nt.find_deep_dive_requests(tmp_path, cap=2)) == 2


def test_set_frontmatter_preserves_rest(tmp_path):
    path = _write_note(tmp_path, "n.md", 'digest_date: 2026-10-21\ndeep_dive: true\ndeep_dive_note: ""\ncustom: keep me')
    before = path.read_text()
    nt.set_frontmatter(path, "deep_dive_note", '"[[n - deep dive]]"')
    after = path.read_text()
    assert after == before.replace('deep_dive_note: ""', 'deep_dive_note: "[[n - deep dive]]"')
    nt.set_frontmatter(path, "new_key", "1")
    assert "new_key: 1\n---" in path.read_text()


def test_read_frontmatter_and_is_true(tmp_path):
    path = _write_note(tmp_path, "n.md", 'deep_dive: " Yes "\ncount: 1')
    fm = nt.read_frontmatter(path)
    assert nt.is_true(fm["deep_dive"]) and nt.is_true(fm["count"])
    assert not nt.is_true("false") and not nt.is_true("")
    assert nt.read_frontmatter(tmp_path / "missing.md") == {}


def test_parse_deep_dive_verdict():
    assert nt.parse_deep_dive_verdict("## Summary\nx\n## Deep dive?\nYes — hands-on tutorial")
    assert nt.parse_deep_dive_verdict("## Deep dive?\n\n**yes**, worth it")
    assert not nt.parse_deep_dive_verdict("## Deep dive?\nNo. Opinion piece.")
    assert not nt.parse_deep_dive_verdict("no heading at all")


def test_deep_dive_prompt_wraps_skill():
    p = nt.deep_dive_prompt("SKILL BODY")
    assert p.startswith("SKILL BODY")
    assert "Ignore the fetch and save steps; output only the summary markdown." in p


def test_render_digest_sections_and_order():
    report = nt.DigestReport(
        new=["[[note A]] · Chan · 25:10 · deep dive: yes — tutorial"],
        skipped=["Vlog · Chan · off-topic: travel"],
        failures=["Feed for UCx: 404"],
        stale_channels=["? Old Chan (news): no uploads for 90 days — consider replacing it"],
        usage=[("anthropic:claude-haiku-5-5", "summary", 2, 30000, 1500, 0.0038)],
    )
    text = nt.render_digest(report, DAY)
    order = [text.index(h) for h in ["Stale channels", "New videos", "Skipped", "Failures", "Usage"]]
    assert order == sorted(order)
    assert "Carried over" not in text  # empty sections omitted
    assert "anthropic:claude-haiku-5-5" in text and "30,000" in text


def test_render_digest_fatal_first():
    text = nt.render_digest(nt.DigestReport(fatal="YOUTUBE_API_KEY missing", new=["x"]), DAY)
    assert text.index("Run failed: YOUTUBE_API_KEY missing") < text.index("New videos")
    assert "digest.log" in text


def test_write_digest_appends_second_run(tmp_path):
    p1 = nt.write_digest(tmp_path, DAY, "first")
    assert p1.name == "2026-10-21 digest.md"
    p2 = nt.write_digest(tmp_path, DAY, "second")
    text = p2.read_text()
    assert p1 == p2 and text.startswith("first") and "## Run " in text and text.rstrip().endswith("second")


def test_note_names_are_wikilink_safe(tmp_path):
    short, _, _ = nt.note_paths(tmp_path, DAY, "Episode #3 [live] ^ notes", "vid00000001")
    assert not any(c in short.stem for c in "[]#^|")


def test_failed_deep_dives_give_up_after_max_attempts(tmp_path):
    a = _write_note(tmp_path, "2026-10-21 LLM - a.md", 'digest_date: 2026-10-21\ndeep_dive: true\ndeep_dive_note: ""\ndeep_dive_attempts: 3')
    b = _write_note(tmp_path, "2026-10-20 LLM - b.md", 'digest_date: 2026-10-20\ndeep_dive: true\ndeep_dive_note: ""\ndeep_dive_attempts: 1')
    c = _write_note(tmp_path, "2026-10-19 LLM - c.md", 'digest_date: 2026-10-19\ndeep_dive_suggested: true\ndeep_dive_note: ""')
    found = nt.find_deep_dive_requests(tmp_path, cap=2, max_attempts=3)
    assert found == [b, c]  # a gave up, so it no longer takes a slot


def test_render_digest_block_first():
    text = nt.render_digest(nt.DigestReport(blocked="feeds: HTTP 429"), date(2026, 10, 31))
    assert text.splitlines()[2].startswith("**Run stopped: YouTube is blocking this IP** (step: feeds: HTTP 429)")
