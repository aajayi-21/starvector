"""The notice that results are public (spec R1 section 3).

The text of the notice is in the web app, and this module has its
version number. A change of the text is a new number, and a player who
agreed to an earlier number gets the new text one time. A test reads
the number of the web app and stops if the two are not equal.

Version 2 is the text of spec SS1 section 10. It tells a player that
each player who sent on a day sees the sketch after the send.
"""

import datetime
from pathlib import Path

from service import store

# The version of the notice text that the sign-up screen shows.
NOTICE_VERSION = 2

# The first version with the sentence on the sketch after the send
# (spec SS1 section 10). An agreement to an earlier version is not an
# agreement to that.
SHOWING_VERSION = 2

NOTICE_REFUSED = "notice"


def agreed(root: Path, player: str) -> bool:
    """The player agreed to the current version of the notice."""
    return store.read_consent_or_none(root, player, NOTICE_VERSION) is not None


def agreed_to_showing(root: Path, player: str) -> bool:
    """The player agreed that other players see the sketch after the send.

    The answer is yes with an agreement to version SHOWING_VERSION or
    to a subsequent version. Spec SS1 section 10 gives the rule: the
    send of a player with version 1 alone does not go to a second
    player before the reveal of its day.
    """
    return any(
        store.read_consent_or_none(root, player, version) is not None
        for version in range(SHOWING_VERSION, NOTICE_VERSION + 1))


def record_agreement(root: Path, player: str,
                     instant: datetime.datetime) -> bool:
    """Write the agreement of one player to the current version.

    The answer says if this write made the record: a record that was
    there stays as it is.
    """
    return store.write_consent(
        root, player, NOTICE_VERSION,
        instant.astimezone(datetime.UTC).isoformat())
