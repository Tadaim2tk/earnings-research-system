"""Answer one question about the J-Quants Free tier, and nothing else.

Does the summary-only financial statements the Free plan includes carry the
disclosure *time*? The plan page lists 「財務情報（サマリーのみ）」 without saying
which fields the summary drops, and the whole free path for timing provenance
turns on that one field. It is not guessable, and it is one request away.

So this asks, reports which fields came back, and stops. It writes nothing,
stores no disclosure, and touches no part of the research record — a probe, not
an adapter. The adapter comes after the source is approved for a use, and no
source is approved for any use yet.

    export $(grep -v '^#' ~/.config/ers/.env | xargs)
    python tools/jquants_probe.py

The key is read from the environment. It is never printed, never logged, and
never written to a file.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = "https://api.jquants.com/v1"
TIMEOUT = 30

# What the answer hinges on. If the disclosure time is absent, the free path
# for timing provenance does not exist — the announcement *schedule* is all
# that is left, and a schedule read in advance cannot confirm that a
# publication occurred (ERS-ADR-0062).
WANTED = ("DisclosedDate", "DisclosedTime", "DiscDate", "DiscTime")


def get(path, params, key):
    query = "&".join("%s=%s" % (k, v) for k, v in params.items())
    url = "%s%s?%s" % (BASE, path, query) if query else BASE + path
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def main():
    key = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not key:
        print("JQUANTS_API_KEY is not set. Load it with:", file=sys.stderr)
        print("  export $(grep -v '^#' ~/.config/ers/.env | xargs)", file=sys.stderr)
        return 2

    # Well outside the Free plan's twelve-week exclusion, so an empty result
    # means the field or the plan, not the date.
    day = date.today() - timedelta(weeks=20)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    print("asking for statements disclosed on %s" % day)

    try:
        payload = get("/fins/statements", {"date": day.isoformat()}, key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print("HTTP %s — %s" % (exc.code, detail), file=sys.stderr)
        if exc.code in (401, 403):
            print("\nThe key was rejected, or this endpoint is outside the plan.", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print("could not reach the API: %s" % exc.reason, file=sys.stderr)
        return 1

    rows = payload.get("statements") or []
    print("rows returned: %d" % len(rows))
    if not rows:
        print("\nNo rows for that date. Try another weekday before concluding "
              "the plan excludes the endpoint.")
        return 0

    fields = sorted(rows[0])
    print("fields returned: %d" % len(fields))
    present = [f for f in WANTED if f in fields]
    missing = [f for f in WANTED if f not in fields]
    print("\n--- the question")
    for name in WANTED:
        mark = "yes" if name in fields else "no "
        # One sample value, and only for the time fields — a disclosure
        # timestamp, not disclosure content.
        sample = ""
        if name in fields and "Time" in name:
            sample = "   e.g. %r" % rows[0][name]
        print("  %-16s %s%s" % (name, mark, sample))

    print("\n--- verdict")
    if any("Time" in f for f in present):
        print("  The Free tier carries a disclosure time. The zero-cost timing")
        print("  path exists, on the twelve-week delay.")
    else:
        print("  No disclosure time in this response. The free path for timing")
        print("  provenance does not exist; only the announcement schedule does,")
        print("  and a schedule is not a confirmation.")
    if missing:
        print("\n  absent: %s" % ", ".join(missing))
    print("\n--- all field names (for the review table)")
    print("  " + ", ".join(fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
