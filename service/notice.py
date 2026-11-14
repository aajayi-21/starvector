"""The notice that results are public (spec R1 section 3).

The text of the notice is in the web app, and this module has its
version number. A change of the text is a new number, and a player who
agreed to an earlier number gets the new text one time. A test reads
the number of the web app and stops if the two are not equal.
"""

import datetime
from pathlib import Path

from service import store

# The version of the notice text that the sign-up screen shows.
NOTICE_VERSION = 1

NOTICE_REFUSED = "notice"


def agreed(root: Path, player: str) -> bool:
    """The player agreed to the current version of the notice."""
    return store.read_consent_or_none(root, player, NOTICE_VERSION) is not None


def record_agreement(root: Path, player: str,
                     instant: datetime.datetime) -> bool:
    """Write the agreement of one player to the current version.

    The answer says if this write made the record: a record that was
    there stays as it is.
    """
    return store.write_consent(
        root, player, NOTICE_VERSION,
        instant.astimezone(datetime.UTC).isoformat())
