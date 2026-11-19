"""The output of the operator command line: text lines, JSON, and CSV.

Spec: OC1 (in docs/specs/operator-cli.md) section 3. Each function
here is pure: it gets a plain value, and it answers text lines or one
text. It reads no file and no clock, and it prints nothing. The shell
of the command prints the answer.

A terminal obeys a control character, and a browser does not (spec
OC1 section 3.1). Thus each field that a player or a file from a
different computer can write goes through `safe_text` before it goes
in a line. The times print in UTC, as the store holds them.

A view of a day shows the target only when the caller says so: the
caller gives each day view to `redact_day` of the plan module first,
and a view with no mark from that function raises here.
"""

import json
import unicodedata
from collections.abc import Mapping, Sequence

# The key that `redact_day` of the plan module adds to a day view.
VISIBILITY_KEY = "target_visibility"

# The Unicode categories that `safe_text` changes to a code: control,
# format (the direction marks and the marks of no width), surrogate,
# private use, not assigned, line separator, and paragraph separator.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_SHORT_CODES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _code(mark: str) -> str:
    """The printable code of one character, as a Python text literal
    writes it."""
    if mark in _SHORT_CODES:
        return _SHORT_CODES[mark]
    point = ord(mark)
    if point < 0x100:
        return f"\\x{point:02x}"
    if point < 0x10000:
        return f"\\u{point:04x}"
    return f"\\U{point:08x}"


def safe_text(text: str) -> str:
    """The text with each control character as a printable code.

    A C0 or C1 control, DEL, a direction mark (for example U+202E), a
    mark of no width, and a line separator each become a code, for
    example `\\x1b` or `\\u202e`. A line end becomes the two characters
    `\\n`, thus one value stays on one line. Each printable character
    stays as it is, a letter that is not ASCII too.
    """
    if not isinstance(text, str):
        raise TypeError(f"safe_text takes a str, got {type(text).__name__}")
    return "".join(
        _code(mark) if unicodedata.category(mark) in _UNSAFE_CATEGORIES
        else mark
        for mark in text)


def _text(value: object) -> str:
    """One value as safe text: `-` for None, `yes` or `no` for a bool."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    return safe_text(str(value))


def _table(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Aligned text columns: the header, a rule, and each row.

    Each cell is safe text before it comes here. The width is a count
    of characters, thus a wide character can move a column.
    """
    widths = [len(column) for column in columns]
    for row in rows:
        if len(row) != len(columns):
            raise ValueError(
                f"a row has {len(row)} cells and the header has "
                f"{len(columns)}")
        widths = [max(width, len(cell))
                  for width, cell in zip(widths, row, strict=True)]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(width) for cell, width
                         in zip(cells, widths, strict=True)).rstrip()

    return [line(columns), line(["-" * width for width in widths]),
            *(line(row) for row in rows)]


def _trial_part(trial: Mapping[str, object]) -> str:
    """The five numbers of one trial row."""
    return (f"p={_text(trial['p'])}  rank={_text(trial['target_rank'])}  "
            f"decoys={_text(trial['decoy_count'])}  "
            f"beaten={_text(trial['beaten'])}  tied={_text(trial['tied'])}")


def _visibility(view: Mapping[str, object]) -> str:
    """The mark that `redact_day` put on the view.

    A view with no mark did not go through that function, and it can
    hold the target of a day that is not revealed. It raises.
    """
    if VISIBILITY_KEY not in view:
        raise ValueError(
            f"the day view has no {VISIBILITY_KEY!r}: give it to redact_day "
            "before a renderer")
    return str(view[VISIBILITY_KEY])


# ---- days and sends ----


def target_lines(image_id: str, credit: Mapping[str, str] | None) -> list[str]:
    """The target of a day that shows it: the image identifier and the
    credit. credit holds `title`, `source`, and `page`, or it is None
    for an image with no credit."""
    if credit is None:
        return [f"target {_text(image_id)}", "credit none"]
    return [f"target {_text(image_id)}",
            f"credit {_text(credit['title'])} - {_text(credit['source'])}",
            f"page {_text(credit['page'])}"]


def _target_part(view: Mapping[str, object]) -> list[str]:
    match _visibility(view):
        case "shown":
            if view.get("target_id") is None:
                raise ValueError("a view that shows the target holds none")
            return target_lines(str(view["target_id"]), view.get("credit"))
        case "none-yet":
            # Spec VP1 section 8: no line says that a photo is hidden,
            # because no photo is picked before the close.
            return ["no target until the close"]
        case "hidden":
            return ["target not shown: the day is not revealed"]
        case other:
            raise ValueError(f"no output for the target visibility {other!r}")


