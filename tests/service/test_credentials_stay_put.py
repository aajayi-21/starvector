"""No credential is in the server output, an answer, the results
index, or an export (spec A2 sections 5.3 and 11).

One world signs up, signs in, recovers, changes the password, and gets
each type of code, with marker strings. The test then scans each
captured line, each answer body, the index file, and the two exports.
"""

import dataclasses
import datetime
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         mixed_wire_record)

from service import auth, index, signin, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

DAY = "2026-08-12"
TOKEN = "test-operator-token"
ORIGIN = {"origin": "https://testserver"}
FIRST_PASSWORD = "marker-password-one-AAAA"
SECOND_PASSWORD = "marker-password-two-BBBB"
THIRD_PASSWORD = "marker-password-three-CC"


def test_no_credential_is_in_the_output_an_answer_or_the_index(
        tmp_path, caplog) -> None:
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"], signup="open")
    root = Path(config.store_root)
    app = create_app(config, operator_token=TOKEN, digester=QuickDigester(),
                     usual_passwords=frozenset())
    client = TestClient(app, base_url="https://testserver", headers=ORIGIN)
    bodies: list[tuple[str, str]] = []

    def post(path: str, body: dict | None = None):
        answer = client.post(path, json=body)
        bodies.append((path, answer.text))
        return answer

    with caplog.at_level(logging.DEBUG):
        made = post("/api/signup", {"username": "marker-name",
                                    "password": FIRST_PASSWORD})
        assert made.status_code == 201
        first_code = made.json()["recovery_code"]
        assert post("/api/signin", {"username": "marker-name",
                                    "password": "not-the-password!"}
                    ).status_code == 401
        assert post("/api/signin", {"username": "marker-name",
                                    "password": FIRST_PASSWORD}
                    ).status_code == 200
        recovered = post("/api/recover", {
            "username": "marker-name", "recovery_code": first_code,
            "password": SECOND_PASSWORD})
        assert recovered.status_code == 200
        second_code = recovered.json()["recovery_code"]
        assert post("/api/account/password", {
            "current_password": SECOND_PASSWORD,
            "password": THIRD_PASSWORD}).status_code == 200
        third_code = post("/api/account/recovery-code", {
            "current_password": THIRD_PASSWORD}).json()["recovery_code"]
        operator = client.post(
            "/api/dev/players/marker-name/recovery-code",
            headers={"Authorization": f"Bearer {TOKEN}"})
        # The dev plane is off in this app: the path answers the
        # constant 404, and the operator's code comes from the module.
        assert operator.status_code == 404
        operator_code, _usable = signin.issue_operator_code(
            root, player="marker-name",
            instant=datetime.datetime.now(datetime.UTC))
        for path in ("/api/me", "/api/sessions", "/api/me/export"):
            bodies.append((path, client.get(path).text))
        # One played and revealed day, thus the index holds a trial row.
        open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
                 pick_seed="a" * 32, secret="b" * 64)
        store.write_once_json(
            store.submission_path(root, DAY, "marker-name"),
            {"day": DAY, "player": "marker-name", "trial_id": "f" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
        close_day(config, clock=lambda: FIXED_CLOCK)
        reveal_day(config, clock=lambda: FIXED_CLOCK)
        bodies.append(("/api/me/export", client.get("/api/me/export").text))

    credential = store.read_credential_or_none(root, "marker-name")
    codes = [auth.normalize_recovery_code(code) for code in
             (first_code, second_code, third_code)] + [operator_code]
    passwords = [FIRST_PASSWORD, SECOND_PASSWORD, THIRD_PASSWORD]
    digests = [credential.password_digest, credential.recovery_digest,
               credential.operator_digest]
    digests += [auth.recovery_code_hash(code) for code in codes]
    shown_codes = [auth.display_recovery_code(code) for code in codes]

    # The server output: no password, no code, and no digest.
    output = caplog.text
    for secret in passwords + codes + shown_codes + digests:
        assert secret not in output

    # The answers: a recovery code is in the answer that makes it and
    # in no other one. No password and no digest is in an answer.
    issuing = {"/api/signup", "/api/recover", "/api/account/recovery-code"}
    for path, text in bodies:
        for secret in passwords + digests:
            assert secret not in text, path
        if path not in issuing:
            for code in codes + shown_codes:
                assert code not in text, path

    # The results index and the research export.
    target = index.index_path(Path(config.data_root))
    index.build(root, target)
    raw = target.read_bytes()
    index.export(target, tmp_path / "export", salt="s3cret",
                 file_format="jsonl")
    exported = b"".join(path.read_bytes()
                        for path in (tmp_path / "export").rglob("*")
                        if path.is_file())
    for secret in passwords + codes + shown_codes + digests:
        assert secret.encode("utf-8") not in raw
        assert secret.encode("utf-8") not in exported
    # The index does hold the player: the username is the key.
    assert b"marker-name" in raw


def test_the_index_builder_reads_no_credential_directory(tmp_path) -> None:
    """The fence of spec A2 section 11: the files that the index reads
    are below days, players, and accounts, and no other directory."""
    fixture = build_service_fixture(tmp_path)
    root = Path(fixture["service_config"].store_root)
    signin.sign_up(root, username="alice",
                   password="correct horse battery",
                   digester=QuickDigester(), usual=frozenset(),
                   instant=datetime.datetime.now(datetime.UTC))
    assert store.credential_record_path(root, "alice").is_file()
    assert store.name_claim_path(root, "alice").is_file()
    read = {path.relative_to(root).parts[0]
            for path in index._record_files(root)}
    assert read <= {"days", "players", "accounts"}
    before = index.store_fingerprint(root)
    # A credential move changes no file that the index reads.
    signin.issue_operator_code(root, player="alice",
                               instant=datetime.datetime.now(datetime.UTC))
    assert index.store_fingerprint(root) == before
    source = Path(index.__file__).read_text(encoding="utf-8")
    for word in ("credential", "names_dir", "name_claim"):
        assert word not in source.split('"""', 2)[2].replace(
            "Credentials.", "")
