"""Record the public 66888 W/P water indices of every race of today's meeting while it is running.

Points per race (minutes relative to the published post time):
  t10  10 min before   t5  5 min before   t2  2 min before   after_start  1 min after the off
66888 clears the values of a finished race, so this is the only way to keep them. Every point is the
page as displayed at capture time; a point that could not be read is stored with its status, never
filled in. One JSON per race is written to the private odds-data branch under indices-live/.

Reuses the meeting calendar, clock and private archive writer of recorder.py. Public rendered page only:
no login, no private feed, no challenge handling; robots.txt is checked first (fail closed) and a
verification wall stops the run.
"""
import os
import re
import sys
import time
from datetime import timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

import recorder as rec
from recorder import log, now, stamp, upper

UA = "HKJCOddsPersonalReport"
POINTS = {"t10": -10.0, "t5": -5.0, "t2": -2.0, "after_start": 1.0}   # minutes relative to post time
LATE = timedelta(seconds=75)         # a point may be read up to this long after its target
OPEN_LEAD = timedelta(minutes=14)    # start reading this long before the first post time
MAX_WAIT = timedelta(minutes=330)    # a job that is only waiting gives up after this
GRACE = timedelta(minutes=35)        # publish what exists this long after the last post time
CALENDAR_EVERY = 45                  # seconds between meeting calendar refreshes
BLOCK = ("verify you are human", "checking your browser", "access denied", "unusual traffic", "驗證您是人類")
FOLDER = "indices-live"


def parse_indices(html):
    """Rows of the 66888 water-index table: {horse_no: {name, win_index, place_index}} (numeric values only)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    for row in soup.select("#tb-rank-wp-q tr[data-horse-no]"):
        horse = row.get("data-horse-no", "")
        name = row.select_one(".horse-name")
        if not horse.isdigit() or not name:
            continue
        values = []
        for selector in (".rank-index-win-value", ".rank-index-place-value"):
            el = row.select_one(selector)
            text = el.get_text(strip=True) if el else ""
            values.append(float(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else None)
        if any(v is not None for v in values):
            result[horse] = {"name": name.get_text(strip=True), "win_index": values[0], "place_index": values[1]}
    return result


def targets(post):
    """{point: target time} for a race with the given post time."""
    return {name: post + timedelta(minutes=minutes) for name, minutes in POINTS.items()}


def next_point(state, at):
    """The earliest (target, race, point) that is due now (target <= at <= target+LATE) and not yet taken,
    plus the earliest future target (or None). Points whose window passed untaken are marked missed."""
    due, future = None, None
    for n, s in sorted(state.items()):
        if s.get("published") or s.get("post") is None or s.get("over"):
            continue
        for name, target in sorted(targets(s["post"]).items(), key=lambda kv: kv[1]):
            if name in s["points"]:
                continue
            if at > target + LATE:
                s["points"][name] = {"status": "missed", "target_at": target.isoformat(timespec="seconds"),
                                     "note": "capture window passed before the page could be read"}
            elif at >= target:
                if due is None or target < due[0]:
                    due = (target, n, name)
            elif future is None or target < future:
                future = target
    return due, future


def race_is_over(state_item, at):
    return state_item.get("over") or (state_item.get("post") is not None and at > state_item["post"] + timedelta(minutes=30))


def race_complete(state_item):
    return all(name in state_item["points"] for name in POINTS)


def robots_ok(day, venue):
    parser = RobotFileParser()
    try:
        with urlopen(Request("https://66888.hk/robots.txt", headers={"User-Agent": UA}), timeout=15) as response:
            parser.parse(response.read().decode("utf-8", "replace").splitlines())
    except HTTPError as error:
        if error.code != 404:
            return False
        parser.parse([])
    except OSError:
        return False
    return parser.can_fetch(UA, f"/raceid/{day.replace('-', '')}-{venue}-01")


class Reader:
    def __init__(self):
        self.driver = None

    def start(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--window-size=1920,1080", "--lang=zh-HK"):
            options.add_argument(arg)
        options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")
        self.driver = webdriver.Chrome(options=options)

    def stop(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def read(self, day, venue, race):
        """Return (status, rows). Status: ok, no_values, no_data, verification_wall, error."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        url = f"https://66888.hk/raceid/{day.replace('-', '')}-{venue}-{race:02d}"
        try:
            if self.driver is None:
                self.start()
            d = self.driver
            d.get(url)
            blocked = lambda: any(x in d.find_element(By.TAG_NAME, "body").text.lower() for x in BLOCK)
            if blocked():
                return "verification_wall", []
            try:
                WebDriverWait(d, 20).until(lambda x: day in x.find_element(By.ID, "meetingDateTrigger").text)
            except Exception:
                return ("verification_wall" if blocked() else "no_data"), []
            try:
                WebDriverWait(d, 12).until(lambda x: len(parse_indices(x.page_source)) > 0)
            except Exception:
                rows = len(d.find_elements(By.CSS_SELECTOR, "tr[data-horse-no]"))
                return ("no_values" if rows else "no_data"), []
            if blocked():
                return "verification_wall", []
            parsed = parse_indices(d.page_source)
            return "ok", [{"horse_no": h, "name": v["name"], "win_index": v["win_index"], "place_index": v["place_index"]}
                          for h, v in sorted(parsed.items(), key=lambda kv: int(kv[0]))]
        except Exception as error:      # browser crash etc.: restart next time
            self.stop()
            log(f"66888 read failed R{race}: {type(error).__name__}")
            return "error", []


