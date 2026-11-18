"""Reproduce the windrop backtests (and refit the coefficients) from a local checkout of the private `odds-data` branch.

    git clone --depth 1 --branch odds-data <private repo> odds-data
    python3 research/windrop/backtest.py --data odds-data            # leave-one-race-out tables
    python3 research/windrop/backtest.py --data odds-data --refit    # print COEFS / PROB / DBL_COEFS-style JSON for windrop.py

Reads `qin-history/<date>_<venue>/race-NN-*.json` (WIN + Quinella boards at before_rollover, t5, t3, t2, after_start) and
`dbl-history/...` (the Double frozen when the previous race stopped selling). Only numpy is needed. Feature definitions come
from windrop.py so the backtest and the live predictions cannot drift apart. Every result is leave-one-race-out: each race is
predicted from models fitted on the other races. Target: WIN price ends >= 10% shorter than at the prediction point.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import windrop  # noqa: E402

POINTS = ("before_rollover", "t5", "t3", "t2")
THRESHOLD = 10.0                        # % shortening that counts as "落飛"
FLAG_LOG = math.log(1 / 0.95)           # flag rule: predicted close <= price now x 0.95


def z(values):
    v = np.asarray(values, float)
    sd = v.std()
    return (v - v.mean()) / sd if sd > 1e-12 else np.zeros(len(v))


def rank_corr(a, b):
    return float(np.corrcoef(np.argsort(np.argsort(a)), np.argsort(np.argsort(b)))[0, 1])


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def board(record, point):
    """{combination: odds} for one Quinella point, from the per-combination rows of a race record."""
    return {c["combination"]: c["odds"][point] for c in record["combinations"] if c["odds"].get(point)}


def load_races(data, days=None):
    """One dict per race with the horses, features at each point and the outcome."""
    root = Path(data)
    races = []
    for day_dir in sorted((root / "qin-history").glob("*")):
        if days and day_dir.name not in days:
            continue
        qin = {int(re.search(r"race-(\d+)", f.name).group(1)): load_json(f) for f in sorted(day_dir.glob("race-*.json"))}
        dbl = {}
        for f in sorted((root / "dbl-history" / day_dir.name).glob("race-*.json")):
            d = load_json(f)
            if d.get("combinations"):
                dbl[d["leg1"]] = d
        for n, q in sorted(qin.items()):
            wp = q.get("win_points") or {}
            if not all(wp.get(k) for k in ("t5", "t3", "t2", "after_start")) or not all((q["points"] or {}).get(k) for k in ("t5", "t3", "t2")):
                continue
            boards = {k: windrop.qin_shares(board(q, k)) for k in POINTS if (q["points"] or {}).get(k)}
            win = {k: (wp[k] or {}).get("odds") or {} for k in (*POINTS, "after_start") if wp.get(k)}
            first_ok = "before_rollover" in win and "before_rollover" in boards
            horses = [h for h in win["t2"] if all(win[k].get(h) for k in ("t5", "t3", "t2", "after_start"))
                      and all(h in boards[k] for k in ("t5", "t3", "t2")) and (not first_ok or (win["before_rollover"].get(h) and h in boards["before_rollover"]))]
            if len(horses) < windrop.MIN_HORSES:
                continue
            race = {"race": (day_dir.name, n), "horses": horses, "feat": {}, "y": {}, "ly": {}, "w": {}, "dbl": False,
                    "qin_t5": board(q, "t5"), "qin_t2": board(q, "t2"), "win_t2": win["t2"], "win_close": win["after_start"]}
            for point in (k for k in POINTS if k in win and k in boards and (k != "before_rollover" or first_ok)):
                w = np.array([win[point][h] for h in horses])
                prob = (1 / w) / (1 / w).sum()
                lead = np.array([boards[point][h] for h in horses]) / prob - 1
                mom = np.array([100 * (win["t5"][h] - win[point][h]) / win["t5"][h] for h in horses]) if point in ("t3", "t2") else np.zeros(len(horses))
                race["feat"][point] = {"fav": z(np.log(prob)), "lead": z(lead), "winmom": z(mom)}
                race["w"][point] = w
                close = np.array([win["after_start"][h] for h in horses])
                race["y"][point] = 100 * (w - close) / w
                race["ly"][point] = np.log(w / close)
            w1 = (((qin.get(n - 1) or {}).get("win_points") or {}).get("after_start") or {}).get("odds")
            if first_ok and w1 and n - 1 in dbl:
                d = dbl[n - 1]
                frozen = {k: v for k, v in ((d.get("final_open") or {}).get("odds") or {}).items() if v} or \
                    {c["combination"]: c["odds"]["t2"] for c in d["combinations"] if c["odds"].get("t2")}
                edges = windrop.dbl_edges(win["before_rollover"], w1, frozen, horses)
                if len(edges) >= windrop.MIN_HORSES:
                    mean = np.mean([e for e, _ in edges.values()])
                    e = z([edges[h][0] if h in edges else mean for h in horses])
                    race["dbl"] = True
                    for point in race["feat"]:
                        race["feat"][point]["edge"] = e
            races.append(race)
    return races


# ---- model fitting -------------------------------------------------------------------------------------------------
def rank_target(y):
    order = np.argsort(y)
    rk = np.empty(len(order))
    rk[order] = np.arange(len(order))
    return z(rk)


def design(race, point, names):
    return np.column_stack([np.ones(len(race["horses"]))] + [race["feat"][point][k] for k in names])


def fit_logistic(x, y, l2=1e-3):
    a, X = np.zeros(2), np.column_stack([np.ones(len(x)), x])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ a))
        a -= np.linalg.solve((X.T * (p * (1 - p))) @ X + l2 * np.eye(2), X.T @ (p - y) + l2 * a * np.array([0, 1]))
    return a


def fit_model(train, point, names, weights=None):
    """Score weights (rank regression, or fixed `weights`), then chance and price mapping on the training scores."""
    if weights is None:
        X = np.vstack([design(r, point, names) for r in train])
        b = np.linalg.lstsq(X, np.concatenate([rank_target(r["y"][point]) for r in train]), rcond=None)[0][1:]
    else:
        b = np.array([weights[k] for k in names])
    score = lambda r: np.column_stack([r["feat"][point][k] for k in names]) @ b
    S = np.concatenate([score(r) for r in train])
    y10 = np.concatenate([(r["y"][point] >= THRESHOLD).astype(float) for r in train])
    y0 = np.concatenate([(r["y"][point] > 0).astype(float) for r in train])
    L = np.concatenate([r["ly"][point] for r in train])
    c1 = np.cov(S, L)[0, 1] / np.var(S, ddof=1)
    c0 = L.mean() - c1 * S.mean()
    r25, r75 = np.percentile(L - (c0 + c1 * S), [25, 75])
    a10, a0 = fit_logistic(S, y10), fit_logistic(S, y0)
    return {"names": names, "b": b, "score": score, "c0": c0, "c1": c1, "r25": r25, "r75": r75, "a10": a10, "a0": a0}


def predict(model, race):
    s = model["score"](race)
    return {"p": 1 / (1 + np.exp(-(model["a10"][0] + model["a10"][1] * s))), "pl": model["c0"] + model["c1"] * s,
            "lo": model["c0"] + model["c1"] * s + model["r25"], "hi": model["c0"] + model["c1"] * s + model["r75"]}


def leave_one_out(races, point, names, weights=None):
    out = []
    for i, race in enumerate(races):
        model = fit_model([r for j, r in enumerate(races) if j != i], point, names, weights)
        out.append({**predict(model, race), "y": (race["y"][point] >= THRESHOLD).astype(float), "ly": race["ly"][point],
                    "yy": race["y"][point], "score": model["score"](race)})
    return out


def summarise(label, out):
    P, Y = np.concatenate([o["p"] for o in out]), np.concatenate([o["y"] for o in out])
    LY, PL = np.concatenate([o["ly"] for o in out]), np.concatenate([o["pl"] for o in out])
    LO, HI = np.concatenate([o["lo"] for o in out]), np.concatenate([o["hi"] for o in out])
    flags = [o["pl"] >= FLAG_LOG for o in out]
    F = np.concatenate(flags)
    fell = np.concatenate([o["ly"] > 0 for o in out])
    rho = np.mean([rank_corr(o["score"], o["yy"]) for o in out])
    top3 = np.mean([o["y"][np.argsort(-o["p"])[:3]].mean() for o in out])
    print(f"{label:<30}{len(out):>3}场 ρ {rho:+.2f} | Brier {np.mean((P - Y) ** 2):.3f} (基準 {np.mean((Y.mean() - Y) ** 2):.3f}) "
          f"| 前三落≥10% {100 * top3:.0f}% | 收盤 ln 誤差 {np.mean(np.abs(LY - PL)):.3f}, 50%區間 {100 * np.mean((LY >= LO) & (LY <= HI)):.0f}% "
          f"| 標出 每場{np.mean([f.sum() for f in flags]):.1f} 有落{100 * fell[F].mean() if F.any() else 0:.0f}% "
          f"落≥10% {100 * Y[F].mean() if F.any() else 0:.0f}% 捉到 {100 * Y[F].sum() / max(Y.sum(), 1):.0f}% ({int(Y[F].sum())}/{int(Y.sum())})")


def longshot_summary(races):
    """windrop_longshot_v1: horses at 20x+ at t2; flagged = race top 3 by mean Quinella-combination drop t5 -> t2 (all horses)."""
    flagged = fl10 = other = other10 = 0
    for r in races:
        drops = windrop.qin_horse_drops(r["qin_t5"], r["qin_t2"])
        horses = [h for h in drops if r["win_t2"].get(h) and r["win_close"].get(h)]
        if len(horses) < windrop.MIN_HORSES:
            continue
        top = set(sorted(horses, key=lambda h: -drops[h])[:windrop.TOP])
        for h in horses:
            if r["win_t2"][h] < windrop.LONGSHOT_MIN_ODDS:
                continue
            fell = 100 * (r["win_t2"][h] - r["win_close"][h]) / r["win_t2"][h] >= THRESHOLD
            if h in top:
                flagged, fl10 = flagged + 1, fl10 + fell
            else:
                other, other10 = other + 1, other10 + fell
    print(f"longshots (>= {windrop.LONGSHOT_MIN_ODDS:g}x at t2): flagged {flagged}, shortened 10%+ {int(fl10)}; "
          f"not flagged {other}, shortened 10%+ {int(other10)}; all {flagged + other}: {int(fl10 + other10)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="local checkout of the odds-data branch")
    ap.add_argument("--days", help="comma separated folder names, e.g. 2026-11-14_ST,2026-11-18_HV (default: all)")
    ap.add_argument("--refit", action="store_true", help="print the full-sample fit as JSON for windrop.py")
    args = ap.parse_args()
    races = load_races(args.data, set(args.days.split(",")) if args.days else None)
    dbl = [r for r in races if r["dbl"]]
    print(f"{len(races)} races ({len({r['race'][0] for r in races})} race days), {len(dbl)} with a Double edge (races 2+). "
          f"Target: WIN ends >= {THRESHOLD:g}% shorter than at the point. All results leave-one-race-out.\n")
    print("== Quinella (windrop_v1): fav + lead + WIN momentum, weights fitted per fold ==")
    for point in ("t5", "t3", "t2"):
        summarise(f"quinella {point}", leave_one_out(races, point, ["fav", "lead"] + (["winmom"] if point != "t5" else [])))
    if dbl:
        print("\n== Double only (windrop_dbl_v1): z(edge) ==")
        for point in ("before_rollover", "t5", "t2"):
            summarise(f"double {'first' if point == 'before_rollover' else point}", leave_one_out(dbl, point, ["edge"], {"edge": 1.0}))
        print("\n== Combined: z(edge) + z(lead), equal weights ==")
        for point in ("t5", "t2"):
            summarise(f"combined {point}", leave_one_out(dbl, point, ["edge", "lead"], {"edge": 1.0, "lead": 1.0}))
    print("\n== Longshot supplement (windrop_longshot_v1, no model: a flag) ==")
    longshot_summary(races)
    if args.refit:
        out = {"qin": {}, "dbl": {}, "combined": {}}
        pick = lambda m: {"c0": round(m["c0"], 4), "c1": round(m["c1"], 4), "a10": round(m["a10"][0], 3), "b10": round(m["a10"][1], 3),
                          "a0": round(m["a0"][0], 3), "b0": round(m["a0"][1], 3), "r25": round(m["r25"], 3), "r75": round(m["r75"], 3)}
        for point in ("t5", "t3", "t2"):
            names = ["fav", "lead"] + (["winmom"] if point != "t5" else [])
            m = fit_model(races, point, names)
            out["qin"][point] = {**pick(m), "score_weights": dict(zip(names, [round(float(x), 4) for x in m["b"]]))}
        for point, label in (("before_rollover", "first"), ("t5", "t5"), ("t2", "t2")):
            if dbl:
                out["dbl"][label] = pick(fit_model(dbl, point, ["edge"], {"edge": 1.0}))
                if point != "before_rollover":
                    out["combined"][label] = pick(fit_model(dbl, point, ["edge", "lead"], {"edge": 1.0, "lead": 1.0}))
        print("\n== --refit: paste into windrop.py (PROB; the QIN score_weights go to COEFS as fav/winmom/lead) ==")
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
