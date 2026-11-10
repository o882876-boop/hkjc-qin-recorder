"""Capture timestamped HKJC Quinella boards and publish per-race records privately."""
import base64
import gzip
import itertools
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")
ENDPOINT = "https://info.cld.hkjc.com/graphql/base-get/"
QUERY = "\n      query sp4e_racing_pmPool($date: String, $venueCode: String, $oddsTypes: [OddsType], $raceNo: Int) {\n          raceMeetings(date: $date, venueCode: $venueCode)\n          {\n            pmPools(oddsTypes: $oddsTypes, raceNo: $raceNo) {\n              id\n              status\n              sellStatus\n              oddsType\n              lastUpdateTime\n              oddsLastUpdateTime\n              guarantee\n              minTicketCost\n              name_en\n              name_ch\n              leg {\n                number\n                races\n              }\n              cWinSelections {\n                composite\n                name_ch\n                name_en\n                starters\n              }\n              oddsNodes {\n                combString\n                oddsValue\n                hotFavourite\n                oddsDropValue\n                bankerOdds {\n                  combString\n                  oddsValue\n                }\n              }\n            }\n          }\n      }\n\n"
GATE = "\n        \n        \n        query raceMeetings($date: String, $venueCode: String) {\n            timeOffset {\n              rc\n            }\n            activeMeetings : raceMeetings\n            {\n              id\n              venueCode\n              date\n              status\n              races {\n                no\n                postTime\n                status\n                wageringFieldSize\n              }\n              poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n                status\n              }\n            }\n            raceMeetings(date: $date, venueCode: $venueCode)\n            {\n              id\n              status\n              venueCode\n              date\n              totalNumberOfRace\n              currentNumberOfRace\n              dateOfWeek\n              meetingType\n              totalInvestment\n              country {\n                code\n                namech\n                nameen\n                seq\n              }\n              races {\n                ...raceFragment\n                runners {\n                    id\n                    no\n                    standbyNo\n                    status\n                    name_ch\n                    name_en\n                    horse {\n                      id\n                      code\n                    }\n                    color\n                    barrierDrawNumber\n                    handicapWeight\n                    currentWeight\n                    currentRating\n                    internationalRating\n                    gearInfo\n                    racingColorFileName\n                    allowance\n                    trainerPreference\n                    last6run\n                    saddleClothNo\n                    trumpCard\n                    priority\n                    finalPosition\n                    deadHeat\n                    winOdds\n                    jockey {\n                      code\n                      name_en\n                      name_ch\n                    }\n                    trainer {\n                      code\n                      name_en\n                      name_ch\n                    }\n                }\n              }\n              obSt: pmPools(oddsTypes: [WIN, PLA]) {\n                leg {\n                  races\n                }\n                oddsType\n                comingleStatus\n              }\n              poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n                id\n                leg {\n                  number\n                  races\n                }\n                status\n                sellStatus\n                oddsType\n                investment\n                mergedPoolId\n                lastUpdateTime\n              }\n              ...racingBlockFragment\n              pmPools(oddsTypes: []) {\n                id\n              }\n              jkcInstNo : foPools(oddsTypes: [JKC], filters: [\"top\"]) {\n                instNo\n              }\n              tncInstNo : foPools(oddsTypes: [TNC], filters: [\"top\"]) {\n                instNo\n              }\n            }\n        }\n    \nfragment raceFragment on Race {\n    id\n    no\n    status\n    raceName_en\n    raceName_ch\n    postTime\n    country_en\n    country_ch\n    distance\n    wageringFieldSize\n    go_en\n    go_ch\n    ratingType\n    raceTrack {\n      description_en\n      description_ch\n    }\n    raceCourse {\n      description_en\n      description_ch\n      displayCode\n    }\n    claCode\n    raceClass_en\n    raceClass_ch\n    judgeSigns {\n      value_en\n    }\n  }\nfragment racingBlockFragment on RaceMeeting {\n    jpEsts: pmPools(oddsTypes: [WIN,PLA,TCE,TRI,FF,QTT,DT,TT,SixUP], filters: [\"jackpot\", \"estimatedDividend\"]) {\n      leg {\n        number\n        races\n      }\n      oddsType\n      jackpot\n      estimatedDividend\n      mergedPoolId\n    }\n    poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n      id\n      leg {\n        races\n      }\n    }\n    penetrometerReadings(filters:[\"first\"]) {\n      reading\n      readingTime\n    }\n    hammerReadings(filters:[\"first\"]) {\n      reading\n      readingTime\n    }\n    changeHistories(filters:[\"top3\"]) {\n      type\n      time\n      raceNo\n      runnerNo\n      horseName_ch\n      horseName_en\n      jockeyName_ch\n      jockeyName_en\n      scratchHorseName_ch\n      scratchHorseName_en\n      handicapWeight\n      scrResvIndicator\n    }\n  }\n\n"
POINTS = ("before_rollover", "after_rollover", "t5", "t3", "after_start")
CLOSED = {"STOP_SELL", "CLOSE", "CLOSED"}
OPEN = {"START_SELL"}
STARTED = {"RUNNING", "FINISHED", "RESULT"}
PAID = {"PAYOUT"}
WINDOW = timedelta(seconds=35)


