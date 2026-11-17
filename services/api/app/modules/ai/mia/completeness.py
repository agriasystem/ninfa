"""A deterministic check that an answer was written to its end.

The structured output of a real model can, rarely, stop in the middle of a sentence while still
being valid JSON with status ANSWERED (measured against the real API: one answer in ~50 ended
"...e non esistono"). A cut-off answer is worse than a short one - it reads as a statement the
user cannot see the end of - so it never goes out: the orchestrator asks for a rewrite once (like
an ungrounded figure) and fails closed if the rewrite is cut off too.

The rule is deliberately plain and measured: every answer of the real-model runs ended with a
full stop or a question mark. An answer is complete when its last character closes a sentence,
or when its last line is a list item ("- ..."), which is written without a full stop.
"""

_SENTENCE_END = (".", "!", "?", "…", ")", '"', "»", "”", ":")


def looks_truncated(answer: str) -> bool:
    """True when `answer` ends without closing its last sentence."""
    text = answer.rstrip()
    if not text:
        return False  # emptiness is another check's job (answer validation)
    if text.endswith(_SENTENCE_END):
        return False
    last_line = text.splitlines()[-1].lstrip()
    return not last_line.startswith("- ")


__all__ = ["looks_truncated"]
