#!/usr/bin/env python3
"""
Fetch the Vermont SOS election-results XML feed once and write one CSV per
race listed in races.json, for use as Datawrapper "linked external data".

Safety behavior:
  * A race is matched by EXACT office name + EXACT district (case/whitespace
    insensitive). Zero matches or more than one match is an error for that
    race -- it never silently picks the wrong one.
  * If the feed can't be fetched or parsed, NO csv is touched, so Datawrapper
    keeps showing the last good data.
  * If one race fails, the others are still written. Exit code is 1 if any
    race failed, so the failure is visible in the Actions log.
  * Candidate is a display name: Title Case + party initials, e.g.
    "Sarah George (D/P)". Odd capitalizations (DeFazio, etc.) can be fixed
    with "name_overrides" in races.json: {"JOHN DEFAZIO": "John DeFazio"}.
  * CSVs are written only if their content changed (stable output, so git
    only sees a diff when the numbers actually move).

Usage:
  python fetch_races.py                      # live feed from races.json
  python fetch_races.py --feed-file x.xml    # test against a local file
"""

import argparse
import csv
import io
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FIELDS = ["Candidate", "Party", "Votes", "Percent", "Winner"]


def norm(s):
    return " ".join((s or "").upper().split())


def load_xml_from_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (results-bot)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return ET.fromstring(resp.read())


def load_xml_from_file(path):
    return ET.parse(path).getroot()


def find_offices(root, office, district):
    want_office, want_district = norm(office), norm(district)
    return [
        o
        for o in root.iter("Office")
        if norm(o.findtext("OfficeName")) == want_office
        and norm(o.findtext("OfficeDistrict")) == want_district
    ]


SUFFIXES = {"JR": "Jr.", "SR": "Sr.", "II": "II", "III": "III", "IV": "IV"}


def _title_token(tok):
    """Title-case one space-separated token (handles O'BRIEN, MCRAE, hyphens)."""
    if "-" in tok:
        return "-".join(_title_token(t) for t in tok.split("-"))
    bare = tok.strip(".,").upper()
    if bare in SUFFIXES:
        return SUFFIXES[bare] + ("," if tok.endswith(",") else "")
    if len(bare) == 1:  # middle initial
        return tok.upper()
    if "'" in tok:
        return "'".join(p[:1].upper() + p[1:].lower() for p in tok.split("'"))
    if bare.startswith("MC") and len(bare) > 2:
        return "Mc" + tok[2:3].upper() + tok[3:].lower()
    return tok[:1].upper() + tok[1:].lower()


def title_case(name):
    return " ".join(_title_token(t) for t in name.split())


def party_initials(party):
    """'DEM/PROG' -> 'D/P', 'REPUBLICAN' -> 'R'. Empty if no party."""
    parts = [p.strip() for p in (party or "").split("/") if p.strip()]
    return "/".join(p[0].upper() for p in parts)


def display_name(name, party, overrides=None):
    key = " ".join((name or "").upper().split())
    base = (overrides or {}).get(key) or title_case(name)
    initials = party_initials(party)
    return f"{base} ({initials})" if initials else base


def to_int(text):
    try:
        return int((text or "0").strip().replace(",", ""))
    except ValueError:
        return 0


def build_rows(office_el, overrides=None):
    cands = []
    for i, c in enumerate(office_el.findall("Candidate")):
        cands.append(
            {
                "order": i,
                "Candidate": display_name(
                    c.findtext("Name"), c.findtext("PartyName"), overrides
                ),
                "Party": " ".join((c.findtext("PartyName") or "").split()),
                "Votes": to_int(c.findtext("Votes")),
                "Winner": (c.findtext("Winner") or "").strip().lower() == "true",
            }
        )
    total = sum(c["Votes"] for c in cands)
    for c in cands:
        c["Percent"] = round(c["Votes"] / total * 100, 1) if total else 0.0
    # Leader first; ties keep the feed's own order so the chart doesn't jitter.
    cands.sort(key=lambda c: (-c["Votes"], c["order"]))
    return cands


def render_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({**r, "Winner": "Yes" if r["Winner"] else ""})
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("races.json")))
    ap.add_argument("--feed-file", help="read this local XML instead of fetching the feed")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out_dir = Path(config.get("output_dir", "data"))
    out_dir.mkdir(parents=True, exist_ok=True)

    feeds = {}  # url -> parsed root, so each distinct feed is fetched once
    failures = 0

    for race in config["races"]:
        slug = race["slug"]
        label = f'{race["office"]} / {race["district"]}'
        try:
            if args.feed_file:
                key = args.feed_file
                if key not in feeds:
                    feeds[key] = load_xml_from_file(key)
            else:
                key = race.get("feed_url") or config["feed_url"]
                if key not in feeds:
                    feeds[key] = load_xml_from_url(key)
            root = feeds[key]

            matches = find_offices(root, race["office"], race["district"])
            if len(matches) != 1:
                raise ValueError(f"expected exactly 1 matching race, found {len(matches)}")

            rows = build_rows(matches[0], config.get("name_overrides"))
            if not rows:
                raise ValueError("race found but it has no candidates")

            text = render_csv(rows)
            path = out_dir / f"{slug}.csv"
            if path.exists() and path.read_text(encoding="utf-8") == text:
                print(f"[unchanged] {slug}")
            else:
                path.write_text(text, encoding="utf-8")
                print(f"[updated]   {slug}")
            for r in rows:
                print(f"              {r['Candidate']} ({r['Party']}): {r['Votes']} ({r['Percent']}%)")
        except Exception as e:  # keep going so one bad race doesn't block the rest
            failures += 1
            print(f"[FAILED]    {slug} ({label}): {e}", file=sys.stderr)

    if failures:
        print(f"\n{failures} race(s) failed; their CSVs were left untouched.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
