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
POINTS = ("t5", "t3", "t2", "t1", "t10")   # t10 last: every earlier point keeps its own prefix of this tuple

COEFS = {
    "t5": {"fav": 0.39634719, "lead": 0.46150613, "c0": -0.18838143, "c1": 0.39392643},
    "t3": {"fav": 0.43630692, "winmom": 0.11864413, "lead": 0.41896430, "c0": -0.18906973, "c1": 0.36670330},
    "t2": {"fav": 0.44003575, "winmom": 0.16874870, "lead": 0.37861915, "c0": -0.18339110, "c1": 0.35486005},
}

# Leave-one-race-out results of the fit above (16 races). Fair baselines for the close-odds error:
# average drift only / favourite-ness only. Out-of-sample means each race was predicted from the other 15.
VALIDATION = {
    "t5": {"rank_corr": 0.62, "top3_shortened_10pct": 0.56, "close_log_mae": 0.252,
           "baseline_mean_drift_mae": 0.318, "baseline_favourite_only_mae": 0.286,
           "brier_10pct": 0.131, "brier_base_rate_only": 0.175, "top3_mean_predicted_prob": 0.55, "interval50_coverage": 0.50},
    "t3": {"rank_corr": 0.65, "top3_shortened_10pct": 0.54, "close_log_mae": 0.236,
           "baseline_mean_drift_mae": 0.309, "baseline_favourite_only_mae": 0.273,
           "brier_10pct": 0.120, "brier_base_rate_only": 0.163, "top3_mean_predicted_prob": 0.54, "interval50_coverage": 0.50},
    "t2": {"rank_corr": 0.65, "top3_shortened_10pct": 0.54, "close_log_mae": 0.225,
           "baseline_mean_drift_mae": 0.301, "baseline_favourite_only_mae": 0.264,
           "brier_10pct": 0.112, "brier_base_rate_only": 0.163, "top3_mean_predicted_prob": 0.56, "interval50_coverage": 0.49},
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


# Score -> chance and price. P(WIN shortens by 10% or more) and P(shortens at all) are logistic in the score; the price is
# now x exp(-(c0 + c1 x score)) with the 25%-75% band of the fit residuals around it. Fitted in-sample on the same races
# as the scores (QIN 16 races, DBL and combined 12); a..b = chance, c = price, r25/r75 = ln residual quartiles.
PROB = {
 "qin": {
  "t5": {
   "c0": -0.18838143,
   "c1": 0.39392643,
   "a10": -1.781,
   "b10": 2.516,
   "a0": -1.651,
   "b0": 2.788,
   "r25": -0.234,
   "r75": 0.181
  },
  "t3": {
   "c0": -0.18906973,
   "c1": 0.3667033,
   "a10": -2.068,
   "b10": 2.699,
   "a0": -1.427,
   "b0": 2.515,
   "r25": -0.192,
   "r75": 0.173
  },
  "t2": {
   "c0": -0.1833911,
   "c1": 0.35486005,
   "a10": -2.193,
   "b10": 2.931,
   "a0": -1.416,
   "b0": 2.548,
   "r25": -0.181,
   "r75": 0.165
  }
 },
 "dbl": {
  "first": {
   "c0": -0.1817,
   "c1": 0.2952,
   "a10": -1.74,
   "b10": 1.944,
   "a0": -1.523,
   "b0": 2.231,
   "r25": -0.22,
   "r75": 0.176
  },
  "t5": {
   "c0": -0.1759,
   "c1": 0.2814,
   "a10": -2.075,
   "b10": 2.235,
   "a0": -1.896,
   "b0": 2.534,
   "r25": -0.186,
   "r75": 0.166
  },
  "t2": {
   "c0": -0.1765,
   "c1": 0.2622,
   "a10": -2.335,
   "b10": 2.356,
   "a0": -1.388,
   "b0": 1.835,
   "r25": -0.184,
   "r75": 0.173
  }
 },
 "combined": {
  "t5": {
   "c0": -0.1759,
   "c1": 0.1647,
   "a10": -2.104,
   "b10": 1.377,
   "a0": -1.847,
   "b0": 1.516,
   "r25": -0.17,
   "r75": 0.181
  },
  "t2": {
   "c0": -0.1765,
   "c1": 0.1521,
   "a10": -2.384,
   "b10": 1.441,
   "a0": -1.342,
   "b0": 1.057,
   "r25": -0.175,
   "r75": 0.18
  }
 }
}


def _sigmoid(x):
    return 1 / (1 + math.exp(-x))


def price_block(w_now, score, params):
    """Chances of shortening and the predicted close price with a 50% band, for one horse."""
    log_drop = params["c0"] + params["c1"] * score
    return {"shorten_prob_10pct": round(_sigmoid(params["a10"] + params["b10"] * score), 3),
            "shorten_prob_any": round(_sigmoid(params["a0"] + params["b0"] * score), 3),
            "predicted_drop_pct": round(100 * (1 - math.exp(-log_drop)), 1),
            "predicted_close_odds": round(w_now * math.exp(-log_drop), 1),
            "predicted_close_low": round(w_now * math.exp(-(log_drop + params["r75"])), 1),
            "predicted_close_high": round(w_now * math.exp(-(log_drop + params["r25"])), 1)}



# Quinella 飛 (the user's rule): at a given moment a horse's share of the Quinella pool is above its WIN-implied share.
#   fly    qin_pct > win_pct
#   tie    win_pct - 1 percentage point <= qin_pct <= win_pct  (打和: nearly equal, never excluded)
#   no_fly qin_pct < win_pct - 1 percentage point             (the exclusion list `qin_no_fly`)
# `qin_fly_points` gives the state at t5, t3, t2 so far. 16 races (204 runners, 46 / 42 / 42 shortened 10%+ at t5 / t3 / t2): the 32-40 no-fly
# horses shortened 10%+ only 9-10% of the time (all runners 21%) and held 3-4 of the fallers; the tie horses shortened 5-7% of the time
# (so tie is "not no-fly", not "fly"); fly horses about 1 in 3. A filter, not a pick: combine it with the scores above.
QIN_TIE_PP = 1.0
QIN_FLY_VALIDATION = {"t5": {"all": {"n": 204, "fallers": 46, "fly": {"n": 106, "fell_10pct": 0.36, "fallers": 38}, "tie": {"n": 58, "fell_10pct": 0.07, "fallers": 4}, "nofly": {"n": 40, "fell_10pct": 0.1, "fallers": 4}}, "le10": {"n": 68, "fallers": 26, "fly": {"n": 36, "fell_10pct": 0.56, "fallers": 20}, "tie": {"n": 6, "fell_10pct": 0.33, "fallers": 2}, "nofly": {"n": 26, "fell_10pct": 0.15, "fallers": 4}}}, "t3": {"all": {"n": 204, "fallers": 42, "fly": {"n": 103, "fell_10pct": 0.33, "fallers": 34}, "tie": {"n": 68, "fell_10pct": 0.07, "fallers": 5}, "nofly": {"n": 33, "fell_10pct": 0.09, "fallers": 3}}, "le10": {"n": 67, "fallers": 23, "fly": {"n": 35, "fell_10pct": 0.51, "fallers": 18}, "tie": {"n": 10, "fell_10pct": 0.2, "fallers": 2}, "nofly": {"n": 22, "fell_10pct": 0.14, "fallers": 3}}}, "t2": {"all": {"n": 204, "fallers": 42, "fly": {"n": 108, "fell_10pct": 0.33, "fallers": 36}, "tie": {"n": 64, "fell_10pct": 0.05, "fallers": 3}, "nofly": {"n": 32, "fell_10pct": 0.09, "fallers": 3}}, "le10": {"n": 67, "fallers": 23, "fly": {"n": 36, "fell_10pct": 0.5, "fallers": 18}, "tie": {"n": 9, "fell_10pct": 0.22, "fallers": 2}, "nofly": {"n": 22, "fell_10pct": 0.14, "fallers": 3}}}}
QIN_FLY_RULE = ("qin_fly_state: fly = qin_pct > win_pct; tie = within 1 percentage point below (打和, not excluded); "
                "no_fly = more than 1 percentage point below; qin_no_fly is the exclusion list")


def qin_fly_state(gap):
    return "fly" if gap > 0 else ("tie" if gap >= -QIN_TIE_PP else "no_fly")


def qin_fly_table(s, upto):
    """{point: {horse: (qin_pct, win_pct)}} at t5, t3, t2 up to `upto`, from the stored boards (WIN normalised over the same horses)."""
    out = {}
    for point in (("t10",) if upto == "t10" else POINTS[:POINTS.index(upto) + 1]):
        qin = (((s.get("points") or {}).get(point) or {}).get("odds")) or {}
        win = (((s.get("win_points") or {}).get(point) or {}).get("odds")) or {}
        shares = qin_shares(qin)
        horses = [h for h, o in win.items() if o and o > 0 and h in shares]
        if len(horses) < MIN_HORSES:
            continue
        total = sum(1 / win[h] for h in horses)
        out[point] = {h: (100 * shares[h], 100 * (1 / win[h]) / total) for h in horses}
    return out


def add_qin_fly(s, point, rows):
    """Add the Quinella-飛 fields to prediction rows; returns {"fly": [...], "tie": [...], "no_fly": [...]} (horses)."""
    table = qin_fly_table(s, point)
    now = table.get(point)
    groups = {"fly": [], "tie": [], "no_fly": []}
    if not now:
        return groups
    for row in rows:
        h = row["horse"]
        if h not in now:
            continue
        gap = now[h][0] - now[h][1]
        state = qin_fly_state(gap)
        row["qin_gap_pp"] = round(gap, 2)
        row["qin_fly_state"] = state
        row["qin_fly_points"] = {pt: qin_fly_state(tbl[h][0] - tbl[h][1]) for pt, tbl in table.items() if h in tbl}
        row["qin_fly_all_points"] = all(v == "fly" for v in row["qin_fly_points"].values())
        groups[state].append(h)
    return groups


def qin_fly_fields(groups, point):
    return {"qin_fly": groups["fly"], "qin_tie": groups["tie"], "qin_no_fly": groups["no_fly"], "qin_fly_rule": QIN_FLY_RULE,
            "qin_fly_validation": QIN_FLY_VALIDATION[point]}


# Quinella share path from the previous race's payout (the user's request: start at 過關後, not t5): the horse's share of the Quinella
# pool at after_rollover, t5, t3, t2 (races 2+; race 1 has no after_rollover board) and how often it went up step by step.
#   qin_rise_from_rollover_pct  share at this point / share at after_rollover - 1
#   qin_rise_steps / _possible  steps up out of after_rollover->t5->t3->t2 so far;  qin_rise_all_steps = every step up
#   qin_rise_from_t5_pct        share now / share at t5 - 1 (less noisy: the after_rollover board is thin)
# 16 races, races 2+ (192 runners, 20% shortened 10%+): going up at every step is only a weak helper (23% of 53; with qin fly 35% of 31 against
# 33% of all fly horses; without fly 5%). Rise from rollover with fly: 5-10% -> 43%, 10%+ -> 40%, falling -> 22%. From t5 the signal is a bit clearer
# (fly horses up 6%+ at t2: 50% of 14) and its mirror is the only usable exclusion: a share down 5%+ from t5 to t2 shortened 10%+ in 0 of 17 horses.
RISE_POINTS = ("after_rollover", "t5", "t3", "t2", "t1")
FALL_EXCLUDE_PCT = -5.0
QIN_RISE_VALIDATION = {"races": 16, "runners_with_rollover": 192, "fallers_base": 0.20,
                       "all_steps_up": {"n": 53, "fell_10pct": 0.23}, "fly_and_all_steps_up": {"n": 31, "fell_10pct": 0.35},
                       "fly_all": {"n": 103, "fell_10pct": 0.33}, "no_fly_and_all_steps_up": {"n": 22, "fell_10pct": 0.05},
                       "fly_rise_from_rollover": {"down": [36, 0.22], "0-5%": [18, 0.33], "5-10%": [14, 0.43], "10%+": [35, 0.40]},
                       "t5_to_t2": {"down_5pct_or_more": {"n": 17, "fell_10pct": 0.0}, "fly_up_6pct_or_more": {"n": 14, "fell_10pct": 0.50}}}


def qin_share_path(s, upto):
    """{point: {horse: share %}} of the Quinella pool at after_rollover, t5, t3, t2 up to `upto` (only boards that exist)."""
    out = {}
    for point in RISE_POINTS[:RISE_POINTS.index(upto) + 1]:
        shares = qin_shares((((s.get("points") or {}).get(point) or {}).get("odds")) or {})
        if len(shares) >= MIN_HORSES:
            out[point] = {h: 100 * v for h, v in shares.items()}
    return out


def add_fly_and_rising(rows):
    """Mark rows that are qin fly now AND whose share went up at every step from the previous payout; returns those horses."""
    out = []
    for row in rows:
        row["qin_fly_and_rising"] = row.get("qin_fly_state") == "fly" and bool(row.get("qin_rise_all_steps"))
        if row["qin_fly_and_rising"]:
            out.append(row["horse"])
    return out


def add_qin_rise(s, point, rows):
    """Add the Quinella share path fields to prediction rows; returns the prediction-level lists."""
    path = qin_share_path(s, point)
    if point not in path:
        return {}
    all_up, fall5 = [], []
    for row in rows:
        h = row["horse"]
        seq = [(pt, path[pt][h]) for pt in RISE_POINTS if pt in path and h in path[pt]]
        if len(seq) < 2 or seq[-1][0] != point:
            continue
        ups = [b > a for (_, a), (_, b) in zip(seq, seq[1:])]
        values = dict(seq)
        row["qin_pct_path"] = {pt: round(v, 2) for pt, v in seq}
        row["qin_rise_steps"], row["qin_rise_steps_possible"] = sum(ups), len(ups)
        row["qin_rise_all_steps"] = all(ups) and seq[0][0] == "after_rollover"
        if "after_rollover" in values and point != "after_rollover":
            row["qin_rise_from_rollover_pct"] = round(100 * (values[point] / values["after_rollover"] - 1), 1)
        if "t5" in values and point != "t5":
            row["qin_rise_from_t5_pct"] = round(100 * (values[point] / values["t5"] - 1), 1)
            if point in ("t2", "t1") and row["qin_rise_from_t5_pct"] <= FALL_EXCLUDE_PCT:
                fall5.append(h)
        if row["qin_rise_all_steps"]:
            all_up.append(h)
    return {"qin_rise_all_steps": all_up, "qin_fall5_from_t5": fall5, "qin_rise_validation": QIN_RISE_VALIDATION}


def add_t10_move(s, rows):
    """t10 -> now: change of each horse's Quinella share and WIN price since ten minutes before the off (information only, never scored)."""
    pts, wpts = s.get("points") or {}, s.get("win_points") or {}
    shares10 = qin_shares(((pts.get("t10") or {}).get("odds")) or {})
    win10 = ((wpts.get("t10") or {}).get("odds")) or {}
    if len(shares10) < MIN_HORSES:
        return
    for row in rows:
        h = row["horse"]
        if h in shares10 and shares10[h] > 0 and row.get("qin_support_pct") is not None:
            row["qin_move_pct_t10_to_now"] = round(100 * (row["qin_support_pct"] / (100 * shares10[h]) - 1), 1)
        if win10.get(h):
            row["win_move_pct_t10_to_now"] = round(100 * (win10[h] - row["win_odds"]) / win10[h], 1)


# Flag list: every horse whose predicted close price is at least 5% shorter than its price now (predicted_drop_pct >= 5,
# i.e. predicted_close_odds <= win_odds x 0.95). No top-N: a race can have 0 or 5 flagged horses.
FLAG_MIN_DROP_PCT = 5.0
FLAG_RULE = "predicted_close_odds <= win_odds x 0.95 (predicted_drop_pct >= 5)"
# Leave-one-race-out results of that rule. QIN = 16 races, DBL / combined = 12 races (races 2+).
FLAG_VALIDATION = {
    "qin": {"t5": {"flagged_per_race": 2.5, "flagged_fell_any": 0.62, "flagged_fell_10pct": 0.55, "caught_of_fell_10pct": 0.48},
            "t3": {"flagged_per_race": 2.2, "flagged_fell_any": 0.72, "flagged_fell_10pct": 0.56, "caught_of_fell_10pct": 0.48},
            "t2": {"flagged_per_race": 2.3, "flagged_fell_any": 0.76, "flagged_fell_10pct": 0.59, "caught_of_fell_10pct": 0.52}},
    "dbl": {"first": {"flagged_per_race": 2.7, "flagged_fell_any": 0.81, "flagged_fell_10pct": 0.72, "caught_of_fell_10pct": 0.59},
            "t5": {"flagged_per_race": 2.6, "flagged_fell_any": 0.81, "flagged_fell_10pct": 0.74, "caught_of_fell_10pct": 0.64},
            "t2": {"flagged_per_race": 2.2, "flagged_fell_any": 0.85, "flagged_fell_10pct": 0.74, "caught_of_fell_10pct": 0.61}},
    "combined": {"t5": {"flagged_per_race": 2.8, "flagged_fell_any": 0.73, "flagged_fell_10pct": 0.64, "caught_of_fell_10pct": 0.58},
                 "t2": {"flagged_per_race": 2.6, "flagged_fell_any": 0.74, "flagged_fell_10pct": 0.65, "caught_of_fell_10pct": 0.61}},
}

# t1 = one minute before the off. Added 2026-11-22 as an extra option: no t1 history exists, so it runs the t2 fit unchanged
# (same coefficients, same price mapping) and every number it carries is labelled `unvalidated`. Judge it from the live scorecard.
T1_NOTE = {"unvalidated": True, "coefs_from": "t2", "note": "t1 has no history of its own; t2 coefficients reused. Judge from the live scorecard."}
COEFS["t1"] = dict(COEFS["t2"])
PROB["qin"]["t1"] = dict(PROB["qin"]["t2"])
VALIDATION["t1"] = dict(T1_NOTE)
FLAG_VALIDATION["qin"]["t1"] = dict(T1_NOTE)
QIN_FLY_VALIDATION["t1"] = dict(T1_NOTE)

# t10 = ten minutes before the off. Added 2026-11-28: no t10 history exists, so it runs the t5 fit unchanged (WIN price now + Quinella lead;
# no WIN momentum, there is no earlier board) and every number it carries is labelled `unvalidated`. It has no share path and no rise fields.
T10_NOTE = {"unvalidated": True, "coefs_from": "t5", "note": "t10 has no history of its own; t5 coefficients reused. Judge from the live scorecard."}
COEFS["t10"] = dict(COEFS["t5"])
PROB["qin"]["t10"] = dict(PROB["qin"]["t5"])
VALIDATION["t10"] = dict(T10_NOTE)
FLAG_VALIDATION["qin"]["t10"] = dict(T10_NOTE)
QIN_FLY_VALIDATION["t10"] = dict(T10_NOTE)


def flag_rows(rows):
    """Mark rows (already ranked) with `flagged`; returns the flagged horses, best first."""
    for row in rows:
        row["flagged"] = row["predicted_drop_pct"] >= FLAG_MIN_DROP_PCT
    return [row["horse"] for row in rows if row["flagged"]]


def predict_windrop(s, point):
    """Prediction for one race state `s` at `point`; errors are labelled, never guessed."""
    pts, wpts = s.get("points") or {}, s.get("win_points") or {}
    need_t5 = point not in ("t5", "t10")
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
        rows.append({"horse": h, "score": round(score, 3), "win_odds": w_now[h],
                     "win_implied_pct": round(100 * prob[h], 2), "qin_support_pct": round(100 * shares[h], 2),
                     "lead_pct": round(100 * (shares[h] / prob[h] - 1), 1),
                     "win_move_pct_t5_to_now": round(100 * (w_t5[h] - w_now[h]) / w_t5[h], 1) if need_t5 else None,
                     **price_block(w_now[h], score, PROB["qin"][point])})
    rows.sort(key=lambda r: -r["score"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    flagged = flag_rows(rows)
    if point == "t10":
        fly = qin_fly_fields(add_qin_fly(s, point, rows), point)
    else:
        fly = {**qin_fly_fields(add_qin_fly(s, point, rows), point), **add_qin_rise(s, point, rows)}
        fly["qin_fly_and_rising"] = add_fly_and_rising(rows)
        add_t10_move(s, rows)
    return {"model": MODEL, "at_point": point, "made_at": (pts.get(point) or {}).get("observed_at"), **fly,
            "target_at": (pts.get(point) or {}).get("target_at"),
            "inputs": ["WIN", "QIN"], "top": [r["horse"] for r in rows[:TOP]], "horses": rows,
            "flagged": flagged, "flag_rule": FLAG_RULE, "flag_validation": FLAG_VALIDATION["qin"][point],
            "validation": VALIDATION[point], "note": NOTE,
            "meaning": "shorten_prob_10pct = chance the WIN price ends 10% or more shorter than now, shorten_prob_any = chance it ends "
                       "shorter at all; predicted_close_odds = win odds now x exp(-(c0 + c1 x score)) with a 50% band "
                       "(predicted_close_low..high); predicted_drop_pct > 0 = expected to shorten"}


def _flag_outcome(pred, rows):
    """What happened to the flagged horses: how many fell at all / 10%+, and how many 10%+ fallers were not flagged."""
    flagged = set(pred.get("flagged") or [])
    if "flagged" not in pred:
        return {}
    hit = [r for r in rows if r["horse"] in flagged]
    missed = [r for r in rows if r["horse"] not in flagged and r["actual_drop_pct"] >= 10]
    fly = {}
    if "qin_no_fly" in pred:
        for name, key in (("fly", "qin_fly"), ("tie", "qin_tie"), ("nofly", "qin_no_fly")):
            group = [r for r in rows if r["horse"] in set(pred.get(key) or [])]
            fly[f"{name}_n"] = len(group)
            fly[f"{name}_fell_10pct"] = sum(r["actual_drop_pct"] >= 10 for r in group)
        fly["fell_10pct_total"] = sum(r["actual_drop_pct"] >= 10 for r in rows)
        for name, key in (("rise_all", "qin_rise_all_steps"), ("fall5", "qin_fall5_from_t5"), ("flyrise", "qin_fly_and_rising")):
            if key in pred:
                group = [r for r in rows if r["horse"] in set(pred.get(key) or [])]
                fly[f"{name}_n"] = len(group)
                fly[f"{name}_fell_10pct"] = sum(r["actual_drop_pct"] >= 10 for r in group)
    return {**fly, "flagged_n": len(hit), "flagged_fell_any": sum(r["actual_drop_pct"] > 0 for r in hit),
            "flagged_fell_10pct": sum(r["actual_drop_pct"] >= 10 for r in hit), "missed_fell_10pct": len(missed),
            "missed_horses": [r["horse"] for r in missed]}


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
            drop = round(100 * (h["win_odds"] - close) / h["win_odds"], 1)
            row = {"horse": h["horse"], "predicted_close": h["predicted_close_odds"], "actual_close": close,
                   "actual_drop_pct": drop, "abs_log_error": round(abs(math.log(h["predicted_close_odds"] / close)), 3)}
            if h.get("shorten_prob_10pct") is not None:
                row["shorten_prob_10pct"] = h["shorten_prob_10pct"]
                row["shortened_10pct"] = drop >= 10
                row["in_50pct_band"] = h["predicted_close_low"] <= close <= h["predicted_close_high"]
            rows.append(row)
    if len(rows) < MIN_HORSES:
        return {"missing": "too_few_after_start_prices"}
    actual_top = [r["horse"] for r in sorted(rows, key=lambda r: -r["actual_drop_pct"])[:TOP]]
    picked = [r for r in rows if r["horse"] in pred["top"]]
    return {"horses": rows, "actual_top": actual_top,
            "top_hits": len(set(pred["top"]) & set(actual_top)), "chance_hits": round(TOP * TOP / len(rows), 2),
            "top_shortened_10pct": sum(1 for r in picked if r["actual_drop_pct"] >= 10), "top_n": len(picked),
            "close_log_mae": round(sum(r["abs_log_error"] for r in rows) / len(rows), 3),
            **_flag_outcome(pred, rows),
            **({"brier_10pct": round(sum((r["shorten_prob_10pct"] - r["shortened_10pct"]) ** 2 for r in rows) / len(rows), 3),
                "in_50pct_band": sum(r["in_50pct_band"] for r in rows)} if all("shorten_prob_10pct" in r for r in rows) else {})}


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
DBL_COMBINED_POINTS = ("t5", "t2")
DBL_BOARD = {"first": "before_rollover", "t5": "t5", "t2": "t2"}      # race N board each point reads
LEG1_CAP = 10.0
# Leave-one-race-out on 12 races (2 meetings): Brier of P(shortens 10%+) against predicting the base rate, mean predicted
# chance of the top 3 against what happened to them, and mean |ln| error of the close price.
DBL_VALIDATION = {
    "dbl": {"first": {"brier_10pct": 0.126, "brier_base_rate_only": 0.191, "top3_mean_predicted_prob": 0.64, "top3_realised": 0.61, "close_log_mae": 0.241},
            "t5": {"brier_10pct": 0.115, "brier_base_rate_only": 0.181, "top3_mean_predicted_prob": 0.63, "top3_realised": 0.61, "close_log_mae": 0.233},
            "t2": {"brier_10pct": 0.107, "brier_base_rate_only": 0.170, "top3_mean_predicted_prob": 0.61, "top3_realised": 0.58, "close_log_mae": 0.217}},
    "combined": {"t5": {"brier_10pct": 0.109, "brier_base_rate_only": 0.181, "top3_mean_predicted_prob": 0.67, "top3_realised": 0.64, "close_log_mae": 0.229},
                 "t2": {"brier_10pct": 0.102, "brier_base_rate_only": 0.170, "top3_mean_predicted_prob": 0.64, "top3_realised": 0.61, "close_log_mae": 0.221}},
}
DBL_NOTE = ("Exploratory: 12 races (2 meetings), races 2+ only; chances and price bands are leave-one-race-out checked on those. "
            "Horses given 60%+ shortened 10%+ about 7 times in 10, horses given under 15% about 1 time in 25. "
            "A ranking and a chance, not a betting recommendation.")


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


def predict_dbl(s, prev, point, combined=False):
    """windrop_dbl_v1 for race state `s` (race N) with `prev` the state of race N-1; errors are labelled.

    Default: Double only (score = z(edge)). combined=True (t5, t2): edge plus the Quinella lead (score = z(edge) + z(lead)).
    """
    key = DBL_BOARD[point]
    wpts, pts = s.get("win_points") or {}, s.get("points") or {}
    w_first = ((wpts.get("before_rollover") or {}).get("odds")) or {}
    w_now = ((wpts.get(key) or {}).get("odds")) or {}
    w1 = (((prev or {}).get("win_points") or {}).get("after_start") or {}).get("odds") or {}
    frozen = dbl_frozen(prev)
    base = {"model": DBL_MODEL + ("_combined" if combined else ""), "at_point": point}
    if combined and point not in DBL_COMBINED_POINTS:
        return {**base, "error": "combined_needs_t5_or_t2"}
    if not w1:
        return {**base, "error": "need_leg1_win_after_start_board"}
    if not frozen:
        return {**base, "error": "need_frozen_double_board"}
    if not w_first or not w_now:
        return {**base, "error": "need_win_first_board" if not w_first else f"need_win_{key}_board"}
    qin_now = (((pts.get(key) or {}).get("odds")) or {}) if combined else {}
    if combined and not qin_now:
        return {**base, "error": f"need_{key}_quinella_board"}
    shares = qin_shares(qin_now) if combined else {}
    horses = sorted((h for h, o in w_now.items() if o and o > 0 and w_first.get(h) and (not combined or h in shares)), key=int)
    edges = dbl_edges(w_first, w1, frozen, horses)
    horses = [h for h in horses if h in edges]
    if len(horses) < MIN_HORSES:
        return {**base, "error": "too_few_comparable_horses"}
    z_edge = zscores({h: edges[h][0] for h in horses})
    lead = z_lead = None
    if combined:
        total = sum(1 / w_now[h] for h in horses)
        prob = {h: (1 / w_now[h]) / total for h in horses}
        lead = {h: shares[h] / prob[h] - 1 for h in horses}
        z_lead = zscores(lead)
    params = PROB["combined" if combined else "dbl"][point]
    rows = []
    for h in horses:
        score = z_edge[h] + (z_lead[h] if z_lead else 0.0)
        rows.append({"horse": h, "score": round(score, 3), "win_odds": w_now[h],
                     "dbl_implied_win_odds": round(edges[h][1], 1),
                     "edge_pct": round(100 * (w_first[h] / edges[h][1] - 1), 1),
                     "lead_pct": round(100 * lead[h], 1) if lead else None,
                     **price_block(w_now[h], score, params)})
    top_edge = set(sorted(horses, key=lambda h: -z_edge[h])[:TOP])
    top_lead = set(sorted(horses, key=lambda h: -z_lead[h])[:TOP]) if z_lead else set()
    rows.sort(key=lambda r: -r["score"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        if combined:
            row["signals"] = {"edge_top3": row["horse"] in top_edge, "lead_top3": row["horse"] in top_lead}
            row["signals_fired"] = sum(row["signals"].values())
    flagged = flag_rows(rows)
    fly = ({**qin_fly_fields(add_qin_fly(s, point, rows), point), **add_qin_rise(s, point, rows)}
           if point in DBL_COMBINED_POINTS else {})
    if fly:
        fly["qin_fly_and_rising"] = add_fly_and_rising(rows)
    return {**base, **fly, "flagged": flagged, "flag_rule": FLAG_RULE,
            "flag_validation": FLAG_VALIDATION["combined" if combined else "dbl"][point], "made_at": (pts.get(key) or {}).get("observed_at"), "target_at": (pts.get(key) or {}).get("target_at"),
            "inputs": ["WIN", "DBL"] + (["QIN"] if combined else []), "leg1_cap_odds": LEG1_CAP,
            "top": [r["horse"] for r in rows[:TOP]],
            "both_signals": [r["horse"] for r in rows if combined and r["signals_fired"] == 2],
            "horses": rows, "validation": DBL_VALIDATION["combined" if combined else "dbl"][point], "note": DBL_NOTE,
            "meaning": "edge_pct = WIN price at `first` vs the price the frozen Double implies (+ = WIN longer, expected to shorten). "
                       "shorten_prob_10pct = chance the WIN price ends 10% or more shorter than now, shorten_prob_any = chance it ends "
                       "shorter at all; predicted_close_odds with a 50% band (predicted_close_low..high)"}


# ---------------------------------------------------------------------------------------------------------------
# windrop_longshot_v1 (t2): horses at 20x or more. windrop_v1 / windrop_dbl_v1 lean on favourite-ness, so a long price
# is never ranked high (0 of 74 longshots in 16 races). The Quinella trend itself does see them: the horses whose Quinella
# combinations shortened most between t5 and t2 (top 3 of the race). Flag only, no price or chance is predicted.
# 16 races (2026-11-14 ST, 2026-11-18 HV): 13 longshots flagged, 4 shortened 10%+ (31%); 61 not flagged, 0 did (0%);
# all 74 longshots: 4 (5%). Four fallers only: low confidence, kept separate on purpose.
# ---------------------------------------------------------------------------------------------------------------
LONGSHOT_MODEL = "windrop_longshot_v1"
LONGSHOT_MIN_ODDS = 20.0
LONGSHOT_VALIDATION = {"races": 16, "longshots": 74, "flagged": 13, "flagged_shortened_10pct": 4,
                       "unflagged": 61, "unflagged_shortened_10pct": 0, "all_longshots_shortened_10pct": 4}
LONGSHOT_NOTE = ("Low confidence: 4 longshots shortened 10%+ in 16 races. Of the longshots whose Quinella combinations shortened "
                 "most (race top 3), about 3 in 10 shortened 10%+; none of the others did. A flag, not a price or a chance.")


def qin_horse_drops(early, late):
    """{horse: mean % drop of its Quinella combinations between two boards}; needs 5+ comparable combinations."""
    per = {}
    for pair, a in (early or {}).items():
        b = (late or {}).get(pair)
        if a and b:
            for horse in pair.split("-"):
                per.setdefault(horse, []).append(100 * (a - b) / a)
    return {h: sum(v) / len(v) for h, v in per.items() if len(v) >= 5}


def predict_longshot(s):
    pts, wpts = s.get("points") or {}, s.get("win_points") or {}
    base = {"model": LONGSHOT_MODEL, "at_point": "t2"}
    early, late = ((pts.get("t5") or {}).get("odds")) or {}, ((pts.get("t2") or {}).get("odds")) or {}
    w_now = ((wpts.get("t2") or {}).get("odds")) or {}
    if not early or not late or not w_now:
        return {**base, "error": "need_t5_t2_quinella_and_t2_win_boards"}
    drops = qin_horse_drops(early, late)
    horses = [h for h in drops if w_now.get(h) and w_now[h] > 0]
    if len(horses) < MIN_HORSES:
        return {**base, "error": "too_few_comparable_horses"}
    order = sorted(horses, key=lambda h: -drops[h])
    race_rank = {h: i for i, h in enumerate(order, 1)}
    rows = [{"horse": h, "win_odds": w_now[h], "qin_drop_pct_t5_to_t2": round(drops[h], 2), "race_rank": race_rank[h],
             "flagged": race_rank[h] <= TOP}
            for h in sorted(horses, key=lambda h: race_rank[h]) if w_now[h] >= LONGSHOT_MIN_ODDS]
    return {**base, "min_odds": LONGSHOT_MIN_ODDS, "made_at": (pts.get("t2") or {}).get("observed_at"),
            "flagged": [r["horse"] for r in rows if r["flagged"]], "horses": rows,
            "validation": LONGSHOT_VALIDATION, "note": LONGSHOT_NOTE,
            "meaning": f"horses at {LONGSHOT_MIN_ODDS:g}x or more at t2; flagged = in the race top {TOP} by mean Quinella-combination "
                       "drop t5 -> t2 (all horses ranked together)"}


def longshot_outcome(pred, wpts):
    if not pred or "error" in pred:
        return None
    final = ((wpts or {}).get("after_start") or {}).get("odds")
    if not final:
        return {"missing": "no_after_start"}
    rows = [{"horse": h["horse"], "flagged": h["flagged"], "win_odds": h["win_odds"], "actual_close": final.get(h["horse"]),
             "actual_drop_pct": round(100 * (h["win_odds"] - final[h["horse"]]) / h["win_odds"], 1)}
            for h in pred["horses"] if final.get(h["horse"])]
    flagged = [r for r in rows if r["flagged"]]
    return {"horses": rows, "longshots": len(rows), "flagged_n": len(flagged),
            "flagged_fell_10pct": sum(r["actual_drop_pct"] >= 10 for r in flagged),
            "unflagged_fell_10pct": sum(r["actual_drop_pct"] >= 10 for r in rows if not r["flagged"])}
