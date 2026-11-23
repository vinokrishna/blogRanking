#!/usr/bin/env python3
"""
blog_ranking.py - rank blog posts for a quarterly award, fairly across publish dates.

Each post is scored on its visitors, adjusted for how long it has been live,
and then given a percentage share of the quarter. See logic.md for the reasoning.

Usage:
    python3 blog_ranking.py posts.csv --quarter Q2 --year 2026
    python3 blog_ranking.py posts.csv --quarter Q2 --year 2026 --method perday
    python3 blog_ranking.py posts.csv --quarter Q2 --year 2026 --output q2_results.csv

Requires only the Python 3.8+ standard library.
"""

import argparse
import csv
import math
import sys
from datetime import date, datetime, timedelta

__version__ = "1.0.0"

DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y")
METHODS = ("sqrt", "perday", "raw")

# Accepted header names (case-insensitive) for each field.
COLUMN_ALIASES = {
    "title": ("title", "post", "blog", "blog title", "post title"),
    "author": ("author", "name", "writer", "owner"),
    "publish_date": ("publish_date", "published", "publish date", "date", "posted", "posted_on", "date posted"),
    "visitors": ("visitors", "unique visitors", "unique_visitors", "users", "views"),
    "url": ("url", "link"),
}


# --------------------------------------------------------------------------- #
# Window calculation
# --------------------------------------------------------------------------- #
def quarter_last_month(quarter):
    """Last calendar month of a quarter (Q1 -> 3, Q2 -> 6, ...)."""
    return quarter * 3


def eligibility_window(quarter, year, shift_days=15):
    """
    Return (start, end) of the publish-date window for a quarter.

    The window is shifted back by `shift_days`:
      start = day (shift_days + 1) of the last month of the previous quarter
      end   = day shift_days of the last month of this quarter
    With the default 15: Q2 2026 -> 2026-03-16 .. 2026-06-15.
    Every date belongs to exactly one quarter, with no gaps or overlaps.
    """
    if quarter not in (1, 2, 3, 4):
        raise ValueError("quarter must be 1-4")
    if not 1 <= shift_days <= 27:
        raise ValueError("shift_days must be between 1 and 27")

    end = date(year, quarter_last_month(quarter), shift_days)
    if quarter == 1:
        start = date(year - 1, 12, shift_days + 1)
    else:
        start = date(year, quarter_last_month(quarter - 1), shift_days + 1)
    return start, end


def default_snapshot(window_end, lag_days=30):
    """Visitors are read `lag_days` after the window closes (Q2 -> Jul 15)."""
    return window_end + timedelta(days=lag_days)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def days_live(publish_date, snapshot):
    """Days from publish to snapshot, counting both days."""
    return (snapshot - publish_date).days + 1


def score(visitors, days, method="sqrt"):
    """
    sqrt   : visitors / sqrt(days)   (recommended - balances launch spike vs. age)
    perday : visitors / days         (plain average per day - favours newer posts)
    raw    : visitors                (no adjustment - favours older posts)
    """
    if days <= 0:
        raise ValueError("days live must be positive")
    if method == "sqrt":
        return visitors / math.sqrt(days)
    if method == "perday":
        return visitors / days
    if method == "raw":
        return float(visitors)
    raise ValueError("unknown method: %s" % method)


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
def parse_date(text):
    text = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("unrecognised date '%s' (use YYYY-MM-DD)" % text)


def parse_int(text):
    cleaned = (text or "").strip().replace(",", "").replace("_", "")
    if cleaned == "":
        raise ValueError("visitors not filled in")
    value = int(float(cleaned))
    if value < 0:
        raise ValueError("visitors cannot be negative")
    return value


def map_columns(fieldnames):
    lookup = {name.strip().lower(): name for name in fieldnames if name}
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[field] = lookup[alias]
                break
    missing = [f for f in ("title", "author", "publish_date", "visitors") if f not in mapping]
    if missing:
        raise ValueError(
            "CSV is missing required column(s): %s. Found: %s"
            % (", ".join(missing), ", ".join(fieldnames))
        )
    return mapping


