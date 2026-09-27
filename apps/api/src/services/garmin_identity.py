"""A profile receives Garmin data only from the Garmin account it names (Batch 283).

Garmin authenticates from one global token (``GARMIN_TOKENSTORE_B64``) and the
sync jobs iterate every active profile, so before this module a second profile
would have been synced with Mark's session and filled with his sleep, HRV and
activities. That is what happened on 2026-08-24, when a ``Craig`` profile with
no ``garmin_user_profile_pk`` ingested Mark's history byte for byte and then
generated a paid brief describing it as its own.

Two rules, both enforced where the data is written:

* **A profile that names no Garmin account is not synced at all.** The jobs skip
  it before any Garmin call and count it; the write layer refuses it anyway, so a
  caller that forgets the job-level skip still cannot write.
* **A document that names a different account is refused.** Garmin writes the
  owning account's id into the documents it returns (``userProfilePK``,
  ``userProfileId``, ``ownerId``, ``userId`` depending on the endpoint), so the
  check costs no Garmin call — which matters, because extra calls are what got
  the Railway IP rate-limited on 2026-09-20 (Batch 267).

A document that carries no id is no evidence either way and is not refused.
That is deliberate: it keeps the check from stopping Mark's sync on a field
Garmin one day renames, while still catching the case this exists for — every
document Garmin returns for a real day carries the id, so another account's
data always contradicts the profile somewhere. Measured 2026-09-24: all 552
stored daily-metric rows, 458 sleep rows and 1,249 activities in production
carry Mark's id in exactly the fields read below, and none carries another.

The per-profile tokenstore that would let a second person sync their *own*
account is a credentials change and is not attempted here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

# Where each daily endpoint puts the owning account's id, measured on the real
# sample payloads in ~/garmin-spike/out/. ``body_battery`` and ``weigh_ins``
# carry none. Sleep is read one level down, under ``dailySleepDTO``.
DAILY_OWNER_FIELDS: Mapping[str, str] = {
    "training_readiness": "userProfilePK",
    "hrv": "userProfilePk",
    "rhr": "userProfileId",
    "max_metrics_vo2": "userId",
    "training_status": "userId",
    "stress": "userProfilePK",
    "stats": "userProfileId",
}
SLEEP_OWNER_FIELD = "userProfilePK"
ACTIVITY_OWNER_FIELD = "ownerId"


class GarminIdentityError(RuntimeError):
    """Garmin data would reach a profile that does not own it."""


class GarminAccountUnbound(GarminIdentityError):
    """The profile names no Garmin account, so nothing may be synced into it."""


class GarminIdentityMismatch(GarminIdentityError):
    """A document names a different Garmin account from the profile's."""

    def __init__(self, *, source: str, expected: int, found: set[int]) -> None:
        self.source = source
        self.expected = expected
        self.found = found
        super().__init__(
            f"Garmin {source} data belongs to account(s) {sorted(found)}, "
            f"not the profile's account {expected}; refusing to write it."
        )


class _DailyPayloads(Protocol):
    """The fields of ``GarminDailyPayloads`` this module reads.

    A protocol rather than an import keeps this a leaf: ``garmin_sync`` imports
    this module, not the other way round.
    """

    @property
    def sleep(self) -> Any: ...


def _as_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _ids_in(document: Any, field: str) -> set[int]:
    """The id under ``field`` in a document or in each element of a list of them."""
    elements = document if isinstance(document, list) else [document]
    found: set[int] = set()
    for element in elements:
        if isinstance(element, Mapping):
            owner = _as_id(element.get(field))
            if owner is not None:
                found.add(owner)
    return found


def sleep_owner_ids(payload: Any) -> set[int]:
    dto = payload.get("dailySleepDTO") if isinstance(payload, Mapping) else None
    return _ids_in(dto, SLEEP_OWNER_FIELD)


def daily_owner_ids(payloads: _DailyPayloads) -> set[int]:
    found = sleep_owner_ids(payloads.sleep)
    for name, field in DAILY_OWNER_FIELDS.items():
        found |= _ids_in(getattr(payloads, name, None), field)
    return found


def activity_owner_ids(summaries: Iterable[Any]) -> set[int]:
    return _ids_in(list(summaries), ACTIVITY_OWNER_FIELD)


def garmin_account(profile: Any) -> int | None:
    """The Garmin account a profile names, or ``None`` if it names none."""
    return _as_id(getattr(profile, "garmin_user_profile_pk", None))


def assert_owned_by(expected: int | None, found: set[int], *, source: str) -> None:
    """Refuse data for an unbound profile, or data naming another account."""
    if expected is None:
        raise GarminAccountUnbound(
            f"The profile names no Garmin account; refusing to sync Garmin {source} data "
            "into it. Set garmin_user_profile_pk to the account it owns."
        )
    others = {owner for owner in found if owner != expected}
    if others:
        raise GarminIdentityMismatch(source=source, expected=expected, found=others)
