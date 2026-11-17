#!/usr/bin/env python3
"""Fetch public activity for each person in data/people/*.json into data/activity/<id>.json.

Sources (public data only, each skipped when the handle is missing):
  - GitHub GraphQL via the local `gh` CLI: contribution calendar (public contributions, last year), top repos, followers.
  - Hugging Face public API: counts, most downloaded models and datasets, creation dates per year.
  - OpenAlex (no key): works and citations per year, h-index, most cited works.
Google Scholar is not fetched (it blocks automated access); a Scholar link is only displayed.
Sequential and paced to respect rate limits. Usage: python3 tools/fetch_activity.py [--force] [person-id ...]
"""
import datetime, glob, json, os, subprocess, sys, time, urllib.request, urllib.error, urllib.parse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("data/activity", exist_ok=True)
FORCE = "--force" in sys.argv
ONLY = [a for a in sys.argv[1:] if not a.startswith("--")]
UA = {"User-Agent": "OpenLabsAtlas-activity/1.0"}
TODAY = datetime.date.today().isoformat()


def http_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(8 * (i + 1)); continue
            if e.code in (404, 400): return None
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


GQL = """
query($login:String!){
  user(login:$login){
    name login avatarUrl bio followers{totalCount} createdAt
    contributionsCollection{
      contributionCalendar{ totalContributions weeks{ firstDay contributionDays{ contributionCount } } }
    }
    repositories(first:6, orderBy:{field:STARGAZERS,direction:DESC}, ownerAffiliations:OWNER, privacy:PUBLIC){
      nodes{ name url stargazerCount description primaryLanguage{name} }
    }
  }
}"""


def github(login):
    r = subprocess.run(["gh", "api", "graphql", "-f", f"query={GQL}", "-F", f"login={login}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0: return None
    try:
        u = json.loads(r.stdout)["data"]["user"]
    except Exception:
        return None
    if not u: return None
    cal = u["contributionsCollection"]["contributionCalendar"]
    weeks = [[d["contributionCount"] for d in w["contributionDays"]] for w in cal["weeks"]]
    langs = collections.Counter()
    repos = []
    for n in u["repositories"]["nodes"]:
        lang = (n.get("primaryLanguage") or {}).get("name")
        if lang: langs[lang] += 1
        repos.append({"name": n["name"], "url": n["url"], "stars": n["stargazerCount"], "description": (n.get("description") or "")[:160], "language": lang})
    return {"login": u["login"], "profile_name": u.get("name"), "bio": (u.get("bio") or "")[:200], "followers": u["followers"]["totalCount"],
            "since": (u.get("createdAt") or "")[:4], "calendar": {"start": cal["weeks"][0]["firstDay"] if cal["weeks"] else None, "total": cal["totalContributions"], "weeks": weeks},
            "top_repos": repos, "languages": [l for l, _ in langs.most_common(4)]}


def huggingface(user):
    ov = http_json(f"https://huggingface.co/api/users/{user}/overview")
    if not ov: return None
    time.sleep(0.6)
    out = {"user": user, "followers": ov.get("numFollowers"), "models": ov.get("numModels"), "datasets": ov.get("numDatasets"), "spaces": ov.get("numSpaces"), "likes": ov.get("numLikes")}
    top = []
    for kind, path in (("model", "models"), ("dataset", "datasets")):
        items = http_json(f"https://huggingface.co/api/{path}?author={urllib.parse.quote(user)}&sort=downloads&direction=-1&limit=4") or []
        for it in items:
            top.append({"kind": kind, "name": it.get("id"), "url": f"https://huggingface.co/{'datasets/' if kind == 'dataset' else ''}{it.get('id')}",
                        "downloads": it.get("downloads"), "likes": it.get("likes")})
        time.sleep(0.6)
    out["top"] = sorted(top, key=lambda x: -(x.get("downloads") or 0))[:5]
    years = collections.Counter()
    for path in ("models", "datasets", "spaces"):
        items = http_json(f"https://huggingface.co/api/{path}?author={urllib.parse.quote(user)}&limit=1000") or []
        for it in items:
            c = (it.get("createdAt") or "")[:4]
            if c.isdigit(): years[c] += 1
        time.sleep(0.6)
    out["created_by_year"] = dict(sorted(years.items()))
    return out


def openalex(aid):
    aid = aid.strip().split("/")[-1]
    a = http_json(f"https://api.openalex.org/authors/{aid}")
    if not a: return None
    time.sleep(0.3)
    works = http_json(f"https://api.openalex.org/works?filter=author.id:{aid}&sort=cited_by_count:desc&per-page=5&select=title,publication_year,cited_by_count,doi,primary_location") or {}
    top = []
    for w in works.get("results", []):
        url = w.get("doi") or (((w.get("primary_location") or {}).get("landing_page_url")))
        top.append({"title": w.get("title"), "year": w.get("publication_year"), "cited_by": w.get("cited_by_count"), "url": url})
    counts = {str(c["year"]): c["works_count"] for c in a.get("counts_by_year", []) if c.get("works_count")}
    return {"id": aid, "name": a.get("display_name"), "works": a.get("works_count"), "cited_by": a.get("cited_by_count"),
            "h_index": (a.get("summary_stats") or {}).get("h_index"), "works_by_year": dict(sorted(counts.items())),
            "citations_by_year": {str(c["year"]): c["cited_by_count"] for c in a.get("counts_by_year", []) if c.get("cited_by_count")},
            "top_works": top}


def avatar(p):
    """Only for handle-first accounts: their chosen public icon. Real-name people get a monogram instead."""
    import tempfile
    out = f"assets/people/{p['id']}.png"
    if os.path.exists(out) and not FORCE: return
    h = p.get("handles") or {}
    url = None
    if h.get("github"): url = f"https://github.com/{h['github']}.png?size=192"
    elif h.get("huggingface"):
        m = http_json(f"https://huggingface.co/api/users/{h['huggingface']}/overview")
        url = (m or {}).get("avatarUrl")
        if url and url.startswith("/"): url = "https://huggingface.co" + url
    if not url: return
    try:
        req = urllib.request.Request(url, headers=UA)
        data = urllib.request.urlopen(req, timeout=25).read()
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as t:
            t.write(data); tmp = t.name
        subprocess.run(["sips", "-s", "format", "png", "-Z", "192", tmp, "--out", out], capture_output=True)
        os.unlink(tmp)
    except Exception:
        pass


def main():
    files = sorted(glob.glob("data/people/*.json"))
    done = 0
    for f in files:
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        pid = p.get("id") or os.path.basename(f)[:-5]
        if ONLY and pid not in ONLY: continue
        out_path = f"data/activity/{pid}.json"
        if os.path.exists(out_path) and not FORCE:
            continue
        h = p.get("handles") or {}
        act = {"fetched": TODAY}
        if h.get("github"):
            g = github(h["github"]); act["github"] = g
        if h.get("huggingface"):
            act["huggingface"] = huggingface(h["huggingface"])
        if h.get("openalex"):
            act["papers"] = openalex(h["openalex"])
        if p.get("kind") == "handle": avatar(p)
        json.dump(act, open(out_path, "w"), ensure_ascii=False)
        done += 1
        print(f"  {pid}: " + ", ".join(k for k in ("github", "huggingface", "papers") if act.get(k)) , flush=True)
    print(f"activity fetched for {done} people")


if __name__ == "__main__":
    main()
