#!/usr/bin/env python3
"""Fetch a small logo for each lab into assets/logos/<id>.png.

Source order: the lab's GitHub org avatar, then its Hugging Face org avatar. Labs without either get a
generated monogram at build time. Images are resized to 192px with macOS `sips`. Sequential, polite, resumable.
Usage: python3 tools/fetch_logos.py [--force]
"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("assets/logos", exist_ok=True)
FORCE = "--force" in sys.argv
UA = {"User-Agent": "OpenLabsAtlas-logo-fetch/1.0"}


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def first_segment(u):
    if not u: return None
    seg = [s for s in urlparse(u).path.split("/") if s]
    return seg[0] if seg else None


def save(data, out):
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as t:
        t.write(data); tmp = t.name
    try:
        r = subprocess.run(["sips", "-s", "format", "png", "-Z", "192", tmp, "--out", out], capture_output=True, text=True)
        return r.returncode == 0 and os.path.getsize(out) > 300
    finally:
        os.unlink(tmp)


def main():
    labs = json.load(open("data/labs.json"))["labs"]
    ok = miss = skip = 0
    for l in labs:
        out = f"assets/logos/{l['id']}.png"
        if os.path.exists(out) and not FORCE:
            skip += 1; continue
        done = False
        org = first_segment(l.get("github"))
        if org:
            try:
                data, ct = get(f"https://github.com/{org}.png?size=192")
                done = ct.startswith("image") and save(data, out)
            except Exception as e:
                pass
            time.sleep(0.25)
        if not done:
            hf = first_segment(l.get("huggingface"))
            if hf:
                try:
                    meta, _ = get(f"https://huggingface.co/api/organizations/{hf}/avatar")
                    url = json.loads(meta).get("avatarUrl")
                    if url:
                        data, ct = get(url)
                        done = ct.startswith("image") and save(data, out)
                except Exception:
                    pass
                time.sleep(0.6)
        if done: ok += 1
        else:
            miss += 1
            if os.path.exists(out): os.unlink(out)
    print(f"logos: {ok} fetched, {skip} already present, {miss} without logo (monogram fallback)")


if __name__ == "__main__":
    main()