def now():
    return datetime.now(HK)


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def request(url, headers, data=None):
    with urlopen(Request(url, headers=headers, data=data), timeout=8) as response:
        raw = response.read()
    return json.loads(gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw)


def market(day, venue=None, *, race_no=None):
    query = QUERY if venue else GATE
    args = {"date": day if venue else None, "venueCode": venue}
    if venue:
        args.update(raceNo=race_no, oddsTypes=["QIN", "WIN"])
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[_A-Za-z][_0-9A-Za-z]*|\\.\\.\\.|[^\\s,]', query)
    compact = "".join((" " if i and tokens[i-1][-1].isalnum() and token[0].isalnum() else "") + token
                      for i, token in enumerate(tokens))
    url = ENDPOINT + "?" + urlencode({"query": compact, "variables": json.dumps(args, sort_keys=True, separators=(",", ":"))})
    payload = request(url, {"User-Agent": "Mozilla/5.0", "Origin": "https://bet.hkjc.com",
                            "Referer": "https://bet.hkjc.com/", "Content-Type": "application/json"})
    if payload.get("errors"):
        raise ValueError("HKJC query rejected")
    if venue:
        return payload["data"]["raceMeetings"] or []
    return [m for m in (payload["data"]["raceMeetings"] or []) if m["date"] == day
            and m["venueCode"] in ("ST", "HV")
            and m["id"].startswith("MTG_" + day.replace("-", "") + "_")
            and (not venue or m["venueCode"] == venue)]


def board(pool, size, captured):
    nodes = {}
    for node in pool.get("oddsNodes") or []:
        pair = re.fullmatch(r"(\d{1,2})\s*[-,+/]\s*(\d{1,2})", str(node.get("combString")))
        if not pair:
            continue
        horses = sorted(map(int, pair.groups()))
        try:
            price = float(node["oddsValue"])
        except (ValueError, TypeError):
            continue
        if horses[0] <= 0 or horses[0] == horses[1] or not math.isfinite(price) or price <= 0:
            continue
        key = tuple(horses)
        if key in nodes:
            return None
        nodes[key] = price
    runners = sorted(set(itertools.chain.from_iterable(nodes)))
    if not size or size < 2 or len(runners) != size or len(nodes) != math.comb(size, 2):
        return None
    return {"observed_at": captured.isoformat(), "source_odds_at": pool.get("oddsLastUpdateTime"),
            "sell_status": pool.get("sellStatus"), "pool_status": pool.get("status"),
            "odds": {f"{a}-{b}": price for (a, b), price in sorted(nodes.items())}}


def is_closed(pool):
    return pool.get("sellStatus") in CLOSED or pool.get("status") in PAID


