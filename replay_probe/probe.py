"""Probe: open the public HKJC replay player, log media requests, save screenshots.
Public page only. No login, no cookies, nothing private."""
import json, sys, time
from playwright.sync_api import sync_playwright

url, out = sys.argv[1], sys.argv[2]
shots, gap = int(sys.argv[3]), int(sys.argv[4])
reqs, info = [], {"url": url, "frames": []}

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    pg = b.new_page(viewport={"width": 1280, "height": 720})
    pg.on("request", lambda r: reqs.append(r.url) if any(k in r.url.lower() for k in (".m3u8", ".mp4", ".ts", ".mpd", "video", "stream")) else None)
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        info["goto_error"] = repr(e)
    time.sleep(8)
    for i in range(shots):
        try:
            pg.evaluate("document.querySelectorAll('video').forEach(v=>{v.muted=true;v.play().catch(()=>{})})")
            st = pg.evaluate("Array.from(document.querySelectorAll('video')).map(v=>({t:v.currentTime,rs:v.readyState,w:v.videoWidth,h:v.videoHeight,paused:v.paused,src:(v.currentSrc||'').slice(0,200)}))")
        except Exception as e:
            st = repr(e)
        name = f"{out}/frame_{i:02d}.png"
        pg.screenshot(path=name)
        info["frames"].append({"file": name, "video": st})
        time.sleep(gap)
    info["title"] = pg.title()
    b.close()

info["media_requests"] = sorted(set(reqs))[:200]
json.dump(info, open(f"{out}/probe.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps(info, ensure_ascii=False)[:3000])
