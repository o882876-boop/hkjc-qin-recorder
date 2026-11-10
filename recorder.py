"""Capture timestamped HKJC Quinella boards and publish per-race records privately.

Five snapshots per race N (N >= 2):
  before_rollover  first poll after race N-1 stops selling (the off)
  after_rollover   2 min after race N-1 WIN payout (fallback: 10 min after result)
  t5, t3           5 and 3 min before race N's published post time
  after_start      first closed board after race N's off
Race 1 only has t5, t3 and after_start.
"""
import base64
import gzip
import itertools
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")
ENDPOINT = "https://info.cld.hkjc.com/graphql/base-get/"
# Both query strings are used verbatim: the HKJC endpoint only accepts whitelisted query shapes.
QUERY = "\n      query sp4e_racing_pmPool($date: String, $venueCode: String, $oddsTypes: [OddsType], $raceNo: Int) {\n          raceMeetings(date: $date, venueCode: $venueCode)\n          {\n            pmPools(oddsTypes: $oddsTypes, raceNo: $raceNo) {\n              id\n              status\n              sellStatus\n              oddsType\n              lastUpdateTime\n              oddsLastUpdateTime\n              guarantee\n              minTicketCost\n              name_en\n              name_ch\n              leg {\n                number\n                races\n              }\n              cWinSelections {\n                composite\n                name_ch\n                name_en\n                starters\n              }\n              oddsNodes {\n                combString\n                oddsValue\n                hotFavourite\n                oddsDropValue\n                bankerOdds {\n                  combString\n                  oddsValue\n                }\n              }\n            }\n          }\n      }\n\n"
GATE = "\n        \n        \n        query raceMeetings($date: String, $venueCode: String) {\n            timeOffset {\n              rc\n            }\n            activeMeetings : raceMeetings\n            {\n              id\n              venueCode\n              date\n              status\n              races {\n                no\n                postTime\n                status\n                wageringFieldSize\n              }\n              poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n                status\n              }\n            }\n            raceMeetings(date: $date, venueCode: $venueCode)\n            {\n              id\n              status\n              venueCode\n              date\n              totalNumberOfRace\n              currentNumberOfRace\n              dateOfWeek\n              meetingType\n              totalInvestment\n              country {\n                code\n                namech\n                nameen\n                seq\n              }\n              races {\n                ...raceFragment\n                runners {\n                    id\n                    no\n                    standbyNo\n                    status\n                    name_ch\n                    name_en\n                    horse {\n                      id\n                      code\n                    }\n                    color\n                    barrierDrawNumber\n                    handicapWeight\n                    currentWeight\n                    currentRating\n                    internationalRating\n                    gearInfo\n                    racingColorFileName\n                    allowance\n                    trainerPreference\n                    last6run\n                    saddleClothNo\n                    trumpCard\n                    priority\n                    finalPosition\n                    deadHeat\n                    winOdds\n                    jockey {\n                      code\n                      name_en\n                      name_ch\n                    }\n                    trainer {\n                      code\n                      name_en\n                      name_ch\n                    }\n                }\n              }\n              obSt: pmPools(oddsTypes: [WIN, PLA]) {\n                leg {\n                  races\n                }\n                oddsType\n                comingleStatus\n              }\n              poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n                id\n                leg {\n                  number\n                  races\n                }\n                status\n                sellStatus\n                oddsType\n                investment\n                mergedPoolId\n                lastUpdateTime\n              }\n              ...racingBlockFragment\n              pmPools(oddsTypes: []) {\n                id\n              }\n              jkcInstNo : foPools(oddsTypes: [JKC], filters: [\"top\"]) {\n                instNo\n              }\n              tncInstNo : foPools(oddsTypes: [TNC], filters: [\"top\"]) {\n                instNo\n              }\n            }\n        }\n    \nfragment raceFragment on Race {\n    id\n    no\n    status\n    raceName_en\n    raceName_ch\n    postTime\n    country_en\n    country_ch\n    distance\n    wageringFieldSize\n    go_en\n    go_ch\n    ratingType\n    raceTrack {\n      description_en\n      description_ch\n    }\n    raceCourse {\n      description_en\n      description_ch\n      displayCode\n    }\n    claCode\n    raceClass_en\n    raceClass_ch\n    judgeSigns {\n      value_en\n    }\n  }\nfragment racingBlockFragment on RaceMeeting {\n    jpEsts: pmPools(oddsTypes: [WIN,PLA,TCE,TRI,FF,QTT,DT,TT,SixUP], filters: [\"jackpot\", \"estimatedDividend\"]) {\n      leg {\n        number\n        races\n      }\n      oddsType\n      jackpot\n      estimatedDividend\n      mergedPoolId\n    }\n    poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n      id\n      leg {\n        races\n      }\n    }\n    penetrometerReadings(filters:[\"first\"]) {\n      reading\n      readingTime\n    }\n    hammerReadings(filters:[\"first\"]) {\n      reading\n      readingTime\n    }\n    changeHistories(filters:[\"top3\"]) {\n      type\n      time\n      raceNo\n      runnerNo\n      horseName_ch\n      horseName_en\n      jockeyName_ch\n      jockeyName_en\n      scratchHorseName_ch\n      scratchHorseName_en\n      handicapWeight\n      scrResvIndicator\n    }\n  }\n\n"
POINTS = ("before_rollover", "after_rollover", "t5", "t3", "after_start")
OPEN_POINTS = POINTS[:4]
# Status vocabulary taken from HKJC's own betting site code (bet.hkjc.com main bundle).
RACE_OFF = {"CLOSED", "RESULT"}             # race no longer selling: off / finished
RACE_RESULT = {"RESULT"}
RACE_VOID = {"VOIDED", "ABANDONED", "ABANDON", "ABANDON_PARTIAL", "CANCELLED", "VOID"}
RUNNER_OUT = {"SCRATCHED", "SCRATCHEDRESERVED", "STANDBY", "RESERVED"}
WINDOW = timedelta(seconds=35)              # a snapshot may be taken up to 35 s after its target
FALLBACK_AGE = timedelta(seconds=60)        # max age of "last open board" used for after_start
EARLY_STOP = timedelta(minutes=2)           # stop-sell earlier than post-2min is a suspension
START_CONFIRM = timedelta(seconds=90)       # use stop-sell as the off if race status never says CLOSED
NO_RESULT_ANCHOR = timedelta(minutes=14)    # last-resort rollover anchor: previous off + 14 min
POLL = 8
SOFT_HANDOFF = timedelta(minutes=325)       # hand over to the queued run at a quiet moment
HARD_HANDOFF = timedelta(minutes=342)       # job timeout is 358 min
TIME_KEYS = ("post", "close", "start", "paid", "finish", "first_seen", "last_open_at")


