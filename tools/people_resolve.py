#!/usr/bin/env python3
"""Resolve public identities for the people in data/people-candidates.json (conservative, evidence based).

For each person it tries, in order:
  1. Links already collected for them (github.com/<user>, huggingface.co/<user>, a Scholar profile).
  2. Their own personal page (only pages whose title or heading contains their name; never a lab team page),
     reading GitHub, Hugging Face, Scholar, X and LinkedIn links the person published themselves.
  3. OpenAlex: the author list of papers listed on the person's lab pages (arXiv and DOI links); a name match there
     gives an OpenAlex author id plus the paper as evidence.
A GitHub or Hugging Face handle is accepted only when the profile name matches the person (first and last name) or when
the person's own page links to it and the profile links back / matches. Everything else stays empty.

Writes data/people-resolved.json. Caches HTTP results in data/cache/ (git-ignored). Sequential, paced.
Usage: python3 tools/people_resolve.py [--limit N]
"""
import json, os, re, subprocess, sys, time, unicodedata, urllib.request, urllib.error, urllib.parse, hashlib, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("data/cache", exist_ok=True)
UA = {"User-Agent": "OpenLabsAtlas-resolver/1.0 (+https://labs.renaissancelabs.eu)"}
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

HF_RESERVED = {"models", "datasets", "spaces", "docs", "blog", "papers", "collections", "join", "login", "pricing", "organizations", "tasks", "learn", "chat", "enterprise", "settings", "api", "posts", "huggingface", "new"}
GH_RESERVED = {"about", "features", "pricing", "orgs", "topics", "sponsors", "marketplace", "login", "join", "settings", "explore", "collections", "events", "apps", "search", "pulls", "issues", "notifications", "enterprise", "customer-stories", "readme", "security", "site", "contact"}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", strip_accents(s).lower()).strip()


def name_match(person, profile):
    """True when the profile name contains the person's first and last name tokens."""
    pt, qt = norm(person).split(), set(norm(profile).split())
    if len(pt) < 2 or not qt: return False
    return pt[0] in qt and pt[-1] in qt


def cache_path(url): return "data/cache/" + hashlib.sha1(url.encode()).hexdigest()


def get(url, timeout=18, raw=False, maxbytes=1_500_000):
    p = cache_path(url)
    if os.path.exists(p):
        d = open(p, "rb").read()
        return d if raw else d.decode("utf-8", "ignore")
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = r.read(maxbytes)
            open(p, "wb").write(d)
            return d if raw else d.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(6 * (i + 1)); continue
            if e.code in (400, 401, 403, 404, 410, 451): open(p, "wb").write(b""); return b"" if raw else ""
            time.sleep(2)
        except Exception:
            time.sleep(1.5)
    return b"" if raw else ""


def jget(url):
    t = get(url)
    try: return json.loads(t) if t else None
    except Exception: return None


def gh_user(login):
    p = cache_path("ghuser:" + login)
    if os.path.exists(p):
        t = open(p).read(); return json.loads(t) if t else None
    r = subprocess.run(["gh", "api", f"users/{login}"], capture_output=True, text=True, timeout=40)
    if r.returncode != 0:
        open(p, "w").write(""); return None
    d = json.loads(r.stdout); open(p, "w").write(json.dumps(d)); return d


def hf_user(login):
    d = jget(f"https://huggingface.co/api/users/{urllib.parse.quote(login)}/overview")
    time.sleep(0.4)
    return d


