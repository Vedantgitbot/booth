"""Verify this published reply snapshot and recount its saved results offline."""

from collections import Counter
import hashlib
import json
from pathlib import Path

EVIDENCE_SHA256 = "e1eed0a8fbe01cba266fff33a50edc1cd5b609324f5ead10481ea41c3a97fdb1"
PHASES = {"smoke": 3, "main": 30}
GRADES = ("correct", "wrong", "unscoreable")
CHECKPOINTS = {
    "check": ("Plain check", {"ACCEPTED"}),
    "validator": ("Numeric validator", {"ACCEPTED", "UNCERTAIN"}),
    "keyword_evidence": ("Keyword evidence", {"ACCEPTED", "BLOCKED"}),
    "numeric_evidence": ("Numeric evidence", {"ACCEPTED", "BLOCKED"}),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(rows):
    expected_ids = {
        (phase, f"{phase}_{number:02d}")
        for phase, count in PHASES.items()
        for number in range(1, count + 1)
    }
    actual_ids = {(row["phase"], row["case_id"]) for row in rows}
    require(len(rows) == len(expected_ids) and actual_ids == expected_ids, "case coverage")

    for row in rows:
        case = row["case_id"]
        raw = row["raw_reply"]
        require(sha256(raw.encode("utf-8")) == row["raw_reply_sha256"], f"{case}: raw reply hash")
        lines = raw.splitlines()
        require(lines[:1] == ["```json"] and lines[-1:] == ["```"], f"{case}: reply wrapper")
        reply = json.loads("\n".join(lines[1:-1]))
        require(reply["answer"] == row["answer"] and reply["confidence"] == row["confidence"], f"{case}: reply fields")
        require(row["grade"] in GRADES, f"{case}: grade")
        statuses = row["statuses"]
        require(set(statuses) == set(CHECKPOINTS), f"{case}: checkpoint coverage")
        for arm, (_, allowed_statuses) in CHECKPOINTS.items():
            require(statuses[arm] in allowed_statuses, f"{case}: {arm} status")

        numeric_passed = statuses["numeric_evidence"] == "ACCEPTED"
        require(numeric_passed == (statuses["validator"] == "ACCEPTED"), f"{case}: numeric decisions")
        supported = row["source_supported"] and row["answer_supported"]
        if numeric_passed:
            require(supported, f"{case}: accepted without supported quantities")
        else:
            require(
                not supported and row["numeric_reason"] in (
                    "unsupported quantity grammar", "explicit unit or currency required",
                ),
                f"{case}: withholding stage",
            )


def main_table(rows):
    grades = Counter(row["grade"] for row in rows)
    lines = [
        f"| Checkpoint | Accepted / {len(rows)} | Correct withheld / {grades['correct']} | "
        f"Wrong accepted / {grades['wrong']} | Unscoreable accepted / {grades['unscoreable']} |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm, (name, _) in CHECKPOINTS.items():
        accepted = Counter(row["grade"] for row in rows if row["statuses"][arm] == "ACCEPTED")
        lines.append(
            f"| {name} | {sum(accepted.values())} | {grades['correct'] - accepted['correct']} | "
            f"{accepted['wrong']} | {accepted['unscoreable']} |"
        )
    return "\n".join(lines)


def main():
    folder = Path(__file__).resolve().parent
    try:
        # The snapshot uses LF. Git may check it out with CRLF on Windows.
        data = (folder / "replies.jsonl").read_bytes().replace(b"\r\n", b"\n")
        require(sha256(data) == EVIDENCE_SHA256, "replies.jsonl SHA-256 differs from the published snapshot")
        rows = [json.loads(line) for line in data.decode("utf-8").splitlines()]
        verify(rows)
        main_rows = [row for row in rows if row["phase"] == "main"]
        table = main_table(main_rows)
        report = (folder / "RESULTS.md").read_text(encoding="utf-8")
        require(table in report, "RESULTS.md table differs from the saved results")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise SystemExit(f"Verification failed: {error}") from None

    print(f"Verified {len(rows)} saved replies and the report table.")
    for phase in PHASES:
        counts = Counter(row["grade"] for row in rows if row["phase"] == phase)
        print(f"{phase}: " + ", ".join(f"{counts[grade]} {grade}" for grade in GRADES))
    reasons = Counter(
        row["numeric_reason"] for row in main_rows
        if row["statuses"]["numeric_evidence"] != "ACCEPTED"
    )
    print("Main numeric withholds: " + ", ".join(f"{count} {reason}" for reason, count in sorted(reasons.items())))
    print(table)


if __name__ == "__main__":
    main()
