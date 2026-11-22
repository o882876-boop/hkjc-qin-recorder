"""A readable per-race-day page (markdown) of the momentum t3/t2 predictions: one file to open on GitHub (phone or desktop).

Pure functions, no I/O. `build_momentum(day, venue, state, outcome_fn)` takes the recorder state (race number -> race state with the
stored `t3_prediction` / `t2_prediction`, `points`, `win_points`, `names`, `post`) and returns the markdown text, or "" when nothing has
been predicted yet. Nothing is recomputed except the after-the-race columns, taken from `outcome_fn` (recorder.predict_outcome).
"""
POINTS = ("t3", "t2")


def _ok(pred):
    return bool(pred) and "error" not in pred and bool(pred.get("horses"))


def _cell(value):
    return "-" if value is None or value == "" else str(value).replace("|", "/").replace("\n", " ")


def _pct(value):
    return "-" if value is None else f"{value:+.0f}%"


def _safe_outcome(outcome_fn, pred, s):
    try:
        out = outcome_fn(pred, s.get("points") or {}, s.get("win_points") or {})
    except Exception:  # noqa: BLE001 - a bad outcome must not blank the page
        return None
    return out if out and "qin_top_hits" in out else None


def build_momentum(day, venue, state, outcome_fn):
    races = sorted(n for n, s in state.items() if any(_ok(s.get(f"{p}_prediction")) for p in POINTS))
    if not races:
        return ""
    totals = {p: [0, 0, 0.0] for p in POINTS}
    blocks = []
    for n in races:
        s = state[n]
        preds = {p: s.get(f"{p}_prediction") for p in POINTS if _ok(s.get(f"{p}_prediction"))}
        outs = {p: _safe_outcome(outcome_fn, preds[p], s) for p in preds}
        for p, out in outs.items():
            if out:
                totals[p][0] += out["qin_top_hits"]
                totals[p][1] += 3
                totals[p][2] += out["qin_chance_hits"]
        base = preds.get("t2") or preds["t3"]
        rank = {p: {h["horse"]: i for i, h in enumerate(preds[p]["horses"], 1)} for p in preds}
        later = {p: (outs[p] or {}).get(f"qin_drop_pct_{p}_to_after_start", {}) for p in preds}
        names = s.get("names") or {}
        post = s.get("post")
        head = f"### 第{n}場" + (f"　開跑 {post:%H:%M}" if hasattr(post, "strftime") else "")
        head += "　｜　" + " ".join(f"{p} 預測" for p in preds) + ("　｜　已完成" if any(outs.values()) else "　｜　未完成")
        rows = ["| 馬號 | 馬名 | t3 排名 | t2 排名 | 獨贏賠率 | 連贏落飛%(之前) | 之後落飛%(t2→封盤) |", "|---|---|---|---|---|---|---|"]
        for h in base["horses"]:
            no = h["horse"]
            point = "t2" if "t2" in preds else "t3"
            star = lambda p: ("★" if no in preds[p]["top"] else "") + str(rank[p].get(no, "-")) if p in preds else "-"
            rows.append(f"| {no} | {_cell(names.get(str(no)))} | {star('t3')} | {star('t2')} | {_cell(h.get(f'win_odds_{point}'))} | "
                        f"{_pct(h.get(f'qin_drop_pct_ref_to_{point}'))} | {_pct(later[point].get(no)) if outs.get(point) else '-'} |")
        lines = [head, "", *rows, ""]
        done = [(p, outs[p]) for p in preds if outs[p]]
        if done:
            for p, out in done:
                real = " ".join(f"{h} {names.get(str(h), '')}".strip() for h in out["qin_actual_top"])
                lines.append(f"- **{p}**:預測 {' '.join(preds[p]['top'])} → 實際 {p} 之後落飛最多(連贏) {real};命中 **{out['qin_top_hits']}/3**(運氣約 {out['qin_chance_hits']})")
            lines.append("")
        blocks.append("\n".join(lines))
    tot = " ／ ".join(f"**{p}** {t[0]}/{t[1]}(運氣約 {t[2]:.1f})" for p, t in totals.items() if t[1])
    head = [f"# 動量預測　{day}　{venue}", "",
            "預測**邊啲馬喺該時間點之後會繼續落飛(賠率縮短)**,唔係預測邊匹贏,亦唔係投注建議。",
            "排名按「由 t5 到該時間點已經落咗幾多」(連贏組合 + 獨贏)計;★ = 前 3 名;`之後落飛%` 喺賽後先有。", "",
            f"**今日累計命中(前 3 匹對實際落飛最多 3 匹)**:{tot or '未有完成場次'}", ""]
    note = ["_探索性:2 個賽日回測模型時睇過數據,偏樂觀;11/18 係未見過嘅數據(t3、t2 各 15/27,運氣約 6.8)。詳見 README。_", ""]
    return "\n".join(head + blocks + note)
