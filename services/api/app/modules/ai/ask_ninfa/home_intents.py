"""Bounded question understanding for Mia Home: question (+ short history) -> a closed resolution.

    question  ->  HomeIntent(s) + period + named channels + unsupported concepts

This is NOT an autonomous agent and NOT a model call. It is a deterministic classifier over the
explicit hospitality vocabulary (`home_vocabulary`) and the explicit time expressions
(`home_period`), and its whole output is a closed, typed value: a set of `HomeIntent`, an optional
`ResolvedPeriod`, channel keys from a closed table, and `UnsupportedTopic`s. It carries no business
fact. Its only job is to SELECT which deterministic facts `HomeDataService` fetches (ENGINE
CALCULATES. MIA EXPLAINS.) - and to make a follow-up land on the right ones:

    "Qual è la priorità più urgente?"  ->  PRIORITY
    "Perché?"                          ->  (no topic of its own) inherits PRIORITY from the history

Only the user's OWN earlier messages are consulted for that inheritance: the assistant's earlier
text is untrusted and is never mined for topics or facts.

A question the router cannot place is `UNKNOWN`: Mia still receives the full overview context
(decisions, coverage, freshness) and the model answers what it supports or says exactly what NINFA
cannot determine - never a generic fallback.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.modules.ai.ask_ninfa.home_history import HistoryRole, HomeHistoryTurn
from app.modules.ai.ask_ninfa.home_period import ResolvedPeriod, parse_period
from app.modules.ai.ask_ninfa.home_vocabulary import (
    CHANNEL_WORDS,
    FOLLOW_UP_WORDS,
    INCIDENCE_WORDS,
    INTENT_PHRASES,
    INTENT_WORDS,
    NEUTRALISED_PHRASES,
    OVERVIEW_PHRASES,
    TYPOS,
    UNSUPPORTED_PHRASES,
    UNSUPPORTED_WORDS,
    WEAK_DAY_ADJECTIVES,
    WEAK_DAY_NOUNS,
    WEAK_DAYS_PHRASES,
    HomeIntent,
    UnsupportedTopic,
    damerau_levenshtein,
    fuzzy_alias,
    normalize_text,
)

# A topic-bearing question this short, naming no period, keeps the period of the user's previous
# question ("e l'occupazione?" after "come vanno le prenotazioni domani?").
_SHORT_QUESTION_TOKENS = 5

_WORD_TO_INTENT: dict[str, HomeIntent] = {
    word: intent for intent, words in INTENT_WORDS.items() for word in words
}
_WORD_TO_UNSUPPORTED: dict[str, UnsupportedTopic] = {
    word: topic for topic, words in UNSUPPORTED_WORDS.items() for word in words
}
_SINGLE_CHANNEL_WORDS: dict[str, str] = {
    word: key for key, words in CHANNEL_WORDS.items() for word in words if " " not in word
}
# The canonical order every resolution lists its intents in (stable output, stable tests).
_INTENT_ORDER = tuple(HomeIntent)


@dataclass(frozen=True, slots=True)
class QuestionResolution:
    """What a question (with its short history) is about. `intents` is never empty: it is
    `(UNKNOWN,)` when nothing could be placed. `channels` are keys of `CHANNEL_WORDS`.
    `inherited` is true when the topic came from the user's previous question ("Perché?");
    `referential` when the question has no topic of its own and no history to take one from."""

    intents: tuple[HomeIntent, ...]
    period: ResolvedPeriod | None
    channels: tuple[str, ...]
    unsupported: tuple[UnsupportedTopic, ...]
    weak_days: bool
    inherited: bool
    referential: bool

    @property
    def is_unknown(self) -> bool:
        return self.intents == (HomeIntent.UNKNOWN,)


@dataclass(frozen=True, slots=True)
class _Analysis:
    intents: frozenset[HomeIntent]
    channels: frozenset[str]
    unsupported: frozenset[UnsupportedTopic]
    period: ResolvedPeriod | None
    weak_days: bool
    token_count: int
    bare_follow_up: bool

    @property
    def has_topic(self) -> bool:
        return bool(self.intents or self.channels)


def _contains(normalized: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized} "


def _fuzzy_channel(token: str) -> str | None:
    if len(token) < 5:
        return None
    budget = 1 if len(token) <= 8 else 2
    matches = {
        key
        for word, key in _SINGLE_CHANNEL_WORDS.items()
        if len(word) >= 5
        and abs(len(word) - len(token)) <= budget
        and damerau_levenshtein(token, word) <= budget
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _analyze(text: str, as_of: date) -> _Analysis:
    normalized = normalize_text(text)
    for phrase in NEUTRALISED_PHRASES:
        normalized = f" {normalized} ".replace(f" {phrase} ", " ").strip()
    period = parse_period(normalized, as_of)

    intents: set[HomeIntent] = set()
    channels: set[str] = set()
    unsupported: set[UnsupportedTopic] = set()

    # "booking pace" is the rhythm of reservations, not the channel "Booking": claim it first.
    pace = _contains(normalized, "booking pace")
    if pace:
        intents.add(HomeIntent.BOOKINGS)
        normalized_for_channels = f" {normalized} ".replace(" booking pace ", " ").strip()
    else:
        normalized_for_channels = normalized

    for intent, phrases in INTENT_PHRASES.items():
        if any(_contains(normalized, phrase) for phrase in phrases):
            intents.add(intent)
    if any(_contains(normalized, phrase) for phrase in OVERVIEW_PHRASES):
        intents.update({HomeIntent.BOOKINGS, HomeIntent.OCCUPANCY})
    question_words = set(normalized.split())
    weak_days = any(_contains(normalized, phrase) for phrase in WEAK_DAYS_PHRASES) or bool(
        question_words & WEAK_DAY_NOUNS and question_words & WEAK_DAY_ADJECTIVES
    )
    if weak_days:
        intents.add(HomeIntent.OCCUPANCY)

    for key, words in CHANNEL_WORDS.items():
        if any(_contains(normalized_for_channels, word) for word in words):
            channels.add(key)

    tokens = [TYPOS.get(token, token) for token in normalized.split()]
    # "booking pace" was claimed above: its "booking" must not come back as the channel.
    channel_tokens = {TYPOS.get(token, token) for token in normalized_for_channels.split()}
    for token in tokens:
        matched = _WORD_TO_INTENT.get(token) or fuzzy_alias(token, _WORD_TO_INTENT)
        if matched is not None:
            intents.add(matched)
        elif token not in _WORD_TO_UNSUPPORTED and token in channel_tokens:
            channel = _fuzzy_channel(token)
            if channel is not None:
                channels.add(channel)
        topic = _WORD_TO_UNSUPPORTED.get(token)
        if topic is not None:
            unsupported.add(topic)

    for topic, phrases in UNSUPPORTED_PHRASES.items():
        if any(_contains(normalized, phrase) for phrase in phrases):
            unsupported.add(topic)
    if intents & {HomeIntent.COSTS, HomeIntent.LABOR} and any(
        token in INCIDENCE_WORDS for token in tokens
    ):
        unsupported.add(UnsupportedTopic.INCIDENCE)

    if channels:
        intents.add(HomeIntent.DISTRIBUTION)
    intents.discard(HomeIntent.UNKNOWN)

    bare = bool(tokens) and all(token in FOLLOW_UP_WORDS for token in tokens)
    return _Analysis(
        intents=frozenset(intents),
        channels=frozenset(channels),
        unsupported=frozenset(unsupported),
        period=period,
        weak_days=weak_days,
        token_count=len(tokens),
        bare_follow_up=bare,
    )


def _ordered(intents: frozenset[HomeIntent]) -> tuple[HomeIntent, ...]:
    return tuple(intent for intent in _INTENT_ORDER if intent in intents)


def resolve_question(
    question: str, history: Sequence[HomeHistoryTurn], as_of: date
) -> QuestionResolution:
    """Deterministic and pure: the same `(question, history, as_of)` resolves the same way."""
    own = _analyze(question, as_of)
    previous = [
        _analyze(turn.content, as_of) for turn in reversed(history) if turn.role is HistoryRole.USER
    ]

    if own.has_topic:
        # Short follow-up naming a topic but no period keeps the previous question's period.
        period = own.period
        inherited = False
        if (
            period is None
            and own.token_count <= _SHORT_QUESTION_TOKENS
            and previous
            and previous[0].period is not None
        ):
            period = previous[0].period
            inherited = True
        return QuestionResolution(
            intents=_ordered(own.intents),
            period=period,
            channels=tuple(sorted(own.channels)),
            unsupported=tuple(sorted(own.unsupported)),
            weak_days=own.weak_days,
            inherited=inherited,
            referential=False,
        )

    if own.unsupported:
        # An explicitly unsupported concept ("qual è il margine?") is its own topic: it is not a
        # follow-up and borrows nothing from the history.
        return QuestionResolution(
            intents=(HomeIntent.UNKNOWN,),
            period=own.period,
            channels=(),
            unsupported=tuple(sorted(own.unsupported)),
            weak_days=False,
            inherited=False,
            referential=False,
        )

    for earlier in previous:
        if earlier.has_topic:
            return QuestionResolution(
                intents=_ordered(earlier.intents),
                period=own.period or earlier.period,
                channels=tuple(sorted(earlier.channels)),
                unsupported=tuple(sorted(earlier.unsupported)),
                weak_days=earlier.weak_days,
                inherited=True,
                referential=False,
            )

    return QuestionResolution(
        intents=(HomeIntent.UNKNOWN,),
        period=own.period,
        channels=(),
        unsupported=(),
        weak_days=False,
        inherited=False,
        referential=own.bare_follow_up,
    )


__all__ = ["QuestionResolution", "resolve_question"]
