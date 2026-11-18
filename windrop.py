"""windrop_v1: which horses' WIN price will keep shortening until the close, and where it will close.

Inputs available at the point (t5, t3 or t2): the WIN board, the Quinella board and, after t5, the WIN t5 board.
Per horse, z-scored inside the race:
  fav      ln of the WIN-implied probability (1/odds normalised)      shorter prices keep shortening more
  winmom   % WIN shortening t5 -> point (not used at t5)               momentum
  lead     Quinella support / WIN-implied probability - 1              Quinella is keener on the horse than WIN is
Quinella support of a horse = sum of 1/(odds-1) over its combinations / (2 x sum over all combinations).
score = linear combination (coefficients below); predicted ln-shortening = c0 + c1 x score, so
predicted close = win odds now x exp(-(c0 + c1 x score)).

Coefficients were fitted on 16 races (Sha Tin 2026-11-14 R4,5,7-11; Happy Valley 2026-11-18 R1-9, 204 runners).
They are exploratory: two meetings, in-sample fit, to be refitted when more race days are recorded.
"""
import math

MODEL = "windrop_v1"
TOP = 3
MIN_HORSES = 6
POINTS = ("t5", "t3", "t2")

COEFS = {
    "t5": {"fav": 0.39634719, "lead": 0.46150613, "c0": -0.18838143, "c1": 0.39392643},
    "t3": {"fav": 0.43630692, "winmom": 0.11864413, "lead": 0.41896430, "c0": -0.18906973, "c1": 0.36670330},
    "t2": {"fav": 0.44003575, "winmom": 0.16874870, "lead": 0.37861915, "c0": -0.18339110, "c1": 0.35486005},
}

# Leave-one-race-out results of the fit above (16 races). Fair baselines for the close-odds error:
# average drift only / favourite-ness only. Out-of-sample means each race was predicted from the other 15.
VALIDATION = {
    "t5": {"rank_corr": 0.62, "top3_shortened_10pct": 0.56, "close_log_mae": 0.252,
           "baseline_mean_drift_mae": 0.318, "baseline_favourite_only_mae": 0.286},
    "t3": {"rank_corr": 0.65, "top3_shortened_10pct": 0.54, "close_log_mae": 0.236,
           "baseline_mean_drift_mae": 0.309, "baseline_favourite_only_mae": 0.273},
    "t2": {"rank_corr": 0.65, "top3_shortened_10pct": 0.54, "close_log_mae": 0.225,
           "baseline_mean_drift_mae": 0.301, "baseline_favourite_only_mae": 0.264},
}
NOTE = ("Exploratory: fitted on 2 race days (16 races). Out-of-sample about 54% of the top 3 shortened by 10% or more "
        "(about 21% of all runners do). Typical error of the predicted close price is about 20-25%. "
        "A ranking signal, not a betting recommendation.")


def qin_shares(odds):
    """{horse: share of the Quinella pool} using weights 1/(odds-1); odds <= 1 and missing prices are ignored."""
    weights = {pair: 1 / (o - 1) for pair, o in (odds or {}).items() if o and o > 1}
    total = sum(weights.values())
    if not total:
        return {}
    shares = {}
    for pair, w in weights.items():
        for horse in pair.split("-"):
            shares[horse] = shares.get(horse, 0.0) + w / (2 * total)
    return shares


