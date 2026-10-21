"""Error messages, shortened for one line of the digest note."""

MAX_REASON_CHARS = 200


def short_reason(message: str) -> str:
    """
    One line for the digest note. youtube-transcript-api errors span many lines; their
    cause is the line after "This is most likely caused by:".
    """
    lines = [l.strip() for l in str(message).splitlines() if l.strip()]
    if not lines:
        return ""
    reason = lines[0].rstrip(": ")
    for i, line in enumerate(lines[:-1]):
        if line.endswith("caused by:"):
            reason = f"{reason}: {lines[i + 1]}"
            break
    return reason if len(reason) <= MAX_REASON_CHARS else reason[:MAX_REASON_CHARS - 1] + "…"
