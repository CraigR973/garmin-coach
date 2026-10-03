"""Admin alerts reach Craig through Sentry (Batch 291).

Production has one profile, Mark's, so the operator push that Batch 141 built has no
recipient: pointing ``ADMIN_ALERT_USER_ID`` at him is refused, and would put ops alerts
on his phone. Craig chose Sentry as the operator route (25 Sep 2026). Every alert that
needs him is one error-level log event carrying a stable tag, ``admin_alert=<kind>``, so
a single Sentry alert rule (any new issue tagged ``admin_alert``) catches all of them.

The tag is set on an isolated scope around the log call: Sentry's logging integration
turns the error record into an issue inside that scope, and nothing leaks into later
events. Each caller passes its own module logger, so the event keeps its name and its
module, and the push half of Batch 141 stays for a future operator profile.

A failed note reading is deliberately not an admin alert: it stays a warning (Craig,
3 Oct 2026).
"""

from __future__ import annotations

from typing import Any, Final

import sentry_sdk

ADMIN_ALERT_TAG: Final = "admin_alert"

KIND_BILLING: Final = "billing"
KIND_GENERATION_FAILURE: Final = "generation_failure"
KIND_LONGITUDINAL: Final = "longitudinal"
KIND_CROSS_SURFACE: Final = "cross_surface_disagreement"
KIND_FIGURE_CONTEST: Final = "figure_contest"
KIND_VERDICT_LESS_CAUTIOUS: Final = "verdict_less_cautious"
KINDS: Final = frozenset(
    {
        KIND_BILLING,
        KIND_GENERATION_FAILURE,
        KIND_LONGITUDINAL,
        KIND_CROSS_SURFACE,
        KIND_FIGURE_CONTEST,
        KIND_VERDICT_LESS_CAUTIOUS,
    }
)


def admin_alert(logger: Any, event: str, *, kind: str, **fields: Any) -> None:
    """Log ``event`` at error level, tagged so Craig's one Sentry rule catches it."""

    with sentry_sdk.new_scope() as scope:
        scope.set_tag(ADMIN_ALERT_TAG, kind)
        logger.error(event, admin_alert=kind, **fields)


def generation_failure_kind(reason: str, artifact: str) -> str:
    """The tag for a failed paid generation: a billing outage first, then which job."""

    if reason == "billing":
        return KIND_BILLING
    if artifact == "longitudinal_analysis":
        return KIND_LONGITUDINAL
    return KIND_GENERATION_FAILURE