def zscores(values):
    xs = list(values.values())
    mean = sum(xs) / len(xs)
    sd = (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5
    return {k: ((v - mean) / sd if sd > 1e-12 else 0.0) for k, v in values.items()}


def predict_windrop(s, point):
    """Prediction for one race state `s` at `point`; errors are labelled, never guessed."""
    pts, wpts = s.get("points") or {}, s.get("win_points") or {}
    need_t5 = point != "t5"
    w_now = ((wpts.get(point) or {}).get("odds")) or {}
    w_t5 = ((wpts.get("t5") or {}).get("odds")) or {}
    qin_now = ((pts.get(point) or {}).get("odds")) or {}
    if not qin_now:
        return {"model": MODEL, "at_point": point, "error": f"need_{point}_quinella_board"}
    if not w_now or (need_t5 and not w_t5):
        return {"model": MODEL, "at_point": point, "error": f"need_win_{point}" + ("_and_t5" if need_t5 else "") + "_board"}
    shares = qin_shares(qin_now)
    horses = sorted((h for h, o in w_now.items() if o and o > 0 and h in shares and (not need_t5 or w_t5.get(h))), key=int)
    if len(horses) < MIN_HORSES:
        return {"model": MODEL, "at_point": point, "error": "too_few_comparable_horses"}
    total = sum(1 / w_now[h] for h in horses)
    prob = {h: (1 / w_now[h]) / total for h in horses}
    feats = {"fav": zscores({h: math.log(prob[h]) for h in horses}),
             "lead": zscores({h: shares[h] / prob[h] - 1 for h in horses})}
    if need_t5:
        feats["winmom"] = zscores({h: 100 * (w_t5[h] - w_now[h]) / w_t5[h] for h in horses})
    c = COEFS[point]
    rows = []
    for h in horses:
        score = sum(c[name] * feats[name][h] for name in feats)
        log_drop = c["c0"] + c["c1"] * score
        rows.append({"horse": h, "score": round(score, 3), "win_odds": w_now[h],
                     "win_implied_pct": round(100 * prob[h], 2), "qin_support_pct": round(100 * shares[h], 2),
                     "lead_pct": round(100 * (shares[h] / prob[h] - 1), 1),
                     "win_move_pct_t5_to_now": round(100 * (w_t5[h] - w_now[h]) / w_t5[h], 1) if need_t5 else None,
                     "predicted_drop_pct": round(100 * (1 - math.exp(-log_drop)), 1),
                     "predicted_close_odds": round(w_now[h] * math.exp(-log_drop), 1)})
    rows.sort(key=lambda r: -r["score"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return {"model": MODEL, "at_point": point, "made_at": (pts.get(point) or {}).get("observed_at"),
            "target_at": (pts.get(point) or {}).get("target_at"),
            "inputs": ["WIN", "QIN"], "top": [r["horse"] for r in rows[:TOP]], "horses": rows,
            "validation": VALIDATION[point], "note": NOTE,
            "meaning": "predicted_drop_pct > 0 = WIN price expected to shorten until the close; "
                       "predicted_close_odds = win odds now x exp(-(c0 + c1 x score))"}


def windrop_outcome(pred, wpts):
    """Compare a stored prediction with the WIN board after the start (after_start)."""
    if not pred or not pred.get("horses"):
        return None
    final = ((wpts or {}).get("after_start") or {}).get("odds")
    if not final:
        return {"missing": "no_after_start"}
    rows = []
    for h in pred["horses"]:
        close = final.get(h["horse"])
        if close and h["win_odds"]:
            rows.append({"horse": h["horse"], "predicted_close": h["predicted_close_odds"], "actual_close": close,
                         "actual_drop_pct": round(100 * (h["win_odds"] - close) / h["win_odds"], 1),
                         "abs_log_error": round(abs(math.log(h["predicted_close_odds"] / close)), 3)})
    if len(rows) < MIN_HORSES:
        return {"missing": "too_few_after_start_prices"}
    actual_top = [r["horse"] for r in sorted(rows, key=lambda r: -r["actual_drop_pct"])[:TOP]]
    picked = [r for r in rows if r["horse"] in pred["top"]]
    return {"horses": rows, "actual_top": actual_top,
            "top_hits": len(set(pred["top"]) & set(actual_top)), "chance_hits": round(TOP * TOP / len(rows), 2),
            "top_shortened_10pct": sum(1 for r in picked if r["actual_drop_pct"] >= 10), "top_n": len(picked),
            "close_log_mae": round(sum(r["abs_log_error"] for r in rows) / len(rows), 3)}
