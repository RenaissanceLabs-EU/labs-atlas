#!/usr/bin/env python3
"""Quality pass over data/people/*.json before publishing: removes emails, validates LinkedIn slugs against the
person's name, drops OpenAlex ids known to mix in other authors, and writes flags to the private review file."""
import glob, json, os, re, unicodedata
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
BAD_OPENALEX = {"amanpreet-singh", "maximilian-beck", "pelonomi-moiloa", "christopher-potts"}
def sa(s): return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
def toks(s): return [t for t in re.sub(r"[^a-z0-9]+", " ", sa(s).lower()).split() if len(t) > 2]

def scrub(o, path, found):
    if isinstance(o, dict): return {k: scrub(v, path + [k], found) for k, v in o.items()}
    if isinstance(o, list): return [scrub(v, path + ["#"], found) for v in o]
    if isinstance(o, str) and EMAIL.search(o) and not o.startswith("http"):
        found.append(".".join(map(str, path))); return None
    if isinstance(o, str) and o.startswith("http") and "@" in o.split("/")[2:3][0] if isinstance(o, str) and o.startswith("http") and len(o.split("/")) > 2 else False:
        found.append(".".join(map(str, path))); return None
    return o

flags, changed = {}, 0
for f in sorted(glob.glob("data/people/*.json")):
    p = json.load(open(f)); pid = p["id"]; orig = json.dumps(p, sort_keys=True)
    found = []
    p = scrub(p, [], found)
    h = p.get("handles") or {}
    name = p.get("name") or p.get("display") or ""
    li = h.get("linkedin")
    if li:
        slug = (li.rstrip("/").split("/in/")[-1] if "/in/" in li else "")
        nt = toks(name)
        if not slug or not any(t in re.sub(r"[^a-z0-9]", "", sa(slug).lower()) for t in nt):
            h["linkedin"] = None; found.append("linkedin (does not match name)")
    if pid in BAD_OPENALEX and h.get("openalex"):
        h["openalex"] = None; found.append("openalex (mixed authors)")
    p["handles"] = h
    if p.get("flag"): flags[pid] = p["flag"]
    if found: flags[pid] = (flags.get(pid, "") + " | QA: " + "; ".join(found)).strip(" |")
    if json.dumps(p, sort_keys=True) != orig:
        changed += 1; json.dump(p, open(f, "w"), ensure_ascii=False, indent=1)
os.makedirs("../labs-map-private", exist_ok=True)
json.dump(flags, open("../labs-map-private/people-flags.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(glob.glob('data/people/*.json'))} records checked; {changed} changed; {len(flags)} flagged (saved privately)")
