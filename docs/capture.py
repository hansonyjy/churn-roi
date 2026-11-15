"""Drive headless Chrome over the DevTools protocol to capture README media
from the running app: the hero GIF of the sliders and the save list screenshot.

Serve the app first (python -m http.server 8765 --directory app/static), then:
    python docs/capture.py
Needs Google Chrome, Pillow, and websocket-client (dev only, not serving deps)."""

import base64, io, json, subprocess, sys, tempfile, time, urllib.request
import websocket
from PIL import Image

APP = "http://localhost:8765/"
from pathlib import Path
OUT = str(Path(__file__).resolve().parent / "img")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333

prof = tempfile.mkdtemp()
proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                         f"--user-data-dir={prof}", "--hide-scrollbars", "--no-first-run",
                         "--disable-gpu", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try:
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
        page = next(t for t in tabs if t["type"] == "page")
        break
    except Exception:
        time.sleep(0.2)
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60)
_id = 0
def cdp(method, **params):
    global _id
    _id += 1
    ws.send(json.dumps({"id": _id, "method": method, "params": params}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            if "error" in msg:
                raise RuntimeError(msg["error"])
            return msg.get("result", {})

def js(expr):
    r = cdp("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
    return r.get("result", {}).get("value")

def viewport(w, h, scale, mobile=False):
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale, mobile=mobile)

def load():
    cdp("Page.enable")
    cdp("Page.navigate", url=APP + "?capture=" + str(time.time()))
    for _ in range(150):
        time.sleep(0.2)
        if js("document.readyState === 'complete' && !!document.body && !document.body.classList.contains('is-loading')"):
            break
    # Freeze motion so every frame is fully settled, and let fonts and charts finish.
    js("""(() => { const s = document.createElement('style');
      s.textContent = '*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}';
      document.head.appendChild(s); Chart.defaults.animation = false;
      Object.values(Chart.instances).forEach(c => { c.options.animation = false; c.update('none'); }); })()""")
    js("document.fonts.ready.then(() => true)")
    time.sleep(0.6)

def shot(clip=None):
    params = {"format": "png", "captureBeyondViewport": False}
    if clip:
        params["clip"] = {**clip, "scale": 1}
    data = cdp("Page.captureScreenshot", **params)["data"]
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")

def setc(cost, rate, budget):
    js(f"document.getElementById('cost').value={cost};document.getElementById('rate').value={rate};"
       f"document.getElementById('budget').value={budget};applyControls();true")

def scroll_to(y):
    js(f"window.scrollTo(0,{y});true")
    time.sleep(0.15)

# ---- Stills at 2x ----
viewport(1280, 800, 2)
load()
setc(50, 0.30, 25000)

# Clip rectangles are in page (document) coordinates, not viewport coordinates.
r = js("(() => { const b = document.querySelector('.window').getBoundingClientRect(); return {y: b.top + scrollY, x: b.left, w: b.width, h: b.height}; })()")
scroll_to(r["y"] - 120)
data = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=True,
           clip={"x": r["x"] - 1, "y": r["y"] - 1, "width": r["w"] + 2, "height": r["h"] + 2, "scale": 1})["data"]
Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB").save(f"{OUT}/save-list.png", optimize=True)

# ---- Hero GIF at 1x, framed on the workspace ----
viewport(1200, 760, 1)
load()
ws_top = js("document.querySelector('.workspace').getBoundingClientRect().top + scrollY")
frames, durs = [], []
def frame(ms):
    frames.append(shot()); durs.append(ms)

setc(50, 0.30, 25000)
scroll_to(max(0, ws_top - 150))
frame(1600)
for c in [45, 40, 35, 30, 25, 20, 15, 10]:       # cheaper offer: more offers clear positive EV
    setc(c, 0.30, 25000); frame(110)
frame(900)
for b in [35000, 45000, 55000, 65000, 75000, 85000, 100000]:   # bigger budget: the cap stops binding
    setc(10, 0.30, b); frame(140)
frame(2600)                                        # alert: the budget is a cap, not a quota
bt_top = js("document.getElementById('backtest').getBoundingClientRect().top + scrollY")
scroll_to(max(0, bt_top - 76))                     # section heading clear of the sticky top bar
frame(1200)
js("document.querySelector('.heat-cell[data-cost=\"100\"][data-rate=\"0.4\"]').click();applyControls();true")
frame(2600)                                        # grid cell loads its scenario into the sliders
setc(50, 0.30, 25000); scroll_to(max(0, ws_top - 150))

pal = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
pal[0].save(f"{OUT}/demo.gif", save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True, disposal=1)

ws.close(); proc.terminate()
print("frames", len(frames))