def day_rows_lines(rows: Sequence[Mapping[str, object]]) -> list[str]:
    """One line for each stored day: the day, its code, its status, and
    its send count. No line holds a target."""
    lines = []
    for row in rows:
        line = (f"{_text(row['day'])}  {_text(row['trial_code'])}  "
                f"{_text(row['status'])}  sends={_text(row['sends'])}")
        if row.get("quarantined"):
            line += f"  quarantined={_text(row['quarantined'])}"
        lines.append(line)
    return lines or ["no stored day"]


def _send_row_line(send: Mapping[str, object], shown: bool) -> str:
    line = (f"  {_text(send['received_at'])}  {_text(send['player'])}  "
            f"trial={_text(send['trial_id'])}")
    if shown:
        trial = send.get("trial")
        line += "  no trial row" if trial is None \
            else "  " + _trial_part(trial)
    return f"{line}  {_text(send['display_name'])}"


def day_lines(view: Mapping[str, object]) -> list[str]:
    """One day: its times, its target line, and each send.

    view is the day view of the console module after `redact_day`. The
    target line is the target and its credit, or `no target until the
    close` for a `vp1` day before its pick, or a line that says the
    target does not show. A send shows its trial numbers only in a
    view that shows the target.
    """
    shown = _visibility(view) == "shown"
    lines = [f"day {_text(view['day'])}",
             f"trial code {_text(view['trial_code'])}",
             f"status {_text(view['status'])}",
             f"opened {_text(view['opened_at'])}"]
    for label, key in (("closes", "closes_at"), ("closed", "closed_at"),
                       ("revealed", "revealed_at"),
                       ("commitment", "commitment")):
        if view.get(key) is not None:
            lines.append(f"{label} {_text(view[key])}")
    lines.append(f"scoring config {_text(view['scoring_config_hash'])}")
    lines.append(f"preparation {_text(view['preparation_version_id'])}")
    lines.extend(_target_part(view))
    sends = view["sends"]
    lines.append(f"sends {len(sends)}")
    lines.extend(_send_row_line(send, shown) for send in sends)
    return lines


def _group_text(record: Mapping[str, object], group_id: str) -> str:
    """A group as the console names it: its label and its identifier."""
    for group in record["groups"]:
        if group["id"] == group_id and group["label"] != "":
            return f"{_text(group['label'])} ({_text(group_id)})"
    return _text(group_id)


def send_lines(record: Mapping[str, object]) -> list[str]:
    """One stored send: its day, player, trial, and time, the counts of
    the sketch, and each text that the player wrote.

    record is the stored submission document, with the wire record
    below `record`. The stroke coordinates do not print: a terminal
    shows no sketch.
    """
    wire = record["record"]
    lines = [f"day {_text(record['day'])}",
             f"player {_text(record['player'])}",
             f"trial {_text(record['trial_id'])}",
             f"received {_text(record['received_at'])}",
             f"strokes {len(wire['canvas_strokes'])}  "
             f"groups {len(wire['groups'])}  "
             f"relations {len(wire['relations'])}"]
    lines.extend(f"impression: {_text(text)}" for text in wire["impressions"])
    lines.extend(f"group: {_group_text(wire, group['id'])}"
                 for group in wire["groups"])
    for relation in wire["relations"]:
        first, second = relation["of"]
        lines.append(f"relation: {_group_text(wire, first)} "
                     f"{_text(relation['relation'])} "
                     f"{_group_text(wire, second)}")
    if wire["pasted_text"] is not None:
        lines.append(f"pasted: {_text(wire['pasted_text'])}")
    return lines


def history_lines(view: Mapping[str, object]) -> list[str]:
    """The days of one player, newest first.

    view holds `player` and `days`. Each row of `days` is a history row
    of the console module after `redact_day`, thus a row shows its
    trial numbers only when the day shows its target.
    """
    lines = [f"player {_text(view['player'])}"]
    for row in view["days"]:
        line = (f"{_text(row['day'])}  {_text(row['trial_code'])}  "
                f"{_text(row['status'])}  sent={_text(row['submitted'])}")
        if _visibility(row) == "shown" and row.get("trial") is not None:
            line += "  " + _trial_part(row["trial"])
        lines.append(line)
    if not view["days"]:
        lines.append("no stored day")
    return lines