GH_RE = re.compile(r'https?://(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})/?(?=["\'#?\s<)\]]|$)', re.I)
HF_RE = re.compile(r'https?://(?:www\.)?huggingface\.co/([A-Za-z0-9._-]{1,60})/?(?=["\'#?\s<)\]]|$)', re.I)
SC_RE = re.compile(r'https?://scholar\.google\.[a-z.]+/citations\?[^"\'<>\s]*user=([A-Za-z0-9_-]{8,14})', re.I)
X_RE = re.compile(r'https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/?(?=["\'#?\s<)\]]|$)', re.I)
LI_RE = re.compile(r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9%_-]{3,100})/?', re.I)
AGGREGATORS = {"alphaxiv.org", "semanticscholar.org", "researchgate.net", "dblp.org", "orcid.org", "openreview.net", "aclanthology.org", "medium.com", "substack.com", "paperswithcode.com", "scholar.google.com", "crunchbase.com", "zoominfo.com", "rocketreach.co", "wikipedia.org", "wikidata.org", "youtube.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com", "arxiv.org", "huggingface.co", "github.com"}
X_RESERVED = {"share", "intent", "home", "search", "i", "hashtag", "login", "explore"}


def looks_personal(html, name, lab_domains, url):
    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    if any(host == d or host.endswith("." + d) for d in lab_domains if d): return False
    if any(host == d or host.endswith("." + d) for d in AGGREGATORS): return False
    head = re.sub(r"\s+", " ", html[:6000]).lower()
    t = re.search(r"<title>(.*?)</title>", html[:20000], re.I | re.S)
    blob = norm((t.group(1) if t else "") + " " + " ".join(re.findall(r"<h1[^>]*>(.*?)</h1>", html[:60000], re.I | re.S)))
    parts = norm(name).split()
    return bool(parts) and parts[-1] in blob.split() and parts[0] in blob.split()


