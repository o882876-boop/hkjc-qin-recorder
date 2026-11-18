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


# ---------------------------------------------------------------------------------------------------------------
# windrop_dbl_v1: Double (孖寶) edge, races 2+.
# The Double of legs (N-1, N) is frozen when race N-1 stops selling. Its price for (a, b) should be about
# W1(a) x W2(b) (same take-out); dividing by the leg-1 win price after the close gives the leg-2 price the Double
# bettors had in mind: implied2(b) = mean over leg-1 horses a at 10x or less of DBL(a,b) / W1(a), weighted 1/W1(a).
# edge(b) = ln(W2(b) / implied2(b)): high = the WIN price is longer than the Double implies -> expected to shorten.
#   first  race N's first WIN board after race N-1 stopped selling (before_rollover): score = z(edge)
#   t5, t2 score = z(edge, W2 taken at `first`) + z(Quinella lead at that point)
# Fitted on 12 races (Sha Tin 2026-11-14 R5,8,9,10; Happy Valley 2026-11-18 R2-9), exploratory.
# ---------------------------------------------------------------------------------------------------------------
DBL_MODEL = "windrop_dbl_v1"
DBL_POINTS = ("first", "t5", "t2")
DBL_BOARD = {"first": "before_rollover", "t5": "t5", "t2": "t2"}      # race N board each point reads
LEG1_CAP = 10.0
DBL_COEFS = {"first": {"c0": -0.1817, "c1": 0.2952},
             "t5": {"c0": -0.1759, "c1": 0.1647},
             "t2": {"c0": -0.1765, "c1": 0.1521}}
DBL_VALIDATION = {
    "first": {"rank_corr": 0.73, "top3_shortened_10pct": 0.61, "all_runners_shortened_10pct": 0.26,
              "close_log_mae": 0.238, "baseline_mean_drift_mae": 0.344, "baseline_close_equals_now_mae": 0.387},
    "t5": {"rank_corr": 0.73, "top3_shortened_10pct": 0.64, "all_runners_shortened_10pct": 0.24,
           "close_log_mae": 0.227, "baseline_mean_drift_mae": 0.325, "baseline_close_equals_now_mae": 0.375},
    "t2": {"rank_corr": 0.71, "top3_shortened_10pct": 0.61, "all_runners_shortened_10pct": 0.22,
           "close_log_mae": 0.219, "baseline_mean_drift_mae": 0.308, "baseline_close_equals_now_mae": 0.356},
}
DBL_NOTE = ("Exploratory: 12 races (2 meetings), races 2+ only. Rank correlation, top-3 hit rate and price error are "
            "leave-one-race-out; the score-to-price mapping is fitted on all 12. About 6 in 10 of the top 3 shortened by "
            "10% or more (about 1 in 4 of all runners do). A ranking signal, not a betting recommendation.")


def dbl_frozen(prev):
    """Odds of the Double (N-1, N) as frozen when race N-1 stopped selling: last open board, else its t2 board."""
    d = (prev or {}).get("dbl") or {}
    board = d.get("last_open") or (d.get("points") or {}).get("t2") or d.get("closed_board")
    return (board or {}).get("odds") or {}


def dbl_edges(w2, w1, frozen, horses):
    """{horse b: (edge, implied leg-2 price)}; horses without a usable leg-1 partner at 10x or less are left out."""
    out = {}
    for b in horses:
        num = den = 0.0
        for a, p1 in w1.items():
            if not p1 or p1 > LEG1_CAP:
                continue
            price = frozen.get(f"{a}-{b}")
            if price and price > 1:
                num += (1 / p1) * (price / p1)
                den += 1 / p1
        if den:
            implied = num / den
            out[b] = (math.log(w2[b] / implied), implied)
    return out


def predict_dbl(s, prev, point):
    """windrop_dbl_v1 for race state `s` (race N) with `prev` the state of race N-1; errors are labelled."""
    key = DBL_BOARD[point]
    wpts, pts = s.get("win_points") or {}, s.get("points") or {}
    w_first = ((wpts.get("before_rollover") or {}).get("odds")) or {}
    w_now = ((wpts.get(key) or {}).get("odds")) or {}
    w1 = (((prev or {}).get("win_points") or {}).get("after_start") or {}).get("odds") or {}
    frozen = dbl_frozen(prev)
    base = {"model": DBL_MODEL, "at_point": point}
    if not w1:
        return {**base, "error": "need_leg1_win_after_start_board"}
    if not frozen:
        return {**base, "error": "need_frozen_double_board"}
    if not w_first or not w_now:
        return {**base, "error": "need_win_first_board" if not w_first else f"need_win_{key}_board"}
    use_qin = point != "first"
    qin_now = (((pts.get(key) or {}).get("odds")) or {}) if use_qin else {}
    if use_qin and not qin_now:
        return {**base, "error": f"need_{key}_quinella_board"}
    shares = qin_shares(qin_now) if use_qin else {}
    horses = sorted((h for h, o in w_now.items() if o and o > 0 and w_first.get(h) and (not use_qin or h in shares)), key=int)
    edges = dbl_edges(w_first, w1, frozen, horses)
    horses = [h for h in horses if h in edges]
    if len(horses) < MIN_HORSES:
        return {**base, "error": "too_few_comparable_horses"}
    z_edge = zscores({h: edges[h][0] for h in horses})
    lead = z_lead = None
    if use_qin:
        total = sum(1 / w_now[h] for h in horses)
        prob = {h: (1 / w_now[h]) / total for h in horses}
        lead = {h: shares[h] / prob[h] - 1 for h in horses}
        z_lead = zscores(lead)
    c = DBL_COEFS[point]
    rows = []
    for h in horses:
        score = z_edge[h] + (z_lead[h] if z_lead else 0.0)
        log_drop = c["c0"] + c["c1"] * score
        rows.append({"horse": h, "score": round(score, 3), "win_odds": w_now[h],
                     "dbl_implied_win_odds": round(edges[h][1], 1),
                     "edge_pct": round(100 * (w_first[h] / edges[h][1] - 1), 1),
                     "lead_pct": round(100 * lead[h], 1) if lead else None,
                     "predicted_drop_pct": round(100 * (1 - math.exp(-log_drop)), 1),
                     "predicted_close_odds": round(w_now[h] * math.exp(-log_drop), 1)})
    top_edge = set(sorted(horses, key=lambda h: -z_edge[h])[:TOP])
    top_lead = set(sorted(horses, key=lambda h: -z_lead[h])[:TOP]) if z_lead else set()
    rows.sort(key=lambda r: -r["score"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["signals"] = {"edge_top3": row["horse"] in top_edge, **({"lead_top3": row["horse"] in top_lead} if z_lead else {})}
        row["signals_fired"] = sum(row["signals"].values())
    return {**base, "made_at": (pts.get(key) or {}).get("observed_at"), "target_at": (pts.get(key) or {}).get("target_at"),
            "inputs": ["WIN", "DBL"] + (["QIN"] if z_lead else []), "leg1_cap_odds": LEG1_CAP,
            "top": [r["horse"] for r in rows[:TOP]],
            "both_signals": [r["horse"] for r in rows if use_qin and r["signals_fired"] == 2],
            "horses": rows, "validation": DBL_VALIDATION[point], "note": DBL_NOTE,
            "meaning": "edge_pct = WIN price at `first` vs the price the frozen Double implies (+ = WIN longer, expected to shorten); "
                       "predicted_drop_pct > 0 = WIN expected to shorten until the close"}