def now():
    return datetime.now(HK)


def log(message):
    print(f"{now():%H:%M:%S} {message}", flush=True)


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def upper(value):
    return str(value or "").upper()


def request(url, headers, data=None, method=None, timeout=10):
    with urlopen(Request(url, headers=headers, data=data, method=method), timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return None
    return json.loads(gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw)


def compact(query):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[_A-Za-z][_0-9A-Za-z]*|\\.\\.\\.|[^\\s,]', query)
    return "".join((" " if i and tokens[i-1][-1].isalnum() and token[0].isalnum() else "") + token
                   for i, token in enumerate(tokens))


def hkjc(query, args):
    url = ENDPOINT + "?" + urlencode({"query": compact(query),
                                      "variables": json.dumps(args, sort_keys=True, separators=(",", ":"))})
    payload = request(url, {"User-Agent": "Mozilla/5.0", "Origin": "https://bet.hkjc.com",
                            "Referer": "https://bet.hkjc.com/", "Content-Type": "application/json"}, timeout=8)
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("HKJC query rejected")
    return payload["data"]


def calendar(day):
    """Today's local meetings. HKJC ignores the date argument and serves the active meeting."""
    return [m for m in (hkjc(GATE, {"date": None, "venueCode": None})["raceMeetings"] or [])
            if m.get("date") == day and m.get("venueCode") in ("ST", "HV")
            and str(m.get("id", "")).startswith("MTG_" + day.replace("-", "") + "_")]


def odds_pools(day, venue):
    return hkjc(QUERY, {"date": day, "venueCode": venue, "raceNo": None,
                        "oddsTypes": ["QIN", "WIN"]})["raceMeetings"] or []


def expected_runners(race):
    numbers = set()
    for runner in race.get("runners") or []:
        if upper(runner.get("status")) in RUNNER_OUT or runner.get("standbyNo"):
            continue
        try:
            numbers.add(int(runner["no"]))
        except (KeyError, TypeError, ValueError):
            continue
    return numbers


def board(pool, race, captured):
    """A complete Quinella board, or None. Scratched horses ("SCR" odds) are left out."""
    nodes = {}
    for node in pool.get("oddsNodes") or []:
        pair = re.fullmatch(r"(\d{1,2})\s*[-,+/]\s*(\d{1,2})", str(node.get("combString")))
        if not pair:
            continue
        horses = sorted(map(int, pair.groups()))
        try:
            price = float(node.get("oddsValue"))
        except (ValueError, TypeError):
            continue
        if horses[0] <= 0 or horses[0] == horses[1] or not math.isfinite(price) or price <= 0:
            continue
        key = tuple(horses)
        if key in nodes:
            return None
        nodes[key] = price
    runners = sorted(set(itertools.chain.from_iterable(nodes)))
    if len(runners) < 2 or len(nodes) != math.comb(len(runners), 2):
        return None
    expected = expected_runners(race)
    return {"observed_at": captured.isoformat(), "source_odds_at": pool.get("oddsLastUpdateTime"),
            "sell_status": pool.get("sellStatus"), "pool_status": pool.get("status"),
            "runners_on_board": runners,
            "field_check": "matches_declared_runners" if not expected or set(runners) == expected
            else f"declared_runners={sorted(expected)}",
            "odds": {f"{a}-{b}": price for (a, b), price in sorted(nodes.items())}}


def pool_open(pool):
    return upper(pool.get("sellStatus")) == "START_SELL" and not settled(pool)


def settled(pool):
    status = upper(pool.get("status"))
    return status == "PAYOUT" or "REFUND" in status


def pools_by_race(meeting_id, pmpools):
    result = {}
    for pool in pmpools or []:
        legs = (pool.get("leg") or {}).get("races") or []
        kind = pool.get("oddsType")
        if len(legs) != 1 or kind not in ("QIN", "WIN"):
            continue
        number = int(legs[0])
        if pool.get("id") == f"{meeting_id}{kind}{number}":
            result[number, kind] = pool
    return result


class Recorder:
    def __init__(self, state=None):
        self.state = state or {}

    # ---- persistence for hand-over between runs ----
    def dump(self):
        out = {}
        for n, s in self.state.items():
            s = dict(s)
            for key in TIME_KEYS:
                if isinstance(s.get(key), datetime):
                    s[key] = s[key].isoformat()
            s.pop("board", None)
            s.pop("targets", None)
            out[str(n)] = s
        return out

    @classmethod
    def load(cls, data):
        state = {}
        for n, s in data.items():
            for key in TIME_KEYS:
                if isinstance(s.get(key), str):
                    s[key] = stamp(s[key])
            s["board"] = None
            state[int(n)] = s
        return cls(state)

    def observe(self, meeting, pmpools, captured):
        """Update race state from one poll. Returns human-readable transition messages."""
        events = []
        pools = pools_by_race(meeting["id"], pmpools)
        races = sorted(meeting["races"], key=lambda race: int(race["no"]))
        for race in races:
            n = int(race["no"])
            s = self.state.setdefault(n, {"points": {}, "missing": {}, "superseded": [],
                                          "suspensions": [], "first_seen": captured})
            qin = pools.get((n, "QIN"), {})
            win = pools.get((n, "WIN"), {})
            post = stamp(race.get("postTime"))
            status = upper(race.get("status"))
            if post:
                if s.get("post") and post != s["post"]:
                    events.append(f"R{n} post time changed {s['post']:%H:%M} -> {post:%H:%M}")
                s["post"] = post
            seen = (status, upper(qin.get("sellStatus")), upper(qin.get("status")), upper(win.get("status")))
            if seen != tuple(s.get("seen") or ()):
                events.append(f"R{n} race={seen[0]} qin_sell={seen[1]} qin_pool={seen[2]} win_pool={seen[3]}")
                s["seen"] = list(seen)

            if "late" not in s and "published" not in s:
                # A race already off when first seen cannot be captured honestly by this run.
                s["late"] = status in RACE_OFF or status in RACE_VOID or (
                    bool(qin) and not pool_open(qin) and bool(post) and captured >= post - EARLY_STOP)
                if s["late"]:
                    events.append(f"R{n} already off or closed when first observed")
            if status in RACE_VOID:
                s["void"] = status

            is_open = pool_open(qin)
            if is_open:
                s["seen_open"] = True
                if s.get("close") and not s.get("start"):
                    events.append(f"R{n} QIN selling again; previous stop-sell treated as a suspension")
                    s["suspensions"].append({"from": s["close"].isoformat(), "to": captured.isoformat()})
                    s.pop("close")
                    s.pop("closed_board", None)
                    nxt = self.state.get(n + 1)
                    if nxt and "published" not in nxt:
                        if nxt["points"].pop("before_rollover", None):
                            nxt["superseded"].append({"point": "before_rollover", "reason": "previous race reopened"})
            if status not in RACE_OFF and status not in RACE_VOID:
                s["seen_prestart"] = True
            if status not in RACE_RESULT:
                s["seen_unfinished"] = True
            if win and not settled(win):
                s["seen_unpaid"] = True

            if qin and not is_open and s.get("seen_open") and "close" not in s:
                if post and captured < post - EARLY_STOP and status not in RACE_OFF:
                    if not s.get("suspended_now"):
                        events.append(f"R{n} QIN stopped selling before post-2min; waiting (suspension?)")
                    s["suspended_now"] = True
                else:
                    s["close"] = captured
                    events.append(f"R{n} stop-sell observed")
            if is_open:
                s["suspended_now"] = False
            if "start" not in s and s.get("seen_prestart") and status in RACE_OFF:
                s["start"], s["start_anchor"] = captured, f"race_status_{status.lower()}"
                events.append(f"R{n} off (race status {status})")
            if "start" not in s and s.get("close") and captured >= s["close"] + START_CONFIRM and s.get("seen_open"):
                s["start"], s["start_anchor"] = s["close"], "qin_stop_sell"
                events.append(f"R{n} off assumed at stop-sell (race status unchanged)")
            if "paid" not in s and s.get("seen_unpaid") and win and settled(win):
                s["paid"] = captured
                events.append(f"R{n} WIN payout observed")
            if "finish" not in s and s.get("seen_unfinished") and status in RACE_RESULT:
                s["finish"] = captured
                events.append(f"R{n} result observed")

            current = board(qin, race, captured) if qin else None
            s["board"] = current
            if current and is_open:
                s["last_open"], s["last_open_at"] = current, captured
            if current and not is_open and s.get("close") and "closed_board" not in s \
                    and captured <= s["close"] + WINDOW:
                s["closed_board"] = current

        for index, race in enumerate(races):
            n = int(race["no"])
            s = self.state[n]
            if "published" in s or s.get("late") or s.get("void") or not s.get("post"):
                continue
            prev = self.state[int(races[index - 1]["no"])] if index else {}
            targets, anchors = self.targets(s, prev)
            s["targets"], s["anchors"] = targets, anchors
            qin = pools.get((n, "QIN"), {})
            current = s["board"]
            for name in OPEN_POINTS:
                target = targets[name]
                point = s["points"].get(name)
                if point and name in ("t5", "t3") and target and point["target_at"] != target.isoformat() \
                        and captured < target and "start" not in s:
                    s["superseded"].append({"point": name, "reason": "post time changed", "snapshot": point})
                    s["points"].pop(name)
                    events.append(f"R{n} {name} will be re-taken for new post time")
                if name in s["points"] or target is None or not target <= captured <= target + WINDOW:
                    continue
                if name == "after_rollover" and captured >= targets["t5"]:
                    continue
                if current and pool_open(qin):
                    s["points"][name] = {**current, "target_at": target.isoformat(), "basis": "open_board",
                                         **({"anchor": anchors[name]} if name in anchors else {})}
                    events.append(f"R{n} {name} captured (target {target:%H:%M:%S}, source odds {current['source_odds_at']})")
            start = s.get("start")
            if start and "after_start" not in s["points"]:
                closed = s.get("closed_board")
                if closed and s.get("close") and s["close"] <= stamp(closed["observed_at"]) <= start + WINDOW:
                    s["points"]["after_start"] = {**closed, "target_at": start.isoformat(),
                                                  "basis": "closed_board_after_stop_sell", "anchor": s["start_anchor"]}
                    events.append(f"R{n} after_start captured (source odds {closed['source_odds_at']})")
                elif start <= captured <= start + WINDOW and current and not pool_open(qin):
                    s["points"]["after_start"] = {**current, "target_at": start.isoformat(),
                                                  "basis": "closed_board_after_off", "anchor": s["start_anchor"]}
                    events.append(f"R{n} after_start captured (source odds {current['source_odds_at']})")
                elif captured > start + WINDOW:
                    cutoff = s.get("close") or start
                    last, at = s.get("last_open"), s.get("last_open_at")
                    if last and at and timedelta(0) <= cutoff - at <= FALLBACK_AGE:
                        s["points"]["after_start"] = {**last, "target_at": start.isoformat(),
                                                      "basis": "FALLBACK_last_open_board_before_stop_sell",
                                                      "fallback_age_seconds": round((cutoff - at).total_seconds()),
                                                      "anchor": s["start_anchor"]}
                        events.append(f"R{n} after_start used FALLBACK last open board")
                    s["after_start_done"] = True
            if "after_start" in s["points"]:
                s["after_start_done"] = True
        return events

    @staticmethod
    def targets(s, prev):
        post = s["post"]
        targets = {"before_rollover": prev.get("close"),
                   "after_rollover": None, "t5": post - timedelta(minutes=5), "t3": post - timedelta(minutes=3)}
        anchors = {}
        if prev.get("paid"):
            targets["after_rollover"], anchors["after_rollover"] = prev["paid"] + timedelta(minutes=2), "prev_win_payout_plus_2min"
        elif prev.get("finish"):
            targets["after_rollover"], anchors["after_rollover"] = prev["finish"] + timedelta(minutes=10), "FALLBACK_prev_result_plus_10min"
        elif prev.get("start"):
            targets["after_rollover"], anchors["after_rollover"] = prev["start"] + NO_RESULT_ANCHOR, "FALLBACK_prev_off_plus_14min_no_result_seen"
        return targets, anchors

    def ready(self, n, captured):
        s = self.state[n]
        if "published" in s:
            return False
        if s.get("late") or s.get("void"):
            return True
        return bool(s.get("after_start_done"))

    def missing_reason(self, n, name, s, prev):
        if s.get("void"):
            return f"race {s['void'].lower()}"
        if s.get("late"):
            return "recorder_not_running_before_race_off"
        if name in ("before_rollover", "after_rollover") and not prev:
            return "first_race"
        target = (s.get("targets") or {}).get(name)
        if name == "after_start":
            return "no_closed_board_after_off_and_no_recent_open_board" if s.get("start") else "off_not_observed"
        if target is None:
            return "previous_race_event_not_observed"
        if s["first_seen"] > target + WINDOW:
            return "recorder_not_running_at_target"
        if name == "after_rollover" and target >= s["targets"]["t5"]:
            return "collides_with_t5"
        return "no_valid_open_board_within_35s_of_target"

    def record(self, n, day, venue, meeting_id):
        s = self.state[n]
        ordered = sorted(self.state)
        prev = self.state[ordered[ordered.index(n) - 1]] if ordered.index(n) else {}
        points = {name: s["points"].get(name) for name in POINTS}
        missing = {name: self.missing_reason(n, name, s, prev) for name in POINTS if not points[name]}
        rows = []
        for pair in sorted(set().union(*(p["odds"] for p in points.values() if p)),
                           key=lambda c: tuple(map(int, c.split("-")))):
            prices = {name: p["odds"].get(pair) if p else None for name, p in points.items()}
            changes = {}
            for left, right in zip(POINTS, POINTS[1:]):
                a, b = prices[left], prices[right]
                changes[f"{left}_to_{right}"] = round(100 * (a - b) / a, 2) if a and b else None
            rows.append({"combination": pair, "odds": prices, "drop_pct": changes})
        iso = lambda t: t.isoformat() if isinstance(t, datetime) else None
        return {"schema": 2, "date": day, "venue": venue, "meeting_id": meeting_id, "race": n,
                "post_time": iso(s.get("post")),
                "events": {"stop_sell": iso(s.get("close")), "off": iso(s.get("start")),
                           "off_anchor": s.get("start_anchor"), "win_payout": iso(s.get("paid")),
                           "result": iso(s.get("finish")), "first_observed": iso(s.get("first_seen"))},
                "target_times": {k: iso(t) for k, t in (s.get("targets") or {}).items()} | {"after_start": iso(s.get("start"))},
                "points": points, "missing": missing, "superseded": s.get("superseded", []),
                "suspensions": s.get("suspensions", []), "combinations": rows}


# ---- private archive (GitHub Contents API) ----
class Archive:
    def __init__(self):
        self.repo = os.environ["PRIVATE_DATA_REPO"]
        self.token = os.environ["PRIVATE_DATA_TOKEN"]
        self.run = f"{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        self.ok_once = False

    def _call(self, method, path, body=None):
        url = f"https://api.github.com/repos/{self.repo}/contents/{quote(path)}"
        if method == "GET":
            url += "?ref=odds-data"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "Content-Type": "application/json", "User-Agent": "qin-recorder"}
        data = json.dumps(body).encode() if body is not None else None
        return request(url, headers, data=data, method=method, timeout=15)

    def listing(self, folder):
        try:
            return [item["name"] for item in self._call("GET", folder) or [] if isinstance(item, dict)]
        except HTTPError as error:
            if error.code == 404:
                return []
            raise

    def read(self, path):
        item = self._call("GET", path)
        return json.loads(base64.b64decode(item["content"]))

    def put(self, path, payload, message):
        """True when the file is stored (also when an earlier timed-out attempt already stored it)."""
        body = {"branch": "odds-data", "message": message,
                "content": base64.b64encode(json.dumps(payload, indent=2).encode()).decode()}
        try:
            self._call("PUT", path, body)
            self.ok_once = True
            return True
        except HTTPError as error:
            code = error.code
            if code == 422:
                try:
                    self._call("GET", path)
                    self.ok_once = True
                    return True
                except (OSError, ValueError):
                    pass
            if code in (401, 404) and not self.ok_once:
                raise SystemExit("Private destination rejected the write. Check token, repository and branch.") from None
            log(f"archive write failed (HTTP {code}); will retry")
        except (OSError, ValueError) as error:
            log(f"archive write failed ({type(error).__name__}); will retry")
        return False