def build_record(day, venue, meeting_id, n, s):
    return {"schema": 1, "phase": "in_meeting", "date": day, "venue": venue, "meeting_id": meeting_id, "race": n,
            "post_time": s["post"].isoformat(timespec="seconds") if s.get("post") else None,
            "points": s["points"], "source": "https://66888.hk/ (public rendered page)",
            "note": "Values as displayed at capture time. Missing points keep their status; nothing is back-filled."}


def archived_races(archive, day, venue):
    done = set()
    for name in archive.listing(f"{FOLDER}/{day}_{venue}"):
        m = re.match(r"race-(\d+)-", name)
        if m:
            done.add(int(m.group(1)))
    return done


def refresh(state, meeting, at):
    """Update post times and race status from the calendar; a postponed race moves its targets."""
    for race in meeting["races"]:
        n = int(race["no"])
        s = state.setdefault(n, {"points": {}, "post": None})
        post = stamp(race.get("postTime"))
        if post:
            s["post"] = post
        status = upper(race.get("status"))
        if status in rec.RACE_VOID or status in rec.RACE_RESULT:
            s["over"] = True


def main():
    started = now()
    day = started.date().isoformat()
    while True:
        found = rec.todays_meetings(day, now())
        if not found:
            print("No local meeting in the capture window.")
            return 0
        if len(found) != 1:
            raise SystemExit("Could not uniquely identify today's local meeting.")
        first_post = min(stamp(r["postTime"]) for r in found[0][0]["races"])
        opens = first_post - OPEN_LEAD
        if now() >= opens:
            break
        until = min(opens, started + MAX_WAIT)
        log(f"Waiting for the meeting; reading starts at {opens:%H:%M}.")
        while now() < until:
            time.sleep(min(300, max(1, (until - now()).total_seconds())))
        if now() < opens:
            raise SystemExit("Waited as long as one job can; trigger this workflow closer to the first race.")
    meeting = found[0][0]
    meeting_id, venue = meeting["id"], meeting["venueCode"]
    if not all(os.environ.get(k) for k in ("PRIVATE_DATA_REPO", "PRIVATE_DATA_TOKEN")):
        raise SystemExit("Configure the private destination before starting live collection.")
    if not robots_ok(day, venue):
        raise SystemExit("66888 robots.txt does not allow this or could not be verified; not reading.")
    archive = rec.Archive()
    done = archived_races(archive, day, venue)
    state = {}
    refresh(state, meeting, now())
    for n in done:
        state[n]["published"] = "earlier run"
    log(f"Meeting {day} {venue}: {len(state)} races; already archived: {sorted(done) or 'none'}")
    reader = Reader()
    last_calendar = now()
    wall = False
    try:
        while True:
            at = now()
            if (at - last_calendar).total_seconds() >= CALENDAR_EVERY:
                try:
                    current = [m for m in rec.calendar(day) if m["id"] == meeting_id]
                    if len(current) == 1:
                        meeting = current[0]
                        refresh(state, meeting, at)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                last_calendar = at
            due, future = next_point(state, at)
            if due and not wall:
                target, n, name = due
                status, rows = reader.read(day, venue, n)
                taken = now()
                state[n]["points"][name] = {"status": status, "target_at": target.isoformat(timespec="seconds"),
                                            "captured_at": taken.isoformat(timespec="seconds"),
                                            "seconds_after_target": round((taken - target).total_seconds(), 1), "rows": rows}
                log(f"R{n} {name}: {status} ({len(rows)} runners, {(taken - target).total_seconds():.0f}s after target)")
                if status == "verification_wall":
                    wall = True
                    log("Verification wall: stopping all 66888 reads.")
                time.sleep(1.5)
            else:
                nap = 1.0 if future is None else min(5.0, max(0.2, (future - now()).total_seconds()))
                time.sleep(nap)
            at = now()
            for n, s in sorted(state.items()):
                if s.get("published"):
                    continue
                finished = race_complete(s) or (s.get("over") and at > (s["post"] or at) + timedelta(minutes=3)) or race_is_over(s, at) or wall
                if finished:
                    for name in POINTS:
                        s["points"].setdefault(name, {"status": "missed", "note": "race over before the point was read"})
                    path = f"{FOLDER}/{day}_{venue}/race-{n:02}-{archive.run}.json"
                    if archive.put(path, build_record(day, venue, meeting_id, n, s), f"Archive 66888 indices R{n}"):
                        s["published"] = archive.run
                        got = [k for k, v in s["points"].items() if v.get("status") == "ok"]
                        log(f"Race {n} archived: {len(got)}/{len(POINTS)} points ok {got}")
            if all(s.get("published") for s in state.values()):
                log("All races archived.")
                return 3 if wall else 0
            last_post = max(s["post"] for s in state.values() if s.get("post"))
            if at > last_post + GRACE:
                for n, s in state.items():
                    if not s.get("published"):
                        s["over"] = True
                if at > last_post + GRACE + timedelta(minutes=5):
                    raise SystemExit("Meeting window ended before every race could be archived.")
    finally:
        reader.stop()


def probe():
    """Read race 1 of the active meeting once and report the status only (no archive write)."""
    meetings = rec.hkjc(rec.GATE, {"date": None, "venueCode": None})["raceMeetings"] or []
    meetings = [m for m in meetings if m.get("venueCode") in ("ST", "HV")]
    if not meetings:
        print("No active local meeting.")
        return 0
    m = meetings[0]
    day, venue = m["date"], m["venueCode"]
    print("robots ok:", robots_ok(day, venue))
    reader = Reader()
    try:
        status, rows = reader.read(day, venue, 1)
    finally:
        reader.stop()
    print(f"probe {day} {venue} R1: {status}, {len(rows)} runners")
    return 0


def write_test():
    archive = rec.Archive()
    ok = archive.put(f"qin-diagnostics/indices-write-test-{archive.run}.json", {"test": "indices recorder write", "at": now().isoformat()}, "Indices recorder write test")
    print("write test:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if os.environ.get("INDICES_PROBE") == "true":
        sys.exit(probe())
    if os.environ.get("INDICES_WRITE_TEST") == "true":
        sys.exit(write_test())
    sys.exit(main())
