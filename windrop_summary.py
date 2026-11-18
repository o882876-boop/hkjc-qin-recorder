"""A readable per-race-day summary (markdown) of the windrop predictions: one file to open on GitHub (phone or desktop).

Pure functions, no I/O. `build_summary(day, venue, state)` takes the recorder state (race number -> race state with the stored
`windrop_*` predictions, `names`, `post`, `win_points`) and returns the markdown text, or "" when nothing has been predicted yet.
Everything shown is what the predictions already say (see docs/WINDROP.md); nothing is recomputed except the after-the-race column.
"""
STATE_TEXT = {"fly": "✅有飛", "tie": "➖打和", "no_fly": "❌冇飛"}
QIN_KEYS = ("windrop_t2", "windrop_t3", "windrop_t5")
DBL_KEYS = ("windrop_dbl_t2", "windrop_dbl_t5", "windrop_dbl_first")
COMBO_KEYS = ("windrop_combo_t2", "windrop_combo_t5")


def _ok(pred):
    return bool(pred) and "error" not in pred and bool(pred.get("horses"))


def _latest(s, keys):
    for key in keys:
        if _ok(s.get(key)):
            return s[key]
    return None


def _cell(value):
    return str(value).replace("|", "/").replace("\n", " ")


def _name(s, horse):
    return (s.get("names") or {}).get(str(horse)) or ""


def _label(s, horse):
    name = _name(s, horse)
    return f"{horse} {name}".strip()


def _times(s, keys, labels):
    got = [label for key, label in zip(keys, labels) if _ok(s.get(key))]
    return " ".join(reversed(got)) if got else "-"


def _hhmm(post):
    try:
        return post.strftime("%H:%M")
    except AttributeError:
        return str(post or "")[11:16]


def _flagged(pred):
    return list(pred.get("flagged") or []) if pred else []


def _names(s, horses):
    return ", ".join(_label(s, h) for h in horses) or "-"