def race_folder(day, venue):
    return f"qin-history/{day}_{venue}"


def archived_races(archive, day, venue):
    races = set()
    for name in archive.listing(race_folder(day, venue)):
        match = re.fullmatch(r"race-(\d{2})-.+\.json", name)
        if match:
            races.add(int(match.group(1)))
    return races


def load_handoff(archive, day, venue):
    folder = f"qin-handoff/{day}_{venue}"
    names = sorted((n for n in archive.listing(folder) if n.endswith(".json")),
                   key=lambda n: [int(x) for x in re.findall(r"\d+", n)])
    if not names:
        return None
    data = archive.read(f"{folder}/{names[-1]}")
    saved = stamp(data.get("saved_at"))
    if not saved or now() - saved > timedelta(minutes=20):
        log("Ignoring stale hand-over state.")
        return None
    return data


def quiet_moment(recorder, at):
    """True when no snapshot target or race event is due within the next 6 minutes."""
    for s in recorder.state.values():
        if "published" in s or s.get("late") or s.get("void"):
            continue
        post = s.get("post")
        if post and post - timedelta(minutes=12) <= at <= post + timedelta(minutes=3):
            return False
        target = (s.get("targets") or {}).get("after_rollover")
        if target and at - WINDOW <= target <= at + timedelta(minutes=6) and "after_rollover" not in s["points"]:
            return False
    return True