def pools_by_race(meeting):
    result = {}
    for pool in meeting.get("pmPools", []):
        legs = (pool.get("leg") or {}).get("races") or []
        kind = pool.get("oddsType")
        if len(legs) != 1 or kind not in ("QIN", "WIN"):
            continue
        number = int(legs[0])
        if pool.get("id") == f"{meeting['id']}{kind}{number}":
            result[number, kind] = pool
    return result


class Recorder:
    def __init__(self):
        self.state = {}

    def observe(self, meeting, captured):
        pools = pools_by_race(meeting)
        races = sorted(meeting["races"], key=lambda race: int(race["no"]))
        for race in races:
            n = int(race["no"])
            state = self.state.setdefault(n, {"points": {}, "last_open": None, "seen_open": False})
            qin = pools.get((n, "QIN"), {})
            win = pools.get((n, "WIN"), {})
            post = stamp(race["postTime"])
            if not post:
                continue
            state["post"] = post
            state["status"] = race["status"]
            closed = is_closed(qin)
            if qin.get("sellStatus") in OPEN and not closed:
                state["seen_open"] = True
            if closed and state["seen_open"] and "close" not in state:
                state["close"] = captured
            if win.get("status") in PAID and "paid" not in state:
                state["paid"] = captured
            if race["status"] in STARTED and "start" not in state:
                state["start"] = captured
            if race["status"] in {"FINISHED", "RESULT"} and "finish" not in state:
                state["finish"] = captured
            current = board(qin, race.get("wageringFieldSize"), captured)
            if current and qin.get("sellStatus") in OPEN and not closed:
                state["last_open"] = current
            state["board"] = current

        for index, race in enumerate(races):
            n = int(race["no"])
            state = self.state[n]
            if "post" not in state:
                continue
            points = state["points"]
            post = state["post"]
            previous = self.state[int(races[index - 1]["no"])] if index else {}
            paid = previous.get("paid")
            finish = previous.get("finish")
            after = paid + timedelta(minutes=2) if paid else finish + timedelta(minutes=10) if finish else None
            targets = {"before_rollover": previous.get("close"), "after_rollover": after,
                       "t5": post - timedelta(minutes=5), "t3": post - timedelta(minutes=3),
                       "after_start": state.get("start")}
            state["targets"] = targets
            current = state["board"]
            for name, target in targets.items():
                if name in points or target is None or not target <= captured <= target + WINDOW:
                    continue
                if name == "after_rollover" and captured >= targets["t5"]:
                    continue
                if name == "after_start":
                    if current and is_closed(pools.get((n, "QIN"), {})):
                        points[name] = {**current, "target_at": target.isoformat(),
                                        "basis": "closed_board_observed_after_race_status"}
                elif current and current["sell_status"] in OPEN and not is_closed(pools.get((n, "QIN"), {})):
                    points[name] = {**current, "target_at": target.isoformat(), "basis": "open_board"}
            # Allow a brief grace period for a closed board to appear before using a fallback.
            event = state.get("start") or state.get("close")
            grace = WINDOW if state.get("start") else timedelta(minutes=3)
            if event and (points.get("after_start") or captured >= event + grace):
                state["ready"] = True
                if "after_start" not in points and state["last_open"]:
                    last = state["last_open"]
                    cutoff = state.get("close") or event
                    if timedelta(0) <= cutoff - stamp(last["observed_at"]) <= WINDOW:
                        points["after_start"] = {**last, "target_at": event.isoformat(),
                                                 "basis": "last_open_board_before_close_or_start"}

    def record(self, n, day, venue):
        state = self.state[n]
        points = {name: state["points"].get(name) for name in POINTS}
        rows = []
        for pair in sorted(set().union(*(p["odds"] for p in points.values() if p))):
            prices = {name: p["odds"].get(pair) if p else None for name, p in points.items()}
            changes = {}
            for left, right in zip(POINTS, POINTS[1:]):
                a, b = prices[left], prices[right]
                changes[f"{left}_to_{right}"] = round(100 * (a - b) / a, 2) if a and b else None
            rows.append({"combination": pair, "odds": prices, "drop_pct": changes})
        return {"schema": 1, "date": day, "venue": venue, "race": n,
                "target_times": {k: t.isoformat() if t else None for k, t in state["targets"].items()},
                "points": points, "combinations": rows}


