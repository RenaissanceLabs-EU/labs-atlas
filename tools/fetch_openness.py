#!/usr/bin/env python3
"""Fetch licence and activity facts for each lab into data/openness/<id>.json (public GitHub and Hugging Face data).

GitHub (via the `gh` CLI, authenticated): the lab org's most recent non-fork repos with SPDX licences, last push date,
number of repos pushed in the last 90 days.
Hugging Face (public API): models and datasets with licence tags, counts, latest created model and dataset.
Tolerant: a failed source keeps the previous file's values for that source. Sequential and paced.
Usage: python3 tools/fetch_openness.py [--force] [lab-id ...]
"""
import datetime, json, os, subprocess, sys, time, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("data/openness", exist_ok=True)
FORCE = "--force" in sys.argv
ONLY = [a for a in sys.argv[1:] if not a.startswith("--")]
UA = {"User-Agent": "OpenLabsAtlas-openness/1.0 (+https://labs.renaissancelabs.eu)"}
NOW = datetime.datetime.now(datetime.timezone.utc)
TODAY = NOW.date().isoformat()


def http_json(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(10 * (i + 1)); continue
            if e.code in (400, 401, 403, 404): return None
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return None


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=90)
    time.sleep(0.1)
    if r.returncode != 0: return None
    try: return json.loads(r.stdout)
    except Exception: return None


def first_segment(u):
    if not u: return None
    seg = [s for s in urllib.parse.urlparse(u).path.split("/") if s]
    return seg[0] if seg else None


def days_ago(iso):
    try:
        d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (NOW - d).days
    except Exception:
        return None


def github(org):
    repos = gh(f"orgs/{org}/repos?type=public&sort=pushed&per_page=100")
    if repos is None: repos = gh(f"users/{org}/repos?type=owner&sort=pushed&per_page=100")
    if repos is None: return None
    own = [r for r in repos if not r.get("fork") and not r.get("archived")]
    if not own: return {"org": org, "repos": 0}
    recent = [r for r in own if (days_ago(r.get("pushed_at")) or 9999) <= 90]
    top = sorted(own, key=lambda r: -r.get("stargazers_count", 0))[:15]
    lic = {}
    for r in top:
        k = ((r.get("license") or {}).get("spdx_id")) or "NONE"
        lic[k] = lic.get(k, 0) + 1
    newest = max(own, key=lambda r: r.get("pushed_at") or "")
    return {"org": org, "repos": len(own), "stars_top": sum(r.get("stargazers_count", 0) for r in top[:5]),
            "last_push": newest.get("pushed_at"), "recent_repos_90d": len(recent), "licenses": lic,
            "latest_repo": {"name": newest["name"], "url": newest["html_url"], "pushed": newest.get("pushed_at")}}


def hf_licence(tags):
    for t in tags or []:
        if t.startswith("license:"): return t.split(":", 1)[1].lower()
    return "none"


def huggingface(org):
    ov = http_json(f"https://huggingface.co/api/organizations/{urllib.parse.quote(org)}/overview")
    time.sleep(0.5)
    if ov is None:
        ov = http_json(f"https://huggingface.co/api/users/{urllib.parse.quote(org)}/overview")
        time.sleep(0.5)
    if ov is None: return None
    out = {"org": org, "models": ov.get("numModels"), "datasets": ov.get("numDatasets"), "spaces": ov.get("numSpaces")}
    q = urllib.parse.quote(org)
    top = http_json(f"https://huggingface.co/api/models?author={q}&sort=downloads&direction=-1&limit=25&full=true") or []
    time.sleep(0.5)
    lic = {}
    for m in top: lic[hf_licence(m.get("tags"))] = lic.get(hf_licence(m.get("tags")), 0) + 1
    out["model_licenses"] = lic
    new = http_json(f"https://huggingface.co/api/models?author={q}&sort=createdAt&direction=-1&limit=2") or []
    time.sleep(0.5)
    if new:
        out["latest_model"] = {"name": new[0].get("id"), "url": f"https://huggingface.co/{new[0].get('id')}", "created": new[0].get("createdAt")}
    dl = http_json(f"https://huggingface.co/api/datasets?author={q}&sort=createdAt&direction=-1&limit=20&full=true") or []
    time.sleep(0.5)
    dlic = {}
    for d in dl: dlic[hf_licence(d.get("tags"))] = dlic.get(hf_licence(d.get("tags")), 0) + 1
    out["dataset_licenses"] = dlic
    if dl:
        out["latest_dataset"] = {"name": dl[0].get("id"), "url": f"https://huggingface.co/datasets/{dl[0].get('id')}", "created": dl[0].get("createdAt")}
    mod = http_json(f"https://huggingface.co/api/models?author={q}&sort=lastModified&direction=-1&limit=1") or []
    time.sleep(0.5)
    if mod: out["last_modified"] = mod[0].get("lastModified")
    return out


def main():
    labs = json.load(open("data/labs.json"))["labs"]
    done = 0
    for l in labs:
        if ONLY and l["id"] not in ONLY: continue
        path = f"data/openness/{l['id']}.json"
        old = {}
        if os.path.exists(path):
            try: old = json.load(open(path))
            except Exception: old = {}
            if not FORCE and old.get("fetched") == TODAY: continue
        rec = {"id": l["id"], "fetched": TODAY, "github": old.get("github"), "hf": old.get("hf")}
        g = first_segment(l.get("github"))
        if g:
            r = github(g)
            if r is not None: rec["github"] = r
        h = first_segment(l.get("huggingface"))
        if h:
            r = huggingface(h)
            if r is not None: rec["hf"] = r
        json.dump(rec, open(path, "w"), ensure_ascii=False)
        done += 1
        if done % 20 == 0: print(f"  {done} labs", flush=True)
    print(f"openness data refreshed for {done} labs")


if __name__ == "__main__":
    main()
