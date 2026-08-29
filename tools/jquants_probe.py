"""Answer one question about the J-Quants Free tier, and nothing else.

Does the summary-only financial information the Free plan includes carry the
disclosure *time*? The plan page lists 「財務情報（サマリーのみ）」 without saying
which fields the summary drops, and the whole free path for timing provenance
turns on that one field. It is not guessable, and it is one request away.

So this asks, reports which fields came back, and stops. It writes nothing,
stores no disclosure, and touches no part of the research record — a probe, not
an adapter. The adapter comes after the source is approved for a use, and no
source is approved for any use yet.

    export $(grep -v '^#' ~/.config/ers/.env | xargs)
    python tools/jquants_probe.py [YYYYMMDD]

The key is read from the environment. It is never printed, never logged, and
never written to a file.

Written first against V1, which is closed. V1 authenticated by exchanging a
refresh token for an ID token and sending `Authorization: Bearer`; V2 issues a
key from the dashboard and expects it in `x-api-key`, and the two headers may
not be sent together. `/v1/fins/statements` became `/v2/fins/summary`. The
first run returned 403 on all three counts at once.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = "https://api.jquants.com/v2"
TIMEOUT = 30

# What the answer hinges on. If the disclosure time is absent, the free path
# for timing provenance does not exist — the announcement *schedule* is all
# that is left, and a schedule read in advance cannot confirm that a
# publication occurred (ERS-ADR-0062).
WANTED = ("DiscDate", "DiscTime")


def get(path, params, key):
    query = "&".join("%s=%s" % (k, v) for k, v in params.items())
    url = "%s%s?%s" % (BASE, path, query) if query else BASE + path
    # V2 authenticates by key alone. Sending Authorization alongside it is
    # rejected, so the header this probe does not set matters as much as the
    # one it does.
    request = urllib.request.Request(url, headers={"x-api-key": key})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def rows_in(payload):
    """The rows, and the envelope key they arrived under.

    The response shape is not documented on the page that lists the fields, and
    guessing a key is how the first version got the endpoint wrong too.
    """
    if isinstance(payload, list):
        return payload, "(top level)"
    for name, value in sorted(payload.items()):
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value, name
    return [], "(none found)"


def main():
    key = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not key:
        print("JQUANTS_API_KEY is not set. Load it with:", file=sys.stderr)
        print("  export $(grep -v '^#' ~/.config/ers/.env | xargs)", file=sys.stderr)
        return 2

    if len(sys.argv) > 1:
        day = date(int(sys.argv[1][:4]), int(sys.argv[1][4:6]), int(sys.argv[1][6:8]))
    else:
        # Well outside the Free plan's twelve-week exclusion, so an empty
        # result means the field or the plan, not the date.
        day = date.today() - timedelta(weeks=20)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
    print("asking for financial summaries disclosed on %s" % day)

    try:
        payload = get("/fins/summary", {"date": day.strftime("%Y%m%d")}, key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print("HTTP %s — %s" % (exc.code, detail), file=sys.stderr)
        if exc.code == 401:
            print("\nThe key was rejected. Reissue it from the dashboard and "
                  "rewrite ~/.config/ers/.env.", file=sys.stderr)
        elif exc.code == 403:
            print("\nThe key is accepted but this endpoint is outside the plan, "
                  "or the date falls inside the excluded recent window.", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print("could not reach the API: %s" % exc.reason, file=sys.stderr)
        return 1

    rows, envelope = rows_in(payload)
    print("envelope key: %s" % envelope)
    print("rows returned: %d" % len(rows))
    if not rows:
        print("\nNo rows for that date. Try another weekday before concluding "
              "the plan excludes the endpoint:")
        print("  python tools/jquants_probe.py 20260508")
        return 0

    fields = sorted(rows[0])
    print("fields returned: %d" % len(fields))
    print("\n--- the question")
    for name in WANTED:
        mark = "yes" if name in fields else "no "
        # One sample value, and only for the time field — a disclosure
        # timestamp, not disclosure content.
        sample = ""
        if name in fields and "Time" in name:
            sample = "   e.g. %r" % rows[0][name]
        print("  %-10s %s%s" % (name, mark, sample))

    populated = [
        r for r in rows
        if any("Time" in f and str(r.get(f) or "").strip() for f in WANTED)
    ]
    print("  rows with a non-empty time: %d / %d" % (len(populated), len(rows)))

    print("\n--- verdict")
    if populated:
        print("  The Free tier carries a disclosure time. The zero-cost timing")
        print("  path exists, on the twelve-week delay.")
    elif any("Time" in f for f in fields if f in WANTED):
        print("  The time field is present but empty on this date. Declared and")
        print("  unpopulated is not a source; try another date before deciding.")
    else:
        print("  No disclosure time in this response. The free path for timing")
        print("  provenance does not exist; only the announcement schedule does,")
        print("  and a schedule is not a confirmation.")

    missing = [f for f in WANTED if f not in fields]
    if missing:
        print("\n  absent: %s" % ", ".join(missing))
    print("\n--- all field names (for the review table)")
    print("  " + ", ".join(fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