def publish(record, *, smoke_test=False):
    repo = os.environ["PRIVATE_DATA_REPO"]
    token = os.environ["PRIVATE_DATA_TOKEN"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    path = f"qin-history/{record['date']}_{record['venue']}/race-{record['race']:02}-{run_id}-{attempt}.json"
    if smoke_test:
        path = f"qin-diagnostics/write-test-{run_id}-{attempt}.json"
    body = {"branch": "odds-data", "message": "Archive Quinella snapshots",
            "content": base64.b64encode(json.dumps(record, indent=2).encode()).decode()}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    req = Request(url, data=json.dumps(body).encode(), method="PUT", headers=headers)
    with urlopen(req, timeout=10):
        pass


def main():
    day = now().date().isoformat()
    candidates = []
    for meeting in market(day):
        races = sorted(meeting["races"], key=lambda r: int(r["no"]))
        if races and (first := stamp(races[0]["postTime"])) and (last := stamp(races[-1]["postTime"])):
            if first - timedelta(minutes=55) <= now() <= last + timedelta(minutes=10) and not all(
                    race["status"] in {"RESULT", "VOID", "CANCELLED"} for race in races):
                candidates.append((meeting["venueCode"], last))
    if not candidates:
        print("No local meeting in the capture window.")
        return
    if len(candidates) != 1:
        raise SystemExit("Could not uniquely identify today's local meeting.")
    if not all(os.environ.get(key) for key in ("PRIVATE_DATA_REPO", "PRIVATE_DATA_TOKEN")):
        raise SystemExit("Configure the private destination before starting live collection.")
    venue, last = candidates[0]
    recorder = Recorder()
    saved = set()
    healthy = False
    while now() <= last + timedelta(minutes=25):
        tick = time.monotonic()
        try:
            calendars = [m for m in market(day) if m["venueCode"] == venue]
            pools = market(day, venue)
            if len(calendars) != 1 or len(pools) != 1:
                raise ValueError("Meeting not uniquely identified")
            meeting = {**calendars[0], "pmPools": pools[0]["pmPools"]}
            recorder.observe(meeting, now())
        except (OSError, ValueError, KeyError, TypeError):
            time.sleep(8)
            continue
        if not healthy and any(s.get("board") for s in recorder.state.values()):
            healthy = True
            print("First complete Quinella board observed.", flush=True)
        for n, state in recorder.state.items():
            if state.get("ready") and n not in saved:
                try:
                    publish(recorder.record(n, day, venue))
                except OSError as error:
                    # Do not leak response bodies, repository URLs, or credentials in public logs.
                    if getattr(error, "code", None) in (401, 403, 404, 422):
                        raise SystemExit("Private destination rejected the write. Check permissions and branch.") from None
                    continue
                saved.add(n)
                print(f"Race {n} archived.", flush=True)
        if len(saved) == len(meeting["races"]):
            if not healthy:
                raise SystemExit("No complete Quinella board observed.")
            return
        time.sleep(max(1, 8 - (time.monotonic() - tick)))
    raise SystemExit("Meeting window ended with one or more unpublished race records.")


if __name__ == "__main__":
    if os.environ.get("QIN_SOURCE_TEST") == "true":
        meetings = market("2026-11-08", "ST")
        pools = meetings[0]["pmPools"] if len(meetings) == 1 else []
        boards = [p for p in pools if p["oddsType"] == "QIN" and p["oddsNodes"]]
        if not boards:
            raise SystemExit("HKJC source returned no historical Quinella boards.")
        print(f"HKJC source returned {len(boards)} historical Quinella boards.")
    elif os.environ.get("QIN_WRITE_TEST") == "true":
        try:
            publish({"date": now().date().isoformat(), "venue": "TEST", "race": 0,
                     "purpose": "private archive write test"}, smoke_test=True)
        except (OSError, KeyError):
            raise SystemExit("Private archive write test failed.") from None
        print("Private archive write test passed.")
    else:
        main()