def load_posts(path):
    """Read posts from CSV. Returns (posts, errors)."""
    posts, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV file is empty")
        cols = map_columns(reader.fieldnames)
        for line_no, row in enumerate(reader, start=2):
            if not any((v or "").strip() for v in row.values()):
                continue  # blank line
            try:
                posts.append({
                    "title": row[cols["title"]].strip(),
                    "author": row[cols["author"]].strip(),
                    "publish_date": parse_date(row[cols["publish_date"]]),
                    "visitors": parse_int(row[cols["visitors"]]),
                    "url": row[cols["url"]].strip() if "url" in cols else "",
                })
            except (ValueError, KeyError) as exc:
                errors.append("line %d: %s" % (line_no, exc))
    return posts, errors


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def rank_posts(posts, window_start, window_end, snapshot, method="sqrt", min_visitors=0):
    """
    Returns (ranked, excluded).
    ranked   : eligible posts with days_live, score, percentage, rank
    excluded : posts left out, with a reason
    """
    eligible, excluded = [], []
    for post in posts:
        pub = post["publish_date"]
        if pub < window_start:
            reason = "published before window (earlier quarter)"
        elif pub > window_end:
            reason = "published after window (next quarter)"
        elif pub > snapshot:
            reason = "published after snapshot date"
        elif post["visitors"] < min_visitors:
            reason = "below minimum of %d visitors" % min_visitors
        else:
            reason = None
        if reason:
            excluded.append(dict(post, reason=reason))
            continue
        d = days_live(pub, snapshot)
        eligible.append(dict(post, days_live=d, score=score(post["visitors"], d, method)))

    total = sum(p["score"] for p in eligible)
    for p in eligible:
        p["percentage"] = (p["score"] / total * 100.0) if total > 0 else 0.0

    # Highest score first; tie-break on more visitors, then earlier publish date.
    eligible.sort(key=lambda p: (-p["score"], -p["visitors"], p["publish_date"]))

    # Competition ranking (1, 2, 2, 4): equal scores share a rank.
    previous, rank = None, 0
    for index, p in enumerate(eligible, start=1):
        key = round(p["score"], 6)
        if key != previous:
            rank, previous = index, key
        p["rank"] = rank
    return eligible, excluded


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _truncate(text, width):
    return text if len(text) <= width else text[: width - 1] + "…"


def print_table(ranked, top=None, out=sys.stdout):
    rows = ranked[:top] if top else ranked
    if not rows:
        out.write("No eligible posts.\n")
        return
    header = ("Rank", "Title", "Author", "Published", "Visitors", "Days", "Score", "Share %")
    body = [
        (
            str(p["rank"]),
            _truncate(p["title"], 40),
            _truncate(p["author"], 20),
            p["publish_date"].isoformat(),
            "{:,}".format(p["visitors"]),
            str(p["days_live"]),
            "%.1f" % p["score"],
            "%.1f" % p["percentage"],
        )
        for p in rows
    ]
    widths = [max(len(r[i]) for r in body + [header]) for i in range(len(header))]
    right = {0, 4, 5, 6, 7}

    def fmt(row):
        return "  ".join(
            cell.rjust(widths[i]) if i in right else cell.ljust(widths[i])
            for i, cell in enumerate(row)
        )

    out.write(fmt(header) + "\n")
    out.write("  ".join("-" * w for w in widths) + "\n")
    for row in body:
        out.write(fmt(row) + "\n")


def print_markdown(ranked, top=None, out=sys.stdout):
    rows = ranked[:top] if top else ranked
    out.write("| Rank | Title | Author | Published | Visitors | Days live | Score | Share % |\n")
    out.write("|---:|---|---|---|---:|---:|---:|---:|\n")
    for p in rows:
        title = p["title"].replace("|", "\\|")
        if p.get("url"):
            title = "[%s](%s)" % (title, p["url"])
        out.write("| %d | %s | %s | %s | %s | %d | %.1f | %.1f |\n" % (
            p["rank"], title, p["author"].replace("|", "\\|"), p["publish_date"].isoformat(),
            "{:,}".format(p["visitors"]), p["days_live"], p["score"], p["percentage"]))