def main():
    started = now()
    day = started.date().isoformat()
    candidates = []
    for meeting in calendar(day):
        posts = [stamp(r.get("postTime")) for r in meeting["races"]]
        if meeting["races"] and all(posts):
            if min(posts) - timedelta(minutes=50) <= started <= max(posts) + timedelta(minutes=40) and not all(
                    upper(r.get("status")) in RACE_RESULT | RACE_VOID for r in meeting["races"]):
                candidates.append(meeting)
    if not candidates:
        print("No local meeting in the capture window.")
        return
    if len(candidates) != 1:
        raise SystemExit("Could not uniquely identify today's local meeting.")
    if not all(os.environ.get(key) for key in ("PRIVATE_DATA_REPO", "PRIVATE_DATA_TOKEN")):
        raise SystemExit("Configure the private destination before starting live collection.")
    meeting_id, venue = candidates[0]["id"], candidates[0]["venueCode"]
    total = len(candidates[0]["races"])
    archive = Archive()
    done, handoff = set(), None
    for attempt in range(3):
        try:
            done = archived_races(archive, day, venue)
            handoff = load_handoff(archive, day, venue)
            break
        except (OSError, ValueError, KeyError, TypeError) as error:
            log(f"Could not read the archive ({type(error).__name__}); attempt {attempt + 1}/3")
            time.sleep(5)
    log(f"Meeting {day} {venue}: {total} races; already archived: {sorted(done) or 'none'}")
    if len(done) >= total:
        print("All races already archived.")
        return
    recorder = Recorder.load(handoff["state"]) if handoff else Recorder()
    if handoff:
        log("Resumed hand-over state from the previous run.")
    for n in done:
        recorder.state.setdefault(n, {"points": {}, "missing": {}, "superseded": [], "suspensions": [],
                                      "first_seen": started})["published"] = "earlier run"
    healthy, failures, last_post = False, 0, None
    while True:
        tick = time.monotonic()
        try:
            meetings = [m for m in calendar(day) if m["venueCode"] == venue]
            pools = odds_pools(day, venue)
            if len(meetings) != 1 or len(pools) != 1 or meetings[0]["id"] != meeting_id:
                raise ValueError("meeting not uniquely identified")
            meeting = meetings[0]
            captured = now()
            for message in recorder.observe(meeting, pools[0]["pmPools"], captured):
                log(message)
            failures = 0
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            failures += 1
            if failures == 1 or failures % 8 == 0:
                log(f"HKJC poll failed x{failures} ({type(error).__name__}: {str(error)[:80]})")
            time.sleep(POLL)
            if now() - started > HARD_HANDOFF:
                break
            continue
        last_post = max(s["post"] for s in recorder.state.values() if s.get("post"))
        if not healthy and any(s.get("board") for s in recorder.state.values()):
            healthy = True
            log("First complete Quinella board observed.")
        for n in sorted(recorder.state):
            if recorder.ready(n, captured):
                try:
                    record = recorder.record(n, day, venue, meeting_id)
                except Exception as error:  # keep recording the other races
                    log(f"Race {n} record could not be built ({type(error).__name__}); will retry")
                    continue
                path = f"{race_folder(day, venue)}/race-{n:02}-{archive.run}.json"
                if archive.put(path, record, f"Archive Quinella R{n}"):
                    recorder.state[n]["published"] = archive.run
                    got = [k for k in POINTS if record["points"][k]]
                    log(f"Race {n} archived: {len(got)}/5 points {got}; missing {record['missing'] or 'none'}")
        if all("published" in recorder.state.get(int(r["no"]), {}) for r in meeting["races"]):
            log("All races archived.")
            return
        elapsed = now() - started
        if elapsed > HARD_HANDOFF or (elapsed > SOFT_HANDOFF and quiet_moment(recorder, captured)):
            break
        if captured > last_post + timedelta(minutes=40):
            for n in sorted(recorder.state):
                s = recorder.state[n]
                if "published" not in s:
                    s["after_start_done"] = True
                    record = recorder.record(n, day, venue, meeting_id)
                    if archive.put(f"{race_folder(day, venue)}/race-{n:02}-{archive.run}.json", record,
                                   f"Archive Quinella R{n} (incomplete)"):
                        s["published"] = archive.run
                        log(f"Race {n} archived incomplete; missing {record['missing']}")
            raise SystemExit("Meeting window ended before every race completed.")
        time.sleep(max(1, POLL - (time.monotonic() - tick)))
    state = {"saved_at": now().isoformat(), "meeting_id": meeting_id, "state": recorder.dump()}
    for _ in range(5):
        if archive.put(f"qin-handoff/{day}_{venue}/state-{archive.run}.json", state, "Recorder hand-over state"):
            log("Job time limit near: state handed over to the next queued run.")
            return
        time.sleep(5)
    raise SystemExit("Could not save hand-over state.")


