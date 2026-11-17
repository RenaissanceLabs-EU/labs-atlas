#!/usr/bin/env python3
"""Detect prominent contributors for each lab from its main public GitHub repos (public data only, no emails).

For every lab with highlighted GitHub repos, reads each repo's contributor list (top committers), drops bots, keeps
people with substantial contributions, and fetches their public profile (name, bio, followers). Writes
data/contributors.json. Uses the local `gh` CLI (authenticated REST, polite pacing).
Usage: python3 tools/people_contributors.py
"""
import json, os, re, subprocess, sys, time, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    time.sleep(0.12)
    if r.returncode != 0: return None
    try: return json.loads(r.stdout)
    except Exception: return None

labs = json.load(open("data/labs.json"))["labs"]
known = set()
import glob
for f in glob.glob("data/people/*.json"):
    p = json.load(open(f)); h = p.get("handles") or {}
    if h.get("github"): known.add(h["github"].lower())
try:
    for r in json.load(open("data/people-resolved.json")):
        if r["handles"].get("github"): known.add(r["handles"]["github"].lower())
except Exception:
    pass

per_lab = {}
for l in labs:
    repos = []
    for h in l["github_highlights"]:
        m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", h.get("url") or "")
        if m and (m.group(1), m.group(2)) not in repos: repos.append((m.group(1), m.group(2)))
    org = (re.match(r"https?://github\.com/([^/]+)", l["github"] or "") or [None, ""])[1].lower()
    owned = []
    for owner, repo in repos:
        if owner.lower() != org: continue
        meta = gh(f"repos/{owner}/{repo}")
        if not meta or meta.get("fork") or meta.get("archived"): continue
        owned.append((owner, repo))
    repos = owned[:3]
    if not repos: continue
    tally = collections.Counter(); where = collections.defaultdict(list)
    for owner, repo in repos:
        cs = gh(f"repos/{owner}/{repo}/contributors?per_page=12") or []
        for c in cs:
            if c.get("type") != "User" or c["login"].endswith("[bot]") or "bot" == c["login"].lower().split("-")[-1]: continue
            if c["contributions"] < 80: continue
            tally[c["login"]] += c["contributions"]; where[c["login"]].append({"repo": f"{owner}/{repo}", "contributions": c["contributions"]})
    per_lab[l["id"]] = [(login, n, where[login]) for login, n in tally.most_common(8)]

out = {}
profiles = {}
for lid, rows in per_lab.items():
    for login, n, wh in rows:
        if login.lower() in known: continue
        if login not in profiles:
            u = gh(f"users/{login}")
            profiles[login] = u
        u = profiles[login]
        if not u: continue
        followers = u.get("followers", 0)
        if followers < 60 and n < 400: continue
        c = out.setdefault(login, {"login": login, "name": u.get("name"), "bio": (u.get("bio") or "")[:200], "company": u.get("company"),
                                  "followers": followers, "blog": u.get("blog"), "x": u.get("twitter_username"), "labs": []})
        c["labs"].append({"lab": lid, "contributions": n, "repos": wh})
res = sorted(out.values(), key=lambda c: -sum(x["contributions"] for x in c["labs"]))
# keep at most 4 per lab (highest contributions)
keep = collections.defaultdict(int); final = []
for c in res:
    top = max(c["labs"], key=lambda x: x["contributions"])["lab"]
    if keep[top] >= 4: continue
    keep[top] += 1; final.append(c)
json.dump(final, open("data/contributors.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(final)} prominent contributors across {len(keep)} labs; {len(labs)} labs checked")