def main():
    cands = json.load(open("data/people-candidates.json"))
    if LIMIT: cands = cands[:LIMIT]
    labs = {l["id"]: l for l in json.load(open("data/labs.json"))["labs"]}
    lab_domains = {}
    for lid, l in labs.items():
        lab_domains[lid] = urllib.parse.urlparse(l["website"] or "").netloc.replace("www.", "")
    lab_orgs = {lid: (urllib.parse.urlparse(l["github"] or "").path.strip("/").split("/")[0].lower() if l["github"] else "") for lid, l in labs.items()}
    all_lab_domains = {d for d in lab_domains.values() if d}

    # ---- OpenAlex author lists for lab papers (arXiv and DOI links), fetched once per paper
    papers = {}
    for c in cands:
        for u in c["lab_papers"]: papers.setdefault(u, None)
    print(f"{len(cands)} people; {len(papers)} lab papers to check", flush=True)
    for i, u in enumerate(list(papers)):
        m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", u)
        doi = ("10.48550/arxiv." + m.group(1)) if m else None
        if not doi:
            m2 = re.search(r"doi\.org/(10\.[^\s?#]+)", u)
            doi = m2.group(1) if m2 else None
        if not doi: continue
        d = jget(f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}?select=authorships")
        time.sleep(0.12)
        if d and d.get("authorships"):
            papers[u] = [{"id": a["author"]["id"].split("/")[-1], "name": a["author"]["display_name"],
                          "inst": [x.get("display_name") for x in a.get("institutions", [])][:2]} for a in d["authorships"] if a.get("author") and a["author"].get("id") and a["author"].get("display_name")]
        if (i + 1) % 100 == 0: print(f"  papers {i+1}/{len(papers)}", flush=True)

    out = []
    for idx, c in enumerate(cands):
        r = {"name": c["name"], "norm": c["norm"], "affiliations": c["affiliations"], "handles": {}, "evidence": [], "openalex": None}
        labs_of = [a["lab"] for a in c["affiliations"]]
        # 1. direct links
        for u in c["urls"]:
            m = GH_RE.match(u)
            if m and m.group(1).lower() not in GH_RESERVED and m.group(1).lower() not in lab_orgs.values():
                r["handles"].setdefault("github_candidate", m.group(1)); r["evidence"].append(f"linked on lab page: {u}")
            m = HF_RE.match(u)
            if m and m.group(1).lower() not in HF_RESERVED:
                r["handles"].setdefault("hf_candidate", m.group(1)); r["evidence"].append(f"linked on lab page: {u}")
            m = SC_RE.search(u)
            if m: r["handles"]["scholar"] = f"https://scholar.google.com/citations?user={m.group(1)}"; r["evidence"].append(f"scholar link on lab page")
        # 2. personal page
        for u in c["urls"]:
            if re.search(r"github\.com|huggingface\.co|wikipedia\.org|arxiv\.org|scholar\.google|linkedin\.com|x\.com|twitter\.com", u): continue
            html = get(u)
            if not html or not looks_personal(html, c["name"], all_lab_domains, u): continue
            r["handles"]["website"] = u
            r["evidence"].append(f"personal page: {u}")
            for rx, key in ((GH_RE, "github_candidate"), (HF_RE, "hf_candidate")):
                for m in rx.finditer(html):
                    h = m.group(1)
                    if key == "github_candidate" and h.lower() in GH_RESERVED: continue
                    if key == "hf_candidate" and h.lower() in HF_RESERVED: continue
                    r["handles"].setdefault(key, h); r["evidence"].append(f"{key.split('_')[0]} link on personal page")
                    break
            m = SC_RE.search(html)
            if m and "scholar" not in r["handles"]: r["handles"]["scholar"] = f"https://scholar.google.com/citations?user={m.group(1)}"
            m = LI_RE.search(html)
            if m: r["handles"].setdefault("linkedin", f"https://www.linkedin.com/in/{m.group(1)}")
            break
        # verify GitHub / HF candidates against profile names
        gc = r["handles"].pop("github_candidate", None)
        if gc:
            u = gh_user(gc); time.sleep(0.15)
            if u and u.get("type") == "User" and (name_match(c["name"], u.get("name") or "") or (r["handles"].get("website") and u.get("blog") and urllib.parse.urlparse(u["blog"] if "//" in u["blog"] else "//" + u["blog"]).netloc.replace("www.", "") == urllib.parse.urlparse(r["handles"]["website"]).netloc.replace("www.", ""))):
                r["handles"]["github"] = u["login"]; r["evidence"].append(f"github profile name matches: {u.get('name')}")
                if u.get("twitter_username") and "x" not in r["handles"]: r["handles"]["x"] = u["twitter_username"]
        hc = r["handles"].pop("hf_candidate", None)
        if hc:
            u = hf_user(hc)
            if u and name_match(c["name"], u.get("fullname") or ""):
                r["handles"]["huggingface"] = u.get("user") or hc; r["evidence"].append(f"hugging face profile name matches: {u.get('fullname')}")
        # 3. OpenAlex via lab papers
        votes = collections.Counter(); sample = {}
        for lid in set(labs_of):
            for pu in c["lab_papers"]:
                for a in (papers.get(pu) or []):
                    if norm(a["name"]) == c["norm"]:
                        votes[a["id"]] += 1; sample.setdefault(a["id"], (a["name"], a["inst"], pu))
        if votes:
            aid, n = votes.most_common(1)[0]
            r["openalex"] = {"id": aid, "name": sample[aid][0], "institutions": sample[aid][1], "papers_matched": n, "evidence_paper": sample[aid][2]}
            r["evidence"].append(f"author on {n} lab paper(s)")
        out.append(r)
        if (idx + 1) % 50 == 0:
            print(f"  people {idx+1}/{len(cands)}", flush=True)
            json.dump(out, open("data/people-resolved.json", "w"), ensure_ascii=False, indent=1)
    json.dump(out, open("data/people-resolved.json", "w"), ensure_ascii=False, indent=1)
    gh = sum(1 for r in out if r["handles"].get("github")); hf = sum(1 for r in out if r["handles"].get("huggingface"))
    oa = sum(1 for r in out if r["openalex"]); web = sum(1 for r in out if r["handles"].get("website"))
    sc = sum(1 for r in out if r["handles"].get("scholar"))
    print(f"resolved: github {gh}, huggingface {hf}, openalex {oa}, personal site {web}, scholar {sc} of {len(out)}")


if __name__ == "__main__":
    main()