def trial_lines(rows: Sequence[Mapping[str, object]],
                truncated: bool = False) -> list[str]:
    """One line for each revealed trial row of the results index.

    Each row is of a revealed day, thus the target shows. truncated
    adds a line that says the answer is cut at the row limit.
    """
    lines = [
        f"{_text(row['day'])}  {_text(row['player'])}  {_trial_part(row)}  "
        f"target={_text(row['target_id'])}  {_text(row['display_name'])}"
        for row in rows]
    if truncated:
        lines.append("truncated: the index holds more rows than this "
                     "answer shows")
    return lines or ["no revealed trial rows"]


def rankings_lines(view: Mapping[str, object],
                   limit: int | None) -> list[str]:
    """The rank of one send: the trial numbers, the fused sequence, and
    the atom report.

    view is the answer of the dev rankings of the scoring module. The
    table shows the first limit rows, or each row with None. The row
    of the target has a `*`, and it prints below the table when it is
    after the limit. Raises ValueError for a limit less than 1.
    """
    if limit is not None and limit < 1:
        raise ValueError("the row limit must be 1 or more")
    names = [str(name) for name in view["channel_names"]]
    rankings = view["rankings"]
    position = view["target_position"]

    def cells(row: Mapping[str, object]) -> list[str]:
        return ["*" if row["is_target"] else "", _text(row["position"]),
                _text(row["fused"]),
                *(_text(row["channels"][name]) for name in names),
                _text(row["image_id"])]

    head = rankings if limit is None else rankings[:limit]
    after = [row for row in rankings[len(head):] if row["is_target"]]
    lines = [_trial_part(view["trial"]),
             f"target position {_text(position)} of {len(rankings)}"]
    lines.extend(_table(
        ["", "position", "fused", *(safe_text(name) for name in names),
         "image"],
        [cells(row) for row in (*head, *after)]))
    lines.extend(
        f"atom: {_text(row['atom_text'])}  element={_text(row['element'])}  "
        f"weight={_text(row['weight'])}  "
        f"similarity={_text(row['similarity'])}  "
        f"rarity={_text(row['rarity'])}"
        for row in view["report"])
    return lines


# ---- the schedule ----


def _plan_text(plan: Mapping[str, object]) -> str:
    """The steps of one plan, with the day that an `open` step starts."""
    steps = [f"open {_text(plan['opens'])}"
             if step == "open" and plan.get("opens") is not None
             else _text(step)
             for step in plan["steps"]]
    return ", ".join(steps) or "nothing"


def _schedule_head(view: Mapping[str, object]) -> list[str]:
    """The rollover hour, the pause, and the steps that are due."""
    if view["closes_at_utc"] is None:
        lines = ["automatic days off: no rollover hour in the server config"]
    else:
        lines = [f"rollover hour {_text(view['closes_at_utc'])} UTC"]
    if view["paused"]:
        lines.append(f"paused yes  changed {_text(view['pause_changed_at'])}"
                     f"  note: {_text(view['pause_note'])}")
    else:
        lines.append("paused no")
    if view["due_now"] is not None:
        lines.append(f"due now: {_plan_text(view['due_now'])}")
    return lines


def schedule_lines(view: Mapping[str, object]) -> list[str]:
    """The automatic days: the hour, the pause, the steps that are due,
    the latest day, the lock, and the recent moves.

    view is the schedule view of the console module. The text of a
    move can hold the message of an error, thus it is safe text too.
    """
    lines = _schedule_head(view)
    lines.append(f"now {_text(view['now'])}")
    latest = view["latest"]
    if latest is None:
        lines.append("no stored day")
    else:
        lines.append(f"latest day {_text(latest['day'])}  "
                     f"status {_text(latest['status'])}  "
                     f"closes {_text(latest['closes_at'])}")
    if view["lock_held"]:
        lines.append("a rollover holds the lock")
    if view["next_run"] is not None:
        lines.append(f"next run {_text(view['next_run']['at'])}: "
                     f"{_plan_text(view['next_run'])}")
    lines.append("recent moves:" if view["runs"] else "no recent moves")
    lines.extend(
        f"  {_text(run['started_at'])}  {_text(run['source'])}  "
        f"{_text(run['outcome'])}  "
        f"{','.join(_text(step) for step in run['steps']) or '-'}  "
        f"{_text(run['detail'])}".rstrip()
        for run in view["runs"])
    return lines