def _race_section(n, s):
    qin, dbl, combo = _latest(s, QIN_KEYS), _latest(s, DBL_KEYS), _latest(s, COMBO_KEYS)
    base = qin or dbl or combo
    if not base:
        return None
    rows = {name: {r["horse"]: r for r in pred["horses"]} for name, pred in (("qin", qin), ("dbl", dbl), ("combo", combo)) if pred}
    final = ((s.get("win_points") or {}).get("after_start") or {}).get("odds") or {}
    longshot = s.get("windrop_longshot_t2") or {}
    long_flag = set(longshot.get("flagged") or []) if _ok(longshot) else set()
    no_fly = set((qin or combo or {}).get("qin_no_fly") or [])
    fall5 = set((qin or {}).get("qin_fall5_from_t5") or [])
    horses = list(rows.get("qin") or rows.get("combo") or rows["dbl"])

    def sort_key(h):
        for kind in ("combo", "dbl", "qin"):
            if h in rows.get(kind, {}):
                return -rows[kind][h]["shorten_prob_10pct"]
        return 0

    horses.sort(key=sort_key)
    head = (f"### 第{n}場　開跑 {_hhmm(s.get('post'))}　｜　連贏 {_times(s, QIN_KEYS[::-1], ('t5', 't3', 't2'))}"
            f"　孖寶 {_times(s, DBL_KEYS[::-1], ('first', 't5', 't2'))}")
    out = [head, "",
           "| 馬號 | 馬名 | 賠率 | 連贏佔% | 獨贏佔% | 差(百分點) | 連贏飛 | 連贏佔%：過關後→t5→t3→t2 | 孖寶edge | 預計收盤 連/孖/合 | 縮短≥10%機會 連/孖/合 | 標出 | 賽後 收盤(縮短) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for h in horses:
        q, d, c = rows.get("qin", {}).get(h), rows.get("dbl", {}).get(h), rows.get("combo", {}).get(h)
        main = q or c or d
        odds = main["win_odds"]
        share = f"{q['qin_support_pct']:.1f}" if q else ""
        wshare = f"{q['win_implied_pct']:.1f}" if q else ""
        gap = f"{q['qin_gap_pp']:+.1f}" if q and "qin_gap_pp" in q else ""
        fly = STATE_TEXT.get((q or c or {}).get("qin_fly_state"), "")
        if (q or c or {}).get("qin_fly_and_rising"):
            fly += " 🔺"
        path_row = q or c or {}
        path = "→".join(f"{v:.1f}" for v in (path_row.get("qin_pct_path") or {}).values())
        if path_row.get("qin_rise_all_steps"):
            path += " ⬆"
        if h in fall5:
            path += " ⬇"
        edge = f"{d['edge_pct']:+.0f}%" if d else ""
        closes = " / ".join(f"{r['predicted_close_odds']:.1f}" if r else "-" for r in (q, d, c))
        chances = " / ".join(f"{100 * r['shorten_prob_10pct']:.0f}" if r else "-" for r in (q, d, c))
        marks = "".join(tag for tag, r in (("連", q), ("孖", d), ("合", c)) if r and r.get("flagged"))
        marks = (("★" + marks) if marks else "") + (" 冷" if h in long_flag else "") + (" 排除" if h in no_fly else "")
        after = ""
        if final.get(h):
            after = f"{final[h]:.1f} ({100 * (odds - final[h]) / odds:+.0f}%)"
        out.append("| " + " | ".join(_cell(x) for x in (h, _name(s, h), f"{odds:.1f}", share, wshare, gap, fly, path, edge, closes, chances, marks.strip(), after)) + " |")
    notes = []
    for label, pred in (("連贏", s.get("windrop_t2") or s.get("windrop_t3") or s.get("windrop_t5")), ("孖寶", s.get("windrop_dbl_t2") or s.get("windrop_dbl_t5") or s.get("windrop_dbl_first"))):
        if pred and "error" in pred:
            notes.append(f"{label}預測：{pred['error']}")
    if notes:
        out += ["", "_" + "；".join(notes) + "_"]
    return "\n".join(out)


def _overview(state):
    lines = ["| 場 | 開跑 | 連贏標出 | 孖寶標出 | 合併標出 | 冷馬旗標(≥20倍) | 冇飛(建議排除) |", "|---|---|---|---|---|---|---|"]
    for n in sorted(state):
        s = state[n]
        qin, dbl, combo = _latest(s, QIN_KEYS), _latest(s, DBL_KEYS), _latest(s, COMBO_KEYS)
        if not (qin or dbl or combo):
            continue
        longshot = s.get("windrop_longshot_t2")
        lines.append("| " + " | ".join(_cell(x) for x in (
            n, _hhmm(s.get("post")), _names(s, _flagged(qin)), _names(s, _flagged(dbl)), _names(s, _flagged(combo)),
            _names(s, longshot.get("flagged") or []) if _ok(longshot) else "-", _names(s, (qin or combo or {}).get("qin_no_fly") or []))) + " |")
    return lines


LEGEND = [
    "**點睇**：每場一個表,頭一行係最新一個時間點嘅預測,按「縮短≥10%機會」由高到低。",
    "- **預計收盤 連/孖/合**：連贏預測 / 孖寶預測 / 兩者合併預測嘅預計獨贏收盤賠率;**縮短≥10%機會** 同樣三個,單位 %。",
    "- **標出**：預計收盤 ≤ 當下賠率×0.95(連=連贏、孖=孖寶、合=合併);冷=賠率≥20倍而連贏組合跌幅排全場前3;排除=連贏冇飛。",
    "- **連贏飛**：連贏佔% 大過獨贏佔% 為✅有飛;差距在 −1 個百分點內為➖打和(不排除);更細為❌冇飛(建議排除)。🔺=有飛而且連贏佔% 由過關後每一步都上升。",
    "- **連贏佔%路徑**：由過關後到 t5、t3、t2 嘅連贏佔%;⬆=每步上升,⬇=t5到t2跌5%以上。",
    "- **孖寶edge**：第1腿停賣後第一張獨贏比孖寶暗示價長幾多(正=預期縮短)。",
    "- **賽後 收盤(縮短)**：獨贏收盤賠率,括號內由預測點到收盤,**+ 係縮短(落飛)**、− 係拉長。",
    "",
    "_探索性(2 個賽日、16 場):標出嘅馬約 55–75% 之後縮短≥10%(全部馬約 21–26%),冇飛嘅馬約 9–10%。係排名同機會率,唔係投注建議。詳見 docs/WINDROP.md。_",
]


def build_summary(day, venue, state):
    sections = [x for x in (_race_section(n, state[n]) for n in sorted(state)) if x]
    if not sections:
        return ""
    lines = [f"# windrop 預測摘要　{day}　{venue}", "", "## 今日標出總表", ""] + _overview(state) + ["", "## 圖例", ""] + LEGEND + ["", "## 逐場", ""]
    for section in sections:
        lines += [section, ""]
    return "\n".join(lines).rstrip() + "\n"
