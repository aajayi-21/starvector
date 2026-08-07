#!/usr/bin/env python3
"""Generate Vale ASD-STE100 styles from the Issue 9 JSON exports.

Inputs (repo root):
  asdste100_issue9_base_names_lower.jsonl  -- controlled dictionary
  asdste100_issue9_technical_words.jsonl   -- approved technical nouns/verbs
  asdste100_issue9_rules.json              -- the writing rules (for messages/refs)

Outputs:
  .vale/styles/ASD-STE100/*.yml
  .vale/styles/config/vocabularies/ASD-STE100/accept.txt
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_DIR = ROOT / ".vale/styles/ASD-STE100"
VOCAB_DIR = ROOT / ".vale/styles/config/vocabularies/ASD-STE100"

BRACKET = re.compile(r"^(.*?)\s*\[(.*)\]$")
WORDLIKE = re.compile(r"^[a-z0-9][a-z0-9' -]*[a-z0-9]$|^[a-z0-9]$")


def q(s: str) -> str:
    """JSON-quote a string; valid as a YAML double-quoted scalar."""
    return json.dumps(s, ensure_ascii=False)


def token_of(name: str) -> str:
    """Entry names like 'long [as long as]' reject the bracketed usage."""
    m = BRACKET.match(name)
    return m.group(2).strip() if m else name.strip()


def to_regex_key(token: str) -> str:
    """Escape a dictionary token into a substitution key; spaces match any whitespace."""
    parts = [re.escape(p) for p in token.split()]
    return r"\s+".join(parts)


def main() -> None:
    base = [json.loads(l) for l in
            (ROOT / "asdste100_issue9_base_names_lower.jsonl").read_text().splitlines() if l.strip()]
    tech = [json.loads(l) for l in
            (ROOT / "asdste100_issue9_technical_words.jsonl").read_text().splitlines() if l.strip()]

    # --- Group dictionary entries by usage token ------------------------------
    by_token = defaultdict(list)
    for e in base:
        by_token[token_of(e["name"])].append(e)

    tech_names = {t["name"].strip().strip("'").lower() for t in tech}

    skipped = []
    swap = {}          # rejected token -> "alt1, alt2"
    no_alt = []        # rejected tokens with no approved alternative
    for tok, entries in sorted(by_token.items()):
        statuses = {e["status"] for e in entries}
        if statuses != {"rejected"}:
            continue  # approved in at least one part of speech: not checkable without POS
        if tok.lower() in tech_names:
            continue  # approved technical noun/verb overrides the rejection
        if not WORDLIKE.match(tok):
            skipped.append(tok)
            continue
        alts = []
        for e in entries:
            for a in e.get("alternatives") or []:
                nm = a["name"].strip()
                if nm and nm.lower() not in (x.lower() for x in alts):
                    alts.append(nm)
        if alts:
            swap[tok] = ", ".join(alts)
        else:
            no_alt.append(tok)

    # --- Approved verb forms: [3rd person, past, past participle] -------------
    participles = set()
    for e in base:
        if e.get("type_") == "v" and e["status"] == "approved" and len(e.get("spellings") or []) >= 3:
            participles.add(e["spellings"][2].lower())
    parts_alt = "|".join(sorted(participles, key=lambda s: (-len(s), s)))

    STYLE_DIR.mkdir(parents=True, exist_ok=True)
    VOCAB_DIR.mkdir(parents=True, exist_ok=True)

    # --- Rejected.yml ----------------------------------------------------------
    lines = [
        "extends: substitution",
        'message: "Use %s instead of \'%s\': not an approved word (ASD-STE100 Issue 9, R1.1)."',
        "link: https://asd-ste100.org",
        "level: error",
        "ignorecase: true",
        "action:",
        "  name: replace",
        "swap:",
    ]
    for tok, alts in sorted(swap.items()):
        lines.append(f"  {q(to_regex_key(tok))}: {q(alts)}")
    (STYLE_DIR / "Rejected.yml").write_text("\n".join(lines) + "\n")

    # --- RejectedNoAlternative.yml ---------------------------------------------
    lines = [
        "extends: existence",
        "message: \"'%s' is not an approved word and has no direct replacement: rewrite the sentence (ASD-STE100 Issue 9, R1.1).\"",
        "link: https://asd-ste100.org",
        "level: error",
        "ignorecase: true",
        "tokens:",
    ]
    for tok in sorted(no_alt):
        lines.append(f"  - {q(to_regex_key(tok))}")
    (STYLE_DIR / "RejectedNoAlternative.yml").write_text("\n".join(lines) + "\n")

    # --- Passive.yml (be + approved past participle) ---------------------------
    raw = rf"\b(?:am|is|are|was|were|be|been|being)\s+(?:{parts_alt})\b"
    (STYLE_DIR / "Passive.yml").write_text(
        "extends: existence\n"
        "message: \"'%s' is passive voice. Use the active voice; passive is allowed only in descriptive text when the agent is unknown or unimportant (ASD-STE100 Issue 9, R3.6).\"\n"
        "link: https://asd-ste100.org\n"
        "level: warning\n"
        "ignorecase: true\n"
        "raw:\n"
        f"  - {q(raw)}\n"
    )

    # --- ComplexVerbs.yml (perfect tenses / auxiliary constructions) -----------
    raw = rf"\b(?:has|have|had)\s+(?:been\s+)?(?:{parts_alt})\b"
    (STYLE_DIR / "ComplexVerbs.yml").write_text(
        "extends: existence\n"
        "message: \"'%s' is a complex verb construction. Use only the simple present, past, or future (ASD-STE100 Issue 9, R3.4).\"\n"
        "link: https://asd-ste100.org\n"
        "level: warning\n"
        "ignorecase: true\n"
        "raw:\n"
        f"  - {q(raw)}\n"
    )

    # --- Contractions.yml -------------------------------------------------------
    (STYLE_DIR / "Contractions.yml").write_text(
        "extends: existence\n"
        "message: \"'%s' is a contraction. Write the words in full (ASD-STE100 Issue 9, R4.2).\"\n"
        "link: https://asd-ste100.org\n"
        "level: error\n"
        "ignorecase: true\n"
        "tokens:\n"
        "  - \"\\\\w+n['\\u2019]t\"\n"
        "  - \"\\\\w+['\\u2019](?:ll|re|ve|d)\"\n"
        "  - \"(?:it|that|there|what|let|he|she|who)['\\u2019]s\"\n"
    )

    # --- Semicolon.yml -----------------------------------------------------------
    (STYLE_DIR / "Semicolon.yml").write_text(
        "extends: existence\n"
        "message: \"Do not use the semicolon. Write two sentences or use a vertical list (ASD-STE100 Issue 9, R8.1).\"\n"
        "link: https://asd-ste100.org\n"
        "level: error\n"
        "nonword: true\n"
        "tokens:\n"
        "  - ';'\n"
    )

    # --- SentenceLength.yml ------------------------------------------------------
    (STYLE_DIR / "SentenceLength.yml").write_text(
        "extends: occurrence\n"
        "message: \"Sentence is longer than 25 words. Use no more than 25 words in descriptive text and 20 in procedures (ASD-STE100 Issue 9, R5.1 / R6.3).\"\n"
        "link: https://asd-ste100.org\n"
        "level: warning\n"
        "scope: sentence\n"
        "max: 25\n"
        "token: '[^\\s]+'\n"
    )

    # --- ParagraphLength.yml -------------------------------------------------------
    (STYLE_DIR / "ParagraphLength.yml").write_text(
        "extends: occurrence\n"
        "message: \"Paragraph has more than 6 sentences. Divide it (ASD-STE100 Issue 9, R6.6).\"\n"
        "link: https://asd-ste100.org\n"
        "level: suggestion\n"
        "scope: paragraph\n"
        "max: 6\n"
        "token: '[.!?](?:\\s|$)'\n"
    )

    # --- LatinAbbreviations.yml ------------------------------------------------------
    (STYLE_DIR / "LatinAbbreviations.yml").write_text(
        "extends: substitution\n"
        "message: \"Use '%s' instead of the Latin abbreviation '%s' (ASD-STE100 Issue 9, GR-6).\"\n"
        "link: https://asd-ste100.org\n"
        "level: warning\n"
        "ignorecase: true\n"
        "nonword: true\n"
        "swap:\n"
        "  '\\be\\.g\\.': for example\n"
        "  '\\bi\\.e\\.': that is\n"
        "  '\\betc\\.': and so on\n"
        "  '\\bet al\\.': and others\n"
        "  '\\bviz\\.': that is\n"
        "  '\\bcf\\.': compare with\n"
        "  '\\bN\\.B\\.': note\n"
    )

    # --- Vocabulary --------------------------------------------------------------
    accept = []
    for t in tech:
        name = t["name"].strip().strip("'").strip()
        if not name or name.isdigit():
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9' ./()-]*", name):
            continue
        accept.append(name.replace(".", r"\.").replace("(", r"\(").replace(")", r"\)"))
    seen = set()
    uniq = [a for a in accept if not (a.lower() in seen or seen.add(a.lower()))]
    (VOCAB_DIR / "accept.txt").write_text("\n".join(sorted(uniq, key=str.lower)) + "\n")

    print(f"swap entries:        {len(swap)}")
    print(f"no-alternative:      {len(no_alt)}")
    print(f"participles:         {len(participles)}")
    print(f"vocab accepted:      {len(uniq)} (of {len(tech)})")
    print(f"skipped odd tokens:  {skipped}")


if __name__ == "__main__":
    sys.exit(main())