def status_lines(*, latest: Mapping[str, object] | None,
                 schedule: Mapping[str, object],
                 player_counts: Mapping[str, int],
                 server_answers: bool | None) -> list[str]:
    """The answer of `sv status`.

    latest is the day row of the latest day, or None with no stored
    day. schedule is the schedule view. player_counts holds a count for
    each player status. server_answers says if the public server
    answered, and None says that the command did not try.
    """
    lines = ["no stored day"] if latest is None \
        else [f"latest {line}" for line in day_rows_lines([latest])]
    lines.extend(_schedule_head(schedule))
    counts = "  ".join(f"{_text(status)}={_text(count)}"
                       for status, count in sorted(player_counts.items()))
    lines.append(f"players {counts or 'none'}")
    match server_answers:
        case None:
            lines.append("public server not checked")
        case True:
            lines.append("public server answers")
        case _:
            lines.append("public server does not answer")
    return lines


# ---- players ----


def roster_lines(rows: Sequence[Mapping[str, object]]) -> list[str]:
    """One line for each player of the roster: the name, the status,
    the counts, the last sign-in, and the label."""
    return [
        f"{_text(row['player'])}  {_text(row['status'])}  "
        f"devices={_text(row['devices'])}  sends={_text(row['sends'])}  "
        f"device_codes={_text(row['device_codes'])}  "
        f"last_signed_in={_text(row['last_signed_in'])}  "
        f"{_text(row['display_name'])}"
        for row in rows] or ["no stored player"]


def player_lines(view: Mapping[str, object]) -> list[str]:
    """One account: the record, the description, the devices, and the
    times of a live operator code.

    view is the player view of the console module. It holds no code
    and no digest of a credential.
    """
    lines = [f"player {_text(view['player'])}",
             f"display name {_text(view['display_name'])}",
             f"status {_text(view['status'])}",
             f"created {_text(view['created_at'])}",
             f"password {_text(view['has_password'])}",
             f"avatar {_text(view['has_avatar'])}",
             f"description: {_text(view['description'] or None)}",
             f"account updated {_text(view['account_updated_at'])}",
             f"sends {_text(view['sends'])}"]
    code = view["operator_code"]
    if code is None:
        lines.append("operator code none")
    else:
        lines.append(f"operator code made {_text(code['issued_at'])}  "
                     f"works from {_text(code['usable_at'])}")
    lines.append(f"devices {len(view['sessions'])}")
    lines.extend(
        f"  {_text(session['id'])[:12]}  {_text(session['created_at'])}  "
        f"ends {_text(session['ends_at'])}  {_text(session['label'])}"
        for session in view["sessions"])
    lines.append(f"device codes {len(view['device_codes'])}")
    return lines


def deletion_preview_lines(preview: Mapping[str, object]) -> list[str]:
    """Step one of a deletion: what goes, what stays, and the command
    for step two. preview is the deletion preview of the players
    module."""
    player = _text(preview["player"])
    days = f"days played {_text(preview['days_played'])} (one send each)"
    if preview["first_day"] is not None:
        days += (f", {_text(preview['first_day'])} to "
                 f"{_text(preview['last_day'])}")
    shown_as = "a new anonymous identifier" \
        if preview["identifier"] is None else _text(preview["identifier"])
    return [
        f"preview: deleting {player} removes "
        f"{'; '.join(_text(item) for item in preview['removes'])}",
        f"it keeps {'; '.join(_text(item) for item in preview['keeps'])}",
        f"{days}, sessions {_text(preview['sessions'])}",
        f"the earlier results will show as {shown_as}",
        "this cannot be undone: restore does not work on a deleted "
        "account, and no one can register the username again",
        f"nothing changed. To delete, run again with --confirm {player}",
    ]


def recovery_code_lines(player: str, code: str, usable_at: str) -> list[str]:
    """The operator's recovery code, when it starts to work, and the
    caution that the code prints one time. code is the display shape
    of the code. The caller prints these lines to a terminal and puts
    them in no file."""
    return [f"player {_text(player)}",
            f"recovery code {_text(code)}",
            f"it works from {_text(usable_at)}",
            "this is the one time the code prints - give it to the "
            "player, then forget it"]


# ---- the results index ----


def index_lines(view: Mapping[str, object]) -> list[str]:
    """The results index: the file, the build time, if it is current,
    and each table with its row count and columns. view is the answer
    of the describe function of the index module."""
    lines = [f"index {_text(view['path'])}",
             f"exists {_text(view['exists'])}",
             f"schema version {_text(view['schema_version'])}",
             f"built {_text(view['built_at'])}",
             f"current {_text(view['current'])}"]
    if view["problem"] is not None:
        lines.append(f"problem: {_text(view['problem'])}")
    lines.extend(
        f"  {_text(table['name'])}  rows={_text(table['rows'])}  "
        f"{'view' if table['view'] else 'table'}  "
        f"{','.join(_text(column) for column in table['columns'])}"
        for table in view["tables"])
    return lines