def write_csv(ranked, path):
    fields = ["rank", "title", "author", "publish_date", "visitors", "days_live",
              "score", "percentage", "url"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in ranked:
            row = dict(p)
            row["publish_date"] = p["publish_date"].isoformat()
            row["score"] = "%.4f" % p["score"]
            row["percentage"] = "%.2f" % p["percentage"]
            writer.writerow(row)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_quarter(text):
    cleaned = text.strip().upper().lstrip("Q")
    if cleaned not in ("1", "2", "3", "4"):
        raise argparse.ArgumentTypeError("quarter must be Q1, Q2, Q3 or Q4")
    return int(cleaned)


def build_parser():
    p = argparse.ArgumentParser(
        prog="blog_ranking.py",
        description="Rank blog posts for a quarterly award, adjusting for how long each post has been live.",
        epilog="Example: python3 blog_ranking.py posts.csv --quarter Q2 --year 2026",
    )
    p.add_argument("csv", help="input CSV with columns: title, author, publish_date, visitors [, url]")
    p.add_argument("-q", "--quarter", type=parse_quarter, help="quarter to rank: Q1-Q4")
    p.add_argument("-y", "--year", type=int, help="year of the quarter (e.g. 2026)")
    p.add_argument("--shift-days", type=int, default=15,
                   help="how far the publish window is shifted back from the calendar quarter (default 15)")
    p.add_argument("--lag-days", type=int, default=30,
                   help="days after the window closes to read visitor counts (default 30)")
    p.add_argument("--window-start", type=parse_date, help="override: first eligible publish date (YYYY-MM-DD)")
    p.add_argument("--window-end", type=parse_date, help="override: last eligible publish date (YYYY-MM-DD)")
    p.add_argument("--snapshot", type=parse_date, help="override: date visitor counts were taken (YYYY-MM-DD)")
    p.add_argument("-m", "--method", choices=METHODS, default="sqrt",
                   help="scoring: sqrt (default, recommended), perday, raw")
    p.add_argument("--min-visitors", type=int, default=0, help="posts below this are not ranked (default 0)")
    p.add_argument("--top", type=int, help="show only the top N posts")
    p.add_argument("-f", "--format", choices=("table", "markdown"), default="table", help="screen output format")
    p.add_argument("-o", "--output", help="also write full results to this CSV file")
    p.add_argument("--show-excluded", action="store_true", help="list posts that were left out and why")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return p


def resolve_dates(args, parser):
    if args.window_start and args.window_end:
        start, end = args.window_start, args.window_end
    elif args.quarter and args.year:
        start, end = eligibility_window(args.quarter, args.year, args.shift_days)
        start = args.window_start or start
        end = args.window_end or end
    else:
        parser.error("give --quarter and --year, or both --window-start and --window-end")
    if start > end:
        parser.error("window start (%s) is after window end (%s)" % (start, end))
    snapshot = args.snapshot or default_snapshot(end, args.lag_days)
    if snapshot < end:
        parser.error("snapshot (%s) must be on or after window end (%s)" % (snapshot, end))
    return start, end, snapshot


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    start, end, snapshot = resolve_dates(args, parser)

    try:
        posts, errors = load_posts(args.csv)
    except (OSError, ValueError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2
    for err in errors:
        sys.stderr.write("warning: skipped %s\n" % err)

    ranked, excluded = rank_posts(posts, start, end, snapshot, args.method, args.min_visitors)

    label = "Q%d %d" % (args.quarter, args.year) if args.quarter and args.year else "Custom window"
    print("%s | publish window %s .. %s | visitors as of %s | method: %s"
          % (label, start, end, snapshot, args.method))
    print("Eligible posts: %d   Excluded: %d\n" % (len(ranked), len(excluded)))

    if args.format == "markdown":
        print_markdown(ranked, args.top)
    else:
        print_table(ranked, args.top)

    if ranked:
        winners = [p for p in ranked if p["rank"] == 1]
        names = ", ".join('"%s" by %s' % (w["title"], w["author"]) for w in winners)
        print("\nWinner%s: %s (%.1f%%)" % ("s (tie)" if len(winners) > 1 else "", names, winners[0]["percentage"]))

    if args.show_excluded and excluded:
        print("\nExcluded:")
        for p in sorted(excluded, key=lambda x: x["publish_date"]):
            print("  - %s | %s | %s | %s" % (p["publish_date"], p["title"], p["author"], p["reason"]))

    if args.output:
        write_csv(ranked, args.output)
        print("\nResults written to %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
