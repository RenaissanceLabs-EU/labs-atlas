#!/usr/bin/env python3
"""Collect every key person listed on lab pages into data/people-candidates.json (merged across labs).
Skips single-name entries and people who already have a record in data/people/."""
import glob, json, os, re, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def norm(s): return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

labs = json.load(open("data/labs.json"))["labs"]
have = set()
for f in glob.glob("data/people/*.json"):
    p = json.load(open(f))
    for n in (p.get("name"), p.get("display")):
        if n: have.add(norm(n))
cands = collections.OrderedDict()
single = 0
for l in labs:
    paper_urls = [p["url"] for p in l["papers"] if p.get("url")]
    for kp in l["key_people"]:
        n = kp["name"].strip()
        if len(n.split()) < 2: single += 1; continue
        k = norm(n)
        if k in have: continue
        c = cands.setdefault(k, {"name": n, "norm": k, "affiliations": [], "urls": [], "lab_papers": []})
        c["affiliations"].append({"lab": l["id"], "lab_name": l["name"], "role": kp.get("role"), "note": kp.get("note")})
        if kp.get("url") and kp["url"] not in c["urls"]: c["urls"].append(kp["url"])
        for u in paper_urls:
            if u not in c["lab_papers"]: c["lab_papers"].append(u)
out = list(cands.values())
json.dump(out, open("data/people-candidates.json", "w"), ensure_ascii=False, indent=1)
multi = sum(1 for c in out if len(c["affiliations"]) > 1)
print(f"{len(out)} candidate people ({multi} in more than one lab); skipped {single} single-name entries; {len(have)} already done")
# how many have a link that is not a generic lab/wiki page
def personal(u):
    return not re.search(r"wikipedia\.org|arxiv\.org|nature\.com|aclanthology|github\.com/[^/]+/?$|huggingface\.co/[^/]+/?$", u) and True
pers = sum(1 for c in out if any(personal(u) for u in c["urls"]))
print("with at least one non-generic link:", pers)
import urllib.parse
dom = collections.Counter(urllib.parse.urlparse(u).netloc.replace("www.","") for c in out for u in c["urls"])
print(dom.most_common(12))