def verify_lines(view: Mapping[str, object]) -> list[str]:
    """If the index agrees with the store. view holds `agrees` and one
    text in `problems` for each table that does not agree."""
    if view["agrees"]:
        return ["the index agrees with the store"]
    return [*(_text(problem) for problem in view["problems"]),
            "the index does not agree with the store"]


def query_lines(answer: Mapping[str, object]) -> list[str]:
    """The answer of one read-only query as aligned columns.

    answer holds `columns`, `rows`, `truncated`, and `elapsed_ms`. A
    cell of SQL NULL prints as `NULL`, as the console shows it. A line
    at the end says so when the answer is cut at the row limit.
    """
    rows = [["NULL" if cell is None else _text(cell) for cell in row]
            for row in answer["rows"]]
    lines = _table([safe_text(str(column)) for column in answer["columns"]],
                   rows)
    lines.append(f"{len(rows)} rows  {_text(answer['elapsed_ms'])} ms")
    if answer["truncated"]:
        lines.append("truncated: more rows agree with the query than this "
                     "answer shows")
    return lines


# ---- the operator journal ----


def _fact_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(_text(item) for item in value)
    return _text(value)


def _journal_line(start: Mapping[str, object] | None,
                  end: Mapping[str, object] | None) -> str:
    """One command of the journal, from its two records."""
    first = end if start is None else start
    parts = [_text(first["at"]),
             f"{_text(first['login'])} ({_text(first['login_source'])})",
             _text(first["command"])]
    for key in ("player", "day"):
        # The `start` record of `sv day open` has no day: the server
        # gives the label, and only the `end` record holds it.
        named = [record[key] for record in (start, end)
                 if record is not None and record.get(key) is not None]
        if named:
            parts.append(f"{key}={_text(named[0])}")
    if start is None:
        parts.append("start not recorded")
    if end is None:
        parts.append("outcome not recorded")
    else:
        parts.append(_text(end["outcome"]))
    facts = {**((start or {}).get("facts") or {}),
             **((end or {}).get("facts") or {})}
    parts.extend(f"{_text(key)}={_fact_text(value)}"
                 for key, value in sorted(facts.items()))
    if end is not None and end.get("error_kind") is not None:
        parts.append(f"error={_text(end['error_kind'])}")
    return "  ".join(parts)


def journal_lines(entries: Sequence[Mapping[str, object]]) -> list[str]:
    """One line for each command of the operator journal.

    Each entry is one record as a mapping, with the fields of the
    journal of spec OC1 section 7. The `start` record and the `end`
    record of one command have the same `entry_id`, and they make one
    line at the position of the first of the two. A `start` with no
    `end` shows `outcome not recorded`. Raises ValueError for a phase
    that the journal does not have.
    """
    starts: dict[object, Mapping[str, object]] = {}
    ends: dict[object, Mapping[str, object]] = {}
    sequence: list[object] = []
    for entry in entries:
        entry_id = entry["entry_id"]
        if entry_id not in starts and entry_id not in ends:
            sequence.append(entry_id)
        match entry["phase"]:
            case "start":
                starts[entry_id] = entry
            case "end":
                ends[entry_id] = entry
            case other:
                raise ValueError(f"unknown journal phase {other!r}")
    return [_journal_line(starts.get(entry_id), ends.get(entry_id))
            for entry_id in sequence] or ["no journal entry"]


# ---- JSON and CSV ----


def to_json(value: object) -> str:
    """The value as JSON text with sorted keys.

    Each character that is not ASCII, and each control character,
    becomes a code of JSON, thus the text is safe on a terminal.
    """
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True)


def _csv_cell(value: object, terminal: bool) -> str:
    text = "" if value is None else str(value)
    if terminal:
        text = safe_text(text)
    if any(mark in text for mark in '",\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def to_csv(columns: Sequence[object], rows: Sequence[Sequence[object]], *,
           terminal: bool = False) -> str:
    """The columns and the rows as RFC 4180 CSV, with CRLF line ends.

    The same rules as the CSV download of the console: a cell with a
    quotation mark, a comma, or a line end goes in quotation marks, and
    SQL NULL is an empty cell. With terminal on, each cell goes through
    `safe_text` first: the caller gives it when the text goes to a
    terminal and not to a file or a pipe.
    """
    lines = [",".join(_csv_cell(column, terminal) for column in columns)]
    lines.extend(",".join(_csv_cell(cell, terminal) for cell in row)
                 for row in rows)
    return "\r\n".join(lines) + "\r\n"
