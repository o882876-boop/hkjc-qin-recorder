"""Live scorecard of the windrop predictions, from the race records the recorder writes to `odds-data`.

    python3 research/windrop/report.py --data odds-data [--days 2026-11-22_ST,...]

Every race record (`qin-history/<date>_<venue>/race-NN-*.json`) carries the predictions made before the race (`windrop`,
`windrop_dbl`, `windrop_combined`, `windrop_longshot`) and, once the close is known, what happened (`*_outcome`). This adds them up
per prediction and time point and sets them next to the leave-one-race-out numbers the predictions were validated with, so a
drift is visible after a few race days. Read the tables with the sample size in mind: one race day is about 9 races.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

FAMILIES = (("windrop", "windrop_outcome", "Quinella (windrop_v1)", ("t5", "t3", "t2")),
            ("windrop_dbl", "windrop_dbl_outcome", "Double (windrop_dbl_v1)", ("first", "t5", "t2")),
            ("windrop_combined", "windrop_combined_outcome", "Combined (Double + Quinella)", ("t5", "t2")))


def aggregate(records):
    """{(family, point): totals} from race records (dicts)."""
    totals = defaultdict(lambda: defaultdict(float))
    expected = {}
    for rec in records:
        for key, outcome_key, _, points in FAMILIES:
            for point in points:
                pred = (rec.get(key) or {}).get(point)
                out = (rec.get(outcome_key) or {}).get(point)
                if not pred or "error" in pred or not out or "flagged_n" not in out:
                    continue
                t = totals[(key, point)]
                horses = len(out.get("horses") or [])
                t["races"] += 1
                t["horses"] += horses
                for k in ("flagged_n", "flagged_fell_any", "flagged_fell_10pct", "missed_fell_10pct"):
                    t[k] += out.get(k, 0)
                t["brier_sum"] += out.get("brier_10pct", 0.0) * horses
                t["band"] += out.get("in_50pct_band", 0)
                t["mae_sum"] += out.get("close_log_mae", 0.0) * horses
                expected[(key, point)] = pred.get("flag_validation") or {}
    longshot = defaultdict(float)
    for rec in records:
        out = rec.get("windrop_longshot_outcome")
        if out and "flagged_n" in out:
            longshot["races"] += 1
            longshot["longshots"] += out["longshots"]
            longshot["flagged"] += out["flagged_n"]
            longshot["flagged_fell"] += out["flagged_fell_10pct"]
            longshot["other"] += out["longshots"] - out["flagged_n"]
            longshot["other_fell"] += out["unflagged_fell_10pct"]
    return totals, expected, longshot


def render(records):
    totals, expected, ls = aggregate(records)
    lines = [f"# windrop live scorecard ({len(records)} race records)", "",
             "Flag rule: predicted close <= price now x 0.95. `fell 10%+` = the WIN price ended 10% or more shorter than at the point.", "",
             "| prediction | point | races | flagged / race | fell at all | fell 10%+ | caught of all 10%+ fallers | Brier 10% | in 50% band | validated (fell 10%+ / caught) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for key, _, title, points in FAMILIES:
        for point in points:
            t = totals.get((key, point))
            if not t:
                continue
            fl, f10 = t["flagged_n"], t["flagged_fell_10pct"]
            fell10_total = f10 + t["missed_fell_10pct"]
            pct = lambda a, b: f"{100 * a / b:.0f}% ({int(a)}/{int(b)})" if b else "-"
            v = expected.get((key, point)) or {}
            lines.append(f"| {title} | {point} | {int(t['races'])} | {fl / t['races']:.1f} | {pct(t['flagged_fell_any'], fl)} | {pct(f10, fl)} | "
                         f"{pct(f10, fell10_total)} | {t['brier_sum'] / t['horses']:.3f} | {pct(t['band'], t['horses'])} | "
                         f"{100 * v.get('flagged_fell_10pct', 0):.0f}% / {100 * v.get('caught_of_fell_10pct', 0):.0f}% |")
    if ls:
        lines += ["", f"Longshots (>= 20x at t2), {int(ls['races'])} races: flagged {int(ls['flagged'])} -> {int(ls['flagged_fell'])} shortened 10%+; "
                      f"not flagged {int(ls['other'])} -> {int(ls['other_fell'])} (validated: 13 -> 4, 61 -> 0)."]
    return "\n".join(lines)


def load(data, days=None):
    records = []
    for day_dir in sorted((Path(data) / "qin-history").glob("*")):
        if days and day_dir.name not in days:
            continue
        for f in sorted(day_dir.glob("race-*.json")):
            records.append(json.loads(f.read_text(encoding="utf-8")))
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="local checkout of the odds-data branch")
    ap.add_argument("--days", help="comma separated folder names (default: all)")
    args = ap.parse_args()
    print(render(load(args.data, set(args.days.split(",")) if args.days else None)))


if __name__ == "__main__":
    main()
