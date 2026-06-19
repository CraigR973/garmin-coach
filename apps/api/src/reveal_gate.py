"""Shared prediction-reveal gate (U24).

The single source of truth for *when another player's prediction may be
returned by the API*. Every endpoint that exposes a peer's prediction — match
comparison, knockout comparison, the specials board, and the player profile —
funnels through these predicates so the privacy invariant is enforced in one
place with no divergent rules.

Privacy invariant: **no endpoint may ever return a player's prediction before
that prediction locks.** Each kind has exactly one lock moment:

* group prediction   → its own match's kickoff (``kickoff_utc``)
* knockout prediction → its own match's kickoff (``kickoff_utc``)  [per U22.1]
* special prediction  → the tournament's opening kickoff (specials lock as a
  set when the first match starts)

The two match-based kinds share the *identical* predicate
(:func:`match_prediction_revealed`); group and knockout differ only in which
table the row lives in, never in the rule. All predicates are evaluated against
naive-UTC ``datetime`` values to match the ``*_utc`` columns.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.models.match import Match, MatchStatus

# Terminal states an admin can set *before* kickoff to void a fixture. They are
# themselves lock events — the match will not be played, so predictions are
# frozen and may be revealed. Keeping them here (rather than only keying on
# kickoff) means a cancelled/postponed match's predictions don't stay hidden
# forever waiting for a kickoff that never comes.
_VOID_STATUSES: frozenset[MatchStatus] = frozenset({MatchStatus.cancelled, MatchStatus.postponed})


def now_utc() -> datetime:
    """Naive-UTC 'now', matching the timezone-naive ``*_utc`` columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def match_prediction_revealed(match: Match, now: datetime) -> bool:
    """True once ``match`` is locked — the shared group/knockout reveal gate.

    A prediction (group *or* knockout) tied to this match becomes visible to
    league-mates the instant its own kickoff passes — and never one moment
    sooner — or when an admin voids the fixture (cancelled/postponed), which is
    itself a pre-play lock event. Sibling matches are independent: another tie
    kicking off does not reveal this one.

    This is safe for the privacy invariant: neither branch can be true before
    kickoff except an explicit admin void, which freezes predictions anyway.
    """
    return match.kickoff_utc <= now or match.status in _VOID_STATUSES


def specials_revealed(opening_match: Match | None, now: datetime) -> bool:
    """True once the tournament has started (opening match kicked off).

    Special predictions (tournament winner, golden boot, …) lock together when
    the first group match kicks off; before that nothing is revealed. With no
    opening match seeded yet, specials stay hidden.
    """
    if opening_match is None:
        return False
    return opening_match.kickoff_utc <= now