def source_check():
    """Checks the live HKJC source. HKJC serves only the current/next meeting, never history."""
    meetings = hkjc(GATE, {"date": None, "venueCode": None})["raceMeetings"] or []
    if len(meetings) != 1:
        raise SystemExit(f"HKJC calendar returned {len(meetings)} meetings.")
    meeting = meetings[0]
    pools = hkjc(QUERY, {"date": meeting["date"], "venueCode": meeting["venueCode"], "raceNo": None,
                         "oddsTypes": ["QIN", "WIN"]})["raceMeetings"] or []
    if len(pools) != 1:
        raise SystemExit("HKJC odds query did not return exactly one meeting.")
    by_race = pools_by_race(meeting["id"], pools[0]["pmPools"])
    print(f"HKJC active meeting {meeting['id']} ({meeting['date']} {meeting['venueCode']}), "
          f"{len(meeting['races'])} races. This source has no historical boards.")
    bad = 0
    for race in sorted(meeting["races"], key=lambda r: int(r["no"])):
        n = int(race["no"])
        qin = by_race.get((n, "QIN"))
        result = board(qin, race, now()) if qin else None
        if not result:
            bad += 1
        print(f"  R{n}: post {race.get('postTime', '')[11:16]} race={race.get('status')} "
              f"QIN={'missing' if not qin else qin.get('sellStatus')} "
              f"board={'complete ' + str(len(result['odds'])) + ' combinations, ' + result['field_check'] if result else 'NOT COMPLETE'}")
    if bad:
        raise SystemExit(f"{bad} race(s) without a complete Quinella board.")


if __name__ == "__main__":
    if os.environ.get("QIN_SOURCE_TEST") == "true":
        source_check()
    elif os.environ.get("QIN_WRITE_TEST") == "true":
        try:
            archive = Archive()
            stored = archive.put(f"qin-diagnostics/write-test-{archive.run}.json",
                                 {"date": now().date().isoformat(), "purpose": "private archive write test"},
                                 "Archive write test")
            archive.listing("qin-diagnostics")
        except (OSError, KeyError, ValueError):
            raise SystemExit("Private archive write test failed.") from None
        if not stored:
            raise SystemExit("Private archive write test failed.")
        print("Private archive write and read test passed.")
    else:
        main()
