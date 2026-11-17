#!/usr/bin/env python3
"""Render 1200x630 social preview images (assets/og/<id>.jpg and home.jpg) with headless Chrome.

Serves the site on a temporary local port, renders tools/og/card.html?id=<id> one lab at a time
(sequential, one Chrome at a time), converts to JPEG with macOS `sips`. Resumable: skips existing files
unless --force. Usage: python3 tools/make_og.py [--force] [id ...]
"""
import json, os, subprocess, sys, tempfile, time, shutil, threading, http.server, socketserver, functools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 8791
FORCE = "--force" in sys.argv
ONLY = [a for a in sys.argv[1:] if not a.startswith("--")]
os.makedirs("assets/og", exist_ok=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def serve():
    handler = functools.partial(Quiet, directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def render(card_id, out_jpg, profile):
    png = tempfile.mktemp(suffix=".png")
    url = f"http://127.0.0.1:{PORT}/tools/og/card.html?id={card_id}"
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
           f"--user-data-dir={profile}", "--window-size=1200,630", "--force-device-scale-factor=1",
           "--virtual-time-budget=6000", f"--screenshot={png}", url]
    subprocess.run(cmd, capture_output=True, timeout=90)
    if not os.path.exists(png) or os.path.getsize(png) < 5000:
        return False
    r = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "84", png, "--out", out_jpg], capture_output=True)
    os.unlink(png)
    return r.returncode == 0


def main():
    labs = json.load(open("data/labs.json"))["labs"]
    ids = ["home"] + [l["id"] for l in labs]
    if ONLY: ids = ONLY
    srv = serve()
    profile = tempfile.mkdtemp(prefix="og-chrome-")
    ok = fail = skip = 0
    try:
        for i in ids:
            out = f"assets/og/{i}.jpg"
            if os.path.exists(out) and not FORCE:
                skip += 1; continue
            try:
                good = render(i, out, profile)
            except Exception as e:
                good = False
            if good: ok += 1
            else:
                fail += 1; print("failed:", i, flush=True)
            if (ok + fail) % 20 == 0: print(f"  {ok + fail} done", flush=True)
    finally:
        srv.shutdown(); shutil.rmtree(profile, ignore_errors=True)
    print(f"og images: {ok} rendered, {skip} existing, {fail} failed")


if __name__ == "__main__":
    main()
