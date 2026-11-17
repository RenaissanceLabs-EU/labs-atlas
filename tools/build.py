#!/usr/bin/env python3
"""Build the Open Labs Atlas (labs.renaissancelabs.eu) from data/regions/*.json plus data/patches/*.json.

Usage: python3 tools/build.py
Writes: data/labs.json, labs.csv, index.html, labs/<slug>/index.html, about/index.html,
        sitemap.xml, robots.txt, llms.txt, CNAME, _headers
Everything user-visible is HTML-escaped; only http(s) URLs are emitted as links.
"""
import csv, glob, html, json, math, os, re, sys, datetime, shutil
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
DOMAIN = "labs.renaissancelabs.eu"
SITE = "https://" + DOMAIN
TODAY = datetime.date.today().isoformat()

TYPES = {
    "startup": "Independent company",
    "nonprofit": "Nonprofit",
    "collective": "Community collective",
    "institute": "Institute",
    "academic": "Academic lab",
    "corporate": "Large company",
}
TYPE_COLOR = {"startup": "#c79a3f", "nonprofit": "#4f7a6a", "collective": "#a35c47", "institute": "#5a6f9a", "academic": "#7d6a9a", "corporate": "#6b6459"}

# explicit friendly URL slugs where the automatic one would be unclear
SLUG_OVERRIDES = {
    "allen-institute-for-ai-ai2": "ai2",
    "allen-institute-for-ai": "ai2",
    "ai2": "ai2",
}

EUROPE = set("""Albania Andorra Austria Belarus Belgium Bulgaria Croatia Cyprus Czechia Denmark Estonia Finland France Germany Greece Hungary Iceland Ireland Italy Kosovo Latvia Liechtenstein Lithuania Luxembourg Malta Moldova Monaco Montenegro Netherlands Norway Poland Portugal Romania Russia Serbia Slovakia Slovenia Spain Sweden Switzerland Turkey Türkiye Ukraine UK Scotland England Wales Georgia Armenia Azerbaijan""".split()) | {"Bosnia and Herzegovina", "Czech Republic", "North Macedonia", "United Kingdom", "Northern Ireland", "Faroe Islands", "San Marino"}
NORTH_AMERICA = {"United States", "USA", "US", "Canada", "Mexico"}
LATAM = {"Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Costa Rica", "Cuba", "Dominican Republic", "Ecuador", "El Salvador", "Guatemala", "Honduras", "Jamaica", "Nicaragua", "Panama", "Paraguay", "Peru", "Puerto Rico", "Trinidad and Tobago", "Uruguay", "Venezuela", "Haiti", "Barbados", "Bahamas"}
MIDEAST = {"Israel", "United Arab Emirates", "UAE", "Saudi Arabia", "Qatar", "Iran", "Kuwait", "Bahrain", "Oman", "Jordan", "Lebanon", "Iraq", "Syria", "Yemen", "Palestine"}
OCEANIA = {"Australia", "New Zealand", "Fiji", "Papua New Guinea", "Samoa", "Tonga"}
AFRICA = {"Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cameroon", "Cape Verde", "Chad", "Congo", "DR Congo", "Democratic Republic of the Congo", "Egypt", "Ethiopia", "Gabon", "Gambia", "Ghana", "Guinea", "Ivory Coast", "Côte d'Ivoire", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Senegal", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"}


def region_of(country):
    c = (country or "").strip()
    if c in NORTH_AMERICA: return "North America"
    if c in LATAM: return "Latin America"
    if c in MIDEAST: return "Middle East"
    if c in OCEANIA: return "Oceania"
    if c in AFRICA: return "Africa"
    if c in EUROPE: return "Europe"
    return "Asia" if c else "Other"


def clean_url(u):
    if not u or not isinstance(u, str): return None
    u = u.strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc: return None
    return u


def clean_email(e):
    if not e or not isinstance(e, str): return None
    e = e.strip()
    return e if re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", e) else None


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "lab"


def split_name(name):
    """'LAION (incl. OpenAssistant)' -> ('LAION', 'incl. OpenAssistant')."""
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", name.strip())
    if m and m.group(1):
        return m.group(1).strip(), m.group(2).strip()
    return name.strip(), None


def domain(u):
    try:
        d = urlparse(u).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def num(x):
    try:
        return float(x)
    except Exception:
        return None


def s_or_none(v, n=1200):
    return str(v).strip()[:n] if v not in (None, "", []) else None


def items(r, key, fields, urlfield="url", limit=5, n=400):
    out = []
    for it in (r.get(key) or [])[:limit]:
        if not isinstance(it, dict): continue
        row = {f: s_or_none(it.get(f), n) for f in fields}
        if urlfield in row: row[urlfield] = clean_url(it.get(urlfield))
        if not (row.get("name") or row.get("title")): continue
        out.append(row)
    return out


def load():
    seen_id, seen_dom, labs, skipped = {}, {}, [], []
    patches = {}
    def patch_rank(path):
        n = os.path.basename(path)
        return (9 if n.startswith("zz") else 3 if n.startswith("thin") else 2 if n.startswith("editorial") else 1, n)
    for path in sorted(glob.glob("data/patches/*.json"), key=patch_rank):
        try:
            for pr in json.load(open(path, encoding="utf-8")):
                if isinstance(pr, dict) and pr.get("id"):
                    patches.setdefault(slug(pr["id"]), {}).update(pr)
        except Exception as ex:
            print("!! cannot parse", path, ex, file=sys.stderr)
    all_rows = []
    for path in sorted(glob.glob("data/regions/*.json")):
        if os.path.basename(path).startswith("_"): continue
        try:
            all_rows.extend(json.load(open(path, encoding="utf-8")))
        except Exception as ex:
            print("!! cannot parse", path, ex, file=sys.stderr)
    for r in all_rows:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        orig_id = slug(r.get("id") or r["name"])
        pt = patches.get(orig_id)
        if pt:
            if pt.get("_remove"):
                skipped.append((r["name"], "removed by patch")); continue
            r = {**r, **{k: v for k, v in pt.items() if k not in ("id", "_remove")}}
        lat, lon = num(r.get("lat")), num(r.get("lon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            skipped.append((r.get("name"), "bad coordinates")); continue
        site = clean_url(r.get("website"))
        dom = domain(site) if site else ""
        if orig_id in seen_id:
            skipped.append((r["name"], "duplicate id " + orig_id)); continue
        if dom and dom in seen_dom and dom not in ("github.com", "huggingface.co"):
            skipped.append((r["name"], "duplicate website with " + seen_dom[dom])); continue
        t = r.get("type") if r.get("type") in TYPES else "startup"
        focus = [str(f).strip() for f in (r.get("focus") or []) if str(f).strip()][:6]
        rel = []
        for n in (r.get("notable_releases") or [])[:4]:
            if isinstance(n, dict) and n.get("name"):
                rel.append({"name": str(n["name"])[:120], "url": clean_url(n.get("url")), "note": str(n.get("note") or "")[:300]})
        people = []
        for p in (r.get("key_people") or []):
            if isinstance(p, dict) and p.get("name"):
                people.append({"name": str(p["name"]).strip()[:80], "role": s_or_none(p.get("role"), 120),
                               "url": clean_url(p.get("url")), "note": s_or_none(p.get("note"), 240)})
        people = [p for p in people if len(p["name"].split()) >= 2]
        if not people:
            people = [{"name": str(n).strip()[:80], "role": None, "url": None, "note": None} for n in (r.get("people_public") or []) if len(str(n).split()) >= 2]
        disp, alias = split_name(str(r["name"]))
        about_raw = r.get("about") if isinstance(r.get("about"), list) else [r.get("about")]
        lab = {
            "orig_id": orig_id, "name": disp, "alias": alias, "full_name": str(r["name"]).strip(), "type": t,
            "founded": r.get("founded") if isinstance(r.get("founded"), int) else None,
            "country": str(r.get("country") or "").strip(), "city": str(r.get("city") or "").strip(),
            "lat": round(lat, 4), "lon": round(lon, 4),
            "website": site, "huggingface": clean_url(r.get("huggingface")), "github": clean_url(r.get("github")),
            "x": clean_url(r.get("x")), "discord": clean_url(r.get("discord")), "linkedin": clean_url(r.get("linkedin")),
            "contact_email": clean_email(r.get("contact_email")),
            "summary": str(r.get("summary") or "").strip(),
            "tagline": s_or_none(r.get("tagline"), 220),
            "about": [str(x).strip() for x in about_raw if x and str(x).strip()][:4],
            "mission": s_or_none(r.get("mission"), 900),
            "notice": s_or_none(r.get("notice"), 420),
            "known_for": [str(x).strip()[:160] for x in (r.get("known_for") or []) if str(x).strip()][:5],
            "focus": focus,
            "contributions": items(r, "contributions", ["title", "note", "year"], urlfield="_", limit=6, n=360),
            "github_highlights": items(r, "github_highlights", ["name", "url", "note"], limit=4, n=240),
            "hf_highlights": items(r, "hf_highlights", ["name", "url", "kind", "note"], limit=4, n=240),
            "papers": items(r, "papers", ["title", "url", "year"], limit=4, n=240),
            "notable_releases": rel,
            "openness": str(r.get("openness") or "").strip(),
            "key_people": people[:8],
            "discord_note": s_or_none(r.get("discord_note"), 240),
            "contact_note": s_or_none(r.get("contact_note"), 240),
            "sources": [u for u in (clean_url(s) for s in (r.get("sources") or [])) if u][:8],
            "confidence": r.get("confidence") if r.get("confidence") in ("high", "medium") else "medium",
        }
        lab["region"] = region_of(lab["country"])
        if not lab["summary"]:
            skipped.append((lab["name"], "no summary")); continue
        seen_id[orig_id] = True
        if dom: seen_dom[dom] = orig_id
        labs.append(lab)
    # friendly, unique URL slugs
    used = set()
    for l in sorted(labs, key=lambda x: x["name"].lower()):
        base = SLUG_OVERRIDES.get(l["orig_id"]) or slug(l["name"])
        s, i = base, 2
        while s in used:
            s = f"{base}-{i}"; i += 1
        used.add(s)
        l["id"] = s
    labs.sort(key=lambda l: l["name"].lower())
    return labs, skipped


PEOPLE = {}        # id -> person record (public fields only)
PEOPLE_BY_NAME = {}  # normalised real name -> id


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load_people(labs):
    lab_ids = {l["id"] for l in labs}
    PEOPLE.clear(); PEOPLE_BY_NAME.clear()
    for path in sorted(glob.glob("data/people/*.json")):
        try:
            r = json.load(open(path, encoding="utf-8"))
        except Exception as ex:
            print("!! cannot parse", path, ex, file=sys.stderr); continue
        pid = slug(r.get("id") or os.path.basename(path)[:-5])
        display = s_or_none(r.get("display") or r.get("name"), 80)
        if not display or not r.get("bio"): continue
        h = r.get("handles") or {}
        handles = {k: s_or_none(h.get(k), 200) for k in ("github", "huggingface", "x", "openalex", "orcid")}
        for k in ("scholar", "website", "linkedin"):
            handles[k] = clean_url(h.get(k))
        aff = []
        for a in (r.get("affiliations") or []):
            if isinstance(a, dict) and (a.get("org") or a.get("lab")):
                lab = a.get("lab") if a.get("lab") in lab_ids else None
                aff.append({"lab": lab, "org": s_or_none(a.get("org"), 120), "role": s_or_none(a.get("role"), 160),
                            "current": bool(a.get("current", True)), "since": a.get("since") if isinstance(a.get("since"), int) else None})
        act = {}
        ap = f"data/activity/{pid}.json"
        if os.path.exists(ap):
            try: act = json.load(open(ap, encoding="utf-8"))
            except Exception: act = {}
            used = act.get("handles")
            if used is not None and any((used.get(k) or "").lower() != (handles.get(k) or "").lower() for k in ("github", "huggingface", "openalex")):
                act = {}  # handles changed since the data was fetched: do not show another account's activity
        p = {"id": pid, "name": s_or_none(r.get("name"), 80), "display": display, "kind": "handle" if r.get("kind") == "handle" else "person",
             "handles": handles, "affiliations": aff, "independent": bool(r.get("independent")), "fame_basis": s_or_none(r.get("fame_basis"), 300),
             "bio": str(r["bio"]).strip()[:900], "known_for": [str(x).strip()[:140] for x in (r.get("known_for") or []) if str(x).strip()][:5],
             "sources": [u for u in (clean_url(s) for s in (r.get("bio_sources") or [])) if u][:8], "activity": act,
             "avatar": os.path.exists(f"assets/people/{pid}.png"), "contributor": bool(r.get("contributor")), "auto": bool(r.get("auto")), "enriched": bool(r.get("enriched"))}
        PEOPLE[pid] = p
        if p["name"]: PEOPLE_BY_NAME[norm(p["name"])] = pid
    return PEOPLE


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(d))


# ---------- icons (simple stroke glyphs, currentColor) ----------
ICONS = {
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
    "github": '<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="8" r="2.2"/><path d="M6 8.2v7.6M18 10.2c0 4-6 3-12 6"/>',
    "hf": '<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5c1 1.8 5 1.8 7 0M9 9.5h.01M15 9.5h.01"/>',
    "paper": '<path d="M7 3h8l4 4v14H7z"/><path d="M15 3v4h4M10 12h6M10 16h6"/>',
    "discord": '<path d="M5 6.5C7 5 9 4.5 9 4.5l.6 1.2a10 10 0 0 1 4.8 0L15 4.5s2 .5 4 2c1.4 3.5 1.8 7 1.5 10.5-1.4 1.4-3.2 2-3.2 2l-1-1.7M5 6.5C3.6 10 3.2 13.5 3.5 17c1.4 1.4 3.2 2 3.2 2l1-1.7"/><circle cx="9.2" cy="12" r="1.2"/><circle cx="14.8" cy="12" r="1.2"/>',
    "x": '<path d="M5 5l14 14M19 5L5 19"/>',
    "linkedin": '<rect x="4" y="4" width="16" height="16" rx="2.5"/><path d="M8.5 11v5M8.5 8.2v.01M12 16v-5M12 13c0-2 4-2.6 4 0v3"/>',
    "mail": '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
    "arrow": '<path d="M7 17L17 7M9 7h8v8"/>',
    "pin": '<path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
}


def icon(name, size=20):
    return f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'


def monogram(name):
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if not parts: return "?"
    if len(parts) == 1: return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def logo_html(l, cls="logo"):
    f = f"assets/logos/{l['id']}.png"
    if os.path.exists(f):
        return f'<span class="{cls}"><img src="/{f}" alt="" width="96" height="96" loading="lazy"></span>'
    hue = sum(ord(c) for c in l["name"]) % 40 + 28
    return f'<span class="{cls} mono" style="--h:{hue}" aria-hidden="true">{esc(monogram(l["name"]))}</span>'


def head(title, desc, path, extra="", image_id="home", image_alt=None, body_class=""):
    url = SITE + path
    img = f"{SITE}/assets/og/{image_id}.jpg"
    alt = image_alt or "Open Labs Atlas: a world map of independent AI labs committed to open source"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:site_name" content="Open Labs Atlas by Renaissance Labs">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{esc(url)}">
<meta property="og:locale" content="en_GB">
<meta property="og:image" content="{esc(img)}">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{esc(alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{esc(img)}">
<meta name="twitter:image:alt" content="{esc(alt)}">
<meta name="theme-color" content="#fdfaf3">
<link rel="icon" href="/assets/favicon.png">
<link rel="preload" href="/assets/fonts/fraunces-latin-opsz-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/styles.css">
{extra}</head>
<body{(' class="' + body_class + '"') if body_class else ""}>
<a class="skip" href="#main">Skip to content</a>
<header class="bar">
  <a class="brand" href="https://renaissancelabs.eu/"><img src="/assets/mark.png" alt="" width="28" height="28"><span>Renaissance Labs</span></a>
  <nav aria-label="Main">
    <a href="/">Atlas</a>
    <a href="/map/">Full map</a>
    <a href="/people/">People</a>
    <a href="/about/">About</a>
    <a href="https://renaissancelabs.eu/">Main site</a>
  </nav>
</header>
"""


def scripts():
    return """<script src="/assets/vendor/d3.min.js"></script>
<script src="/assets/vendor/topojson-client.min.js"></script>
<script src="/app.js" defer></script>
</body>
</html>
"""


def foot():
    return """<footer class="foot wrap">
  <p class="brand"><img src="/assets/mark.png" alt="" width="22" height="22"> Renaissance Labs · Open Labs Atlas · Made in Europe</p>
  <p class="foot-links"><a href="/labs.csv">Download data (CSV)</a><a href="https://discord.gg/6JUezWZbAm">Suggest a lab on Discord</a><a href="https://huggingface.co/RenaissanceLabsEU">Hugging Face</a><a href="https://github.com/BirgerMoell/renaissancelabs.eu">GitHub</a></p>
</footer>
<script src="/assets/vendor/d3.min.js"></script>
<script src="/assets/vendor/topojson-client.min.js"></script>
<script src="/app.js" defer></script>
</body>
</html>
"""


def ext(url, inner, cls=""):
    return f'<a class="{cls}" href="{esc(url)}" target="_blank" rel="noopener">{inner}</a>'


def short(u):
    p = urlparse(u)
    return (domain(u) + p.path.rstrip("/"))[:60]


def lab_page(l, labs):
    loc = ", ".join(x for x in (l["city"], l["country"]) if x)
    near = sorted((o for o in labs if o["id"] != l["id"]), key=lambda o: hav(l, o))[:4]
    tagline = l["tagline"] or l["summary"]
    about = l["about"] or ([l["summary"]] if l["tagline"] else [])

    acts = []
    if l["website"]: acts.append(ext(l["website"], f'Visit website {icon("arrow", 16)}', "btn"))
    for key, label, ic in (("github", "GitHub", "github"), ("huggingface", "Hugging Face", "hf"), ("discord", "Discord", "discord")):
        if l[key]: acts.append(ext(l[key], f'{icon(ic, 16)} {label}', "btn ghost"))
    tags = "".join(f'<span class="tag">{esc(f)}</span>' for f in l["focus"])

    stats = []
    if l["founded"]: stats.append(("Founded", str(l["founded"])))
    stats.append(("Type", TYPES[l["type"]]))
    stats.append(("Based in", loc or l["region"]))
    if l["papers"]: stats.append(("Key papers", str(len(l["papers"]))))
    feat = len(l["github_highlights"]) + len(l["hf_highlights"])
    if feat: stats.append(("Featured projects", str(feat)))
    stats_html = "".join(f'<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>' for k, v in stats)

    sections, toc = [], []

    def add(id_, title, body):
        toc.append((id_, title))
        sections.append(f'<section class="blk" id="{id_}"><h2>{esc(title)}</h2>{body}</section>')

    if about or l["mission"]:
        body = "".join(f"<p>{esc(p)}</p>" for p in about)
        if l["mission"]:
            body += f'<blockquote class="mission"><span class="eyebrow">Mission and ambitions</span><p>{esc(l["mission"])}</p></blockquote>'
        add("about", "About", f'<div class="prose-lg">{body}</div>')

    if l["known_for"]:
        add("known-for", "Known for", '<ol class="famous">' + "".join(f'<li><span class="n">{i:02d}</span><p>{esc(k)}</p></li>' for i, k in enumerate(l["known_for"], 1)) + "</ol>")

    if l["contributions"]:
        lis = ""
        for c in l["contributions"]:
            yr = f'<span class="yr">{esc(c["year"])}</span>' if c.get("year") else '<span class="yr dot"></span>'
            lis += f'<li>{yr}<div><h3>{esc(c["title"])}</h3>' + (f'<p>{esc(c["note"])}</p>' if c.get("note") else "") + "</div></li>"
        cls = "timeline" if any(c.get("year") for c in l["contributions"]) else "timeline noyear"
        add("milestones", "Milestones", f'<ol class="{cls}">{lis}</ol>')

    def panel(kind_cls, ic, title, hub, rows, kinds=False):
        if not rows and not hub: return ""
        if hub:
            head_ = ext(hub, f'{icon(ic, 22)}<span><b>{esc(title)}</b><small>{esc(short(hub))}</small></span>{icon("arrow", 16)}', "panel-head")
        else:
            head_ = f'<div class="panel-head">{icon(ic, 22)}<span><b>{esc(title)}</b></span></div>'
        lis = ""
        for r in rows:
            nm = r.get("name") or ""
            lead = ext(r["url"], esc(nm), "row-name") if r.get("url") else f'<span class="row-name">{esc(nm)}</span>'
            kind = f'<span class="kind">{esc(r["kind"])}</span>' if kinds and r.get("kind") else ""
            lis += f'<li><div class="row-top">{lead}{kind}</div>' + (f'<p>{esc(r["note"])}</p>' if r.get("note") else "") + "</li>"
        return f'<div class="panel {kind_cls}">{head_}<ul>{lis}</ul></div>'

    gh = panel("gh", "github", "GitHub", l["github"], l["github_highlights"])
    hf = panel("hf", "hf", "Hugging Face", l["huggingface"], l["hf_highlights"], kinds=True)
    if gh or hf:
        add("open-source", "Open source", f'<div class="panels">{gh}{hf}</div>')

    if l["papers"]:
        lis = ""
        for p in l["papers"]:
            t = ext(p["url"], esc(p["title"]), "paper-title") if p.get("url") else f'<span class="paper-title">{esc(p["title"])}</span>'
            lis += f'<li>{icon("paper", 22)}<div>{t}<small>{esc(p["year"]) if p.get("year") else ""}</small></div></li>'
        add("research", "Research papers", f'<ul class="papers">{lis}</ul>')

    if l["notable_releases"]:
        cards = ""
        for n in l["notable_releases"]:
            inner = f'<b>{esc(n["name"])}</b>' + (f'<span>{esc(n["note"])}</span>' if n["note"] else "")
            cards += ext(n["url"], inner + icon("arrow", 16), "release") if n["url"] else f'<div class="release">{inner}</div>'
        add("releases", "Notable releases", f'<div class="releases">{cards}</div>')

    if l["openness"]:
        add("openness", "Openness", f'<p class="open-note">{esc(l["openness"])}</p>')

    if l["key_people"] or any(a["lab"] == l["id"] and a["current"] for pr in PEOPLE.values() for a in pr["affiliations"]):
        cards = ""
        for p in l["key_people"]:
            av = f'<span class="avatar" aria-hidden="true">{esc(monogram(p["name"]))}</span>'
            pid = PEOPLE_BY_NAME.get(norm(p["name"]))
            if pid:
                nm = f'<a class="pname" href="/people/{esc(pid)}/">{esc(p["name"])}</a>'
            else:
                nm = ext(p["url"], esc(p["name"]), "pname") if p.get("url") else f'<span class="pname">{esc(p["name"])}</span>'
            role = f'<small>{esc(p["role"])}</small>' if p.get("role") else ""
            note = f'<p>{esc(p["note"])}</p>' if p.get("note") else ""
            cards += f'<li>{av}<div>{nm}{role}{note}</div></li>'
        seen = {norm(p["name"]) for p in l["key_people"]}
        for pr in sorted(PEOPLE.values(), key=lambda x: (1 if x.get("contributor") else 0, x["display"].lower())):
            if any(a["lab"] == l["id"] and a["current"] for a in pr["affiliations"]) and norm(pr["name"] or "") not in seen:
                a = next(a for a in pr["affiliations"] if a["lab"] == l["id"] and a["current"])
                tag = "handle" if pr["kind"] == "handle" else None
                cards += f'<li><span class="avatar" aria-hidden="true">{esc(monogram(pr["display"]))}</span><div><a class="pname" href="/people/{esc(pr["id"])}/">{esc(pr["display"])}</a>' + (f'<small>{esc(a["role"])}</small>' if a.get("role") else "") + '</div></li>'
        add("people", "People", f'<ul class="people-grid">{cards}</ul><p class="fine">Listed from the lab\'s own pages and public profiles.</p>')

    tiles = []

    def tile(ic, label, val, url):
        tiles.append(ext(url, f'{icon(ic, 22)}<span><b>{esc(label)}</b><small>{esc(val)}</small></span>{icon("arrow", 16)}', "tile"))
    if l["website"]: tile("globe", "Website", short(l["website"]), l["website"])
    if l["contact_email"]: tile("mail", "Email", l["contact_email"], "mailto:" + l["contact_email"])
    if l["discord"]: tile("discord", "Discord", short(l["discord"]), l["discord"])
    if l["github"]: tile("github", "GitHub", short(l["github"]), l["github"])
    if l["huggingface"]: tile("hf", "Hugging Face", short(l["huggingface"]), l["huggingface"])
    if l["x"]: tile("x", "X", short(l["x"]), l["x"])
    if l["linkedin"]: tile("linkedin", "LinkedIn", short(l["linkedin"]), l["linkedin"])
    notes = "".join(f"<p>{esc(n)}</p>" for n in (l["contact_note"], l["discord_note"]) if n)
    if tiles:
        add("contact", "Contact and community", f'<div class="notes">{notes}</div><div class="tiles">{"".join(tiles)}</div>')

    srcs = "".join(ext(s, esc(s)) for s in l["sources"])
    add("sources", "Sources", f'<div class="srcs">{srcs}</div><p class="fine">Compiled from the lab\'s public pages, Hugging Face and GitHub. Last checked {TODAY}. Something wrong or out of date? Tell us on <a href="https://discord.gg/6JUezWZbAm">Discord</a>.</p>')

    toc_html = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in toc)
    nearby = "".join(f'<a class="nb" href="/labs/{esc(o["id"])}/">{logo_html(o, "logo sm")}<span><b>{esc(o["name"])}</b><small>{esc(o["city"])}, {esc(o["country"])} · {int(hav(l, o)):,} km away</small></span></a>' for o in near)

    ld = {"@context": "https://schema.org", "@type": "Organization", "name": l["name"], "url": l["website"], "description": l["summary"],
          "address": {"@type": "PostalAddress", "addressLocality": l["city"], "addressCountry": l["country"]},
          "sameAs": [u for u in (l["huggingface"], l["github"], l["x"], l["linkedin"]) if u]}
    if l["founded"]: ld["foundingDate"] = str(l["founded"])
    extra = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c") + "</script>\n"
    alias = f'<span class="alias">{esc(l["alias"])}</span>' if l["alias"] else ""
    notice_html = f'<div class="wrap"><p class="notice"><b>Update</b> {esc(l["notice"])}</p></div>' if l["notice"] else ""

    social_img = l["id"] if os.path.exists(f"assets/og/{l['id']}.jpg") else "home"
    return head(f"{l['name']} · Open Labs Atlas", (tagline or "")[:200], f"/labs/{l['id']}/", extra, social_img,
                f"{l['name']}: {tagline}"[:300]) + f"""<main id="main" data-lab-page="{esc(l['id'])}">
  <section class="lab-hero">
    <div class="wrap hero-grid">
      <div class="hero-main">
        <p class="crumbs"><a href="/">Atlas</a> <span>/</span> <a href="/#{esc(l['id'])}">{esc(l['region'])}</a></p>
        <div class="id-row">{logo_html(l)}<p class="eyebrow"><span class="dot" style="background:{TYPE_COLOR[l['type']]}"></span>{esc(TYPES[l['type']])} · {esc(loc)}</p></div>
        <h1>{esc(l['name'])}{alias}</h1>
        <p class="lede">{esc(tagline)}</p>
        <div class="tags">{tags}</div>
        <div class="actions">{"".join(acts)}</div>
      </div>
      <div class="hero-map"><div class="mini" id="mini"></div><p class="pinlabel">{icon("pin", 14)} {esc(loc)}</p></div>
    </div>
    <div class="wrap"><dl class="stats-strip">{stats_html}</dl></div>
  </section>
  {notice_html}
  <div class="wrap lab-layout">
    <nav class="toc" aria-label="On this page"><span class="eyebrow">On this page</span>{toc_html}</nav>
    <div class="lab-body">{"".join(sections)}</div>
  </div>
  <section class="wrap nearby"><h2>Labs nearby</h2><div class="nb-grid">{nearby}</div></section>
</main>
""" + foot()


def card(l):
    loc = ", ".join(x for x in (l["city"], l["country"]) if x)
    hay = " ".join([l["name"], l["alias"] or "", l["city"], l["country"], l["region"], l["summary"], " ".join(l["focus"]), TYPES[l["type"]]]).lower()
    tags = "".join(f'<span class="tag">{esc(f)}</span>' for f in l["focus"][:3])
    return (f'<a class="card" href="/labs/{esc(l["id"])}/" data-id="{esc(l["id"])}" data-type="{esc(l["type"])}" '
            f'data-region="{esc(l["region"])}" data-focus="{esc("|".join(f.lower() for f in l["focus"]))}" data-search="{esc(hay)}">'
            f'<span class="card-top">{logo_html(l, "logo sm")}<span class="loc">{esc(TYPES[l["type"]])}<br>{esc(loc)}</span></span>'
            f'<h3>{esc(l["name"])}</h3><p>{esc(l["tagline"] or l["summary"])}</p><span class="tags">{tags}</span></a>')


def index_page(labs):
    regions = sorted({l["region"] for l in labs})
    order = ["Europe", "North America", "Latin America", "Asia", "Middle East", "Africa", "Oceania", "Other"]
    regions.sort(key=lambda r: order.index(r) if r in order else 99)
    countries = len({l["country"] for l in labs})
    foc = {}
    for l in labs:
        for f in l["focus"]:
            foc[f.lower()] = foc.get(f.lower(), 0) + 1
    top_focus = [f for f, _ in sorted(foc.items(), key=lambda kv: (-kv[1], kv[0])) if foc[f] >= 3][:40]
    type_counts = {t: sum(1 for l in labs if l["type"] == t) for t in TYPES}
    chips = '<button class="chip" data-type="all" aria-pressed="true">All</button>' + "".join(
        f'<button class="chip" data-type="{t}" aria-pressed="false">{esc(TYPES[t])}</button>' for t in TYPES if type_counts[t])
    ropts = '<option value="all">All regions</option>' + "".join(f'<option value="{esc(r)}">{esc(r)} ({sum(1 for l in labs if l["region"] == r)})</option>' for r in regions)
    fopts = '<option value="all">All focus areas</option>' + "".join(f'<option value="{esc(f)}">{esc(f)}</option>' for f in top_focus)
    legend = "".join(f'<span><i style="background:{TYPE_COLOR[t]}"></i>{esc(TYPES[t])}</span>' for t in TYPES if type_counts[t])
    cards = "".join(card(l) for l in labs)
    title = "Open Labs Atlas · Independent AI labs committed to open source"
    desc = f"A map and directory of {len(labs)} independent AI labs in {countries} countries that build in the open: open weights, open code, open data."
    return head(title, desc, "/") + f"""<main id="main">
  <section class="intro">
    <p class="eyebrow">Open Labs Atlas</p>
    <h1>The open frontier of intelligence.</h1>
    <p class="lede">A world map of independent labs releasing open weights, open code and open data, with a page for each.</p>
    <div class="stats">
      <div class="stat"><b>{len(labs)}</b><span>labs</span></div>
      <div class="stat"><b>{countries}</b><span>countries</span></div>
      <div class="stat"><b>{len(regions)}</b><span>regions</span></div>
    </div>
  </section>
  <div class="mapwrap">
    <div class="map" id="map">
      <div class="map-ui"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="zreset" aria-label="Reset view">⟲</button><a class="mbtn" href="/map/" title="Full-page map" aria-label="Open full-page map">⤢</a></div>
      <div class="legend" aria-hidden="true">{legend}</div>
      <div class="hint" id="hint" aria-hidden="true">Hold Ctrl or ⌘ and scroll to zoom</div>
      <div class="tip" id="tip" role="tooltip"></div>
      <div class="peek" id="peek" aria-live="polite"></div>
    </div>
  </div>
  <div class="toolbar">
    <div class="wrap">
      <div class="search"><input id="q" type="search" placeholder="Search labs, places, topics" aria-label="Search labs"></div>
      <div class="chips" role="group" aria-label="Type">{chips}</div>
      <select class="sel" id="region" aria-label="Region">{ropts}</select>
      <select class="sel" id="focus" aria-label="Focus area">{fopts}</select>
      <button class="chip" id="shuffle" type="button">Surprise me</button>
      <span class="count" id="count" aria-live="polite">{len(labs)} labs</span>
    </div>
  </div>
  <section class="list wrap">
    <div class="grid" id="grid">{cards}</div>
    <p class="empty" id="empty" hidden>No labs match. Try fewer filters.</p>
  </section>
</main>
""" + foot()


def map_page(labs):
    regions = sorted({l["region"] for l in labs})
    order = ["Europe", "North America", "Latin America", "Asia", "Middle East", "Africa", "Oceania", "Other"]
    regions.sort(key=lambda r: order.index(r) if r in order else 99)
    foc = {}
    for l in labs:
        for f in l["focus"]:
            foc[f.lower()] = foc.get(f.lower(), 0) + 1
    top_focus = [f for f, _ in sorted(foc.items(), key=lambda kv: (-kv[1], kv[0])) if foc[f] >= 3][:40]
    type_counts = {t: sum(1 for l in labs if l["type"] == t) for t in TYPES}
    chips = '<button class="chip" data-type="all" aria-pressed="true">All</button>' + "".join(
        f'<button class="chip" data-type="{t}" aria-pressed="false">{esc(TYPES[t])}</button>' for t in TYPES if type_counts[t])
    ropts = '<option value="all">All regions</option>' + "".join(f'<option value="{esc(r)}">{esc(r)} ({sum(1 for l in labs if l["region"] == r)})</option>' for r in regions)
    fopts = '<option value="all">All focus areas</option>' + "".join(f'<option value="{esc(f)}">{esc(f)}</option>' for f in top_focus)
    legend = "".join(f'<span><i style="background:{TYPE_COLOR[t]}"></i>{esc(TYPES[t])}</span>' for t in TYPES if type_counts[t])
    desc = f"Full-page world map of {len(labs)} independent AI labs committed to open source. Search, filter and zoom to find labs near you."
    return head("Full map · Open Labs Atlas", desc, "/map/", body_class="fullmap") + f"""<main id="main">
  <div class="map full" id="map" data-full data-free-zoom>
    <details class="fm-panel" open>
      <summary><span>Search and filters</span><span class="count" id="count" aria-live="polite">{len(labs)} labs</span></summary>
      <div class="fm-body">
        <input id="q" type="search" placeholder="Search labs, places, topics" aria-label="Search labs">
        <div class="chips" role="group" aria-label="Type">{chips}</div>
        <div class="fm-row"><select class="sel" id="region" aria-label="Region">{ropts}</select><select class="sel" id="focus" aria-label="Focus area">{fopts}</select></div>
        <div class="fm-row"><button class="chip" id="shuffle" type="button">Surprise me</button><a class="chip" href="/">List view</a></div>
      </div>
    </details>
    <div class="map-ui"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="zreset" aria-label="Reset view">⟲</button><a class="mbtn" href="/" title="Back to list" aria-label="Back to the list view">×</a></div>
    <div class="legend" aria-hidden="true">{legend}</div>
    <div class="tip" id="tip" role="tooltip"></div>
    <div class="peek" id="peek" aria-live="polite"></div>
  </div>
</main>
""" + scripts()


def about_page(labs):
    countries = len({l["country"] for l in labs})
    return head("About the Open Labs Atlas · Renaissance Labs", "How the Open Labs Atlas is compiled, what counts as an independent open source lab, and how to get listed.", "/about/") + f"""<main id="main" class="about wrap">
  <p class="eyebrow">About</p>
  <h1>An atlas of independent open AI.</h1>
  <div class="prose" style="margin-top:24px">
    <p>The Open Labs Atlas is a public directory by <a href="https://renaissancelabs.eu/">Renaissance Labs</a>. It lists {len(labs)} labs across {countries} countries that build AI in the open and are not owned by a big technology company. We made it because the people doing this work are scattered across Discord servers, Hugging Face orgs and small offices, and there was no single place to find them.</p>
    <h2>What counts</h2>
    <p>A lab is listed when it is independent (a nonprofit, an independent company, a community collective, an institute or a standalone academic lab), works on AI models, data, tooling or infrastructure, and has a public record of releasing open weights, open code or open datasets. We check this on its own website, Hugging Face and GitHub pages. Subsidiaries of large technology companies are left out.</p>
    <h2>Contact details and people</h2>
    <p>We only show channels the lab publishes itself: its website, Hugging Face and GitHub organisations, social accounts, and an organisation email address when the lab prints one on its own site. People are listed by name and role only when the lab or their own public profile makes that information public. We do not list personal email addresses or phone numbers.</p>
    <h2>Corrections and additions</h2>
    <p>Information changes quickly. If a lab is missing, wrong or out of date, tell us on <a href="https://discord.gg/6JUezWZbAm">Discord</a> or open an issue on <a href="https://github.com/BirgerMoell/renaissancelabs.eu">GitHub</a>. Labs and people can also ask to be removed. The full dataset is available as <a href="/labs.csv">CSV</a> and <a href="/data/labs.json">JSON</a>.</p>
  </div>
</main>
""" + foot()


SHADES = ["#efe6d2", "#f3e3b6", "#e6c46f", "#c79a3f", "#8c6a2a"]


def heatmap(cal):
    weeks = cal.get("weeks") or []
    if not weeks: return ""
    vals = sorted(v for w in weeks for v in w if v)
    qs = [vals[int(len(vals) * x)] for x in (0.25, 0.5, 0.75)] if vals else [0, 0, 0]
    def level(v):
        if not v: return 0
        return 1 if v <= qs[0] else 2 if v <= qs[1] else 3 if v <= qs[2] else 4
    cell, gap, top = 11, 3, 16
    w = len(weeks) * (cell + gap)
    out = []
    try:
        start = datetime.date.fromisoformat(cal.get("start"))
    except Exception:
        start = None
    last_m = None
    for x, wk in enumerate(weeks):
        if start:
            d = start + datetime.timedelta(days=7 * x)
            if d.month != last_m and (last_m is not None or d.day <= 7):
                out.append(f'<text x="{x*(cell+gap)}" y="10" font-size="10" fill="#958c80">{d.strftime("%b")}</text>')
            last_m = d.month
        for y, v in enumerate(wk):
            lv = level(v)
            xy = f'x="{x*(cell+gap)}" y="{top + y*(cell+gap)}"'
            out.append(f'<rect class="c{lv}" {xy}><title>{v}</title></rect>' if v else f'<rect class="c0" {xy}/>')
    h = top + 7 * (cell + gap)
    return f'<svg class="heat" viewBox="0 0 {w} {h}" role="img" aria-label="GitHub contributions over the past year">{"".join(out)}</svg>'


def bars(data, label):
    items = sorted((k, v) for k, v in (data or {}).items() if str(k).isdigit())[-10:]
    if not items: return ""
    mx = max(v for _, v in items) or 1
    bw, gap, hh = 34, 10, 86
    w = len(items) * (bw + gap)
    out = []
    for i, (k, v) in enumerate(items):
        bh = max(3, int(hh * v / mx))
        x = i * (bw + gap)
        out.append(f'<rect x="{x}" y="{hh-bh}" width="{bw}" height="{bh}" rx="4" fill="#c79a3f"><title>{k}: {v}</title></rect><text x="{x+bw/2}" y="{hh+16}" text-anchor="middle" font-size="11" fill="#958c80">{str(k)[2:]}</text>')
    return f'<svg class="bars" viewBox="0 0 {w} {hh+22}" role="img" aria-label="{esc(label)}">{"".join(out)}</svg>'


def fmt(n):
    try: n = int(n)
    except Exception: return "0"
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def person_page(p, labs_by_id):
    a = p["activity"] or {}
    gh, hf, pp = a.get("github"), a.get("huggingface"), a.get("papers")
    h = p["handles"]
    primary = next((x for x in p["affiliations"] if x["current"]), p["affiliations"][0] if p["affiliations"] else None)
    sub = []
    for x in p["affiliations"][:3]:
        lab = labs_by_id.get(x["lab"]) if x["lab"] else None
        org = x["org"] or ""
        org_html = f'<a href="/labs/{esc(lab["id"])}/">{esc(lab["name"])}</a>' if lab else ("" if org.strip().lower() in ("independent", "independent researcher", "") else esc(org))
        label = esc(x["role"] or "") + (" at " if x.get("role") and org_html else "") + org_html
        if not label.strip(): label = "Independent"
        sub.append(label)
    kind_badge = '<span class="pill">Handle</span>' if p["kind"] == "handle" else ('<span class="pill alt">Independent</span>' if p["independent"] else "")
    av = f'<span class="logo"><img src="/assets/people/{esc(p["id"])}.png" alt="" width="96" height="96"></span>' if p["avatar"] else f'<span class="logo mono" style="--h:{sum(ord(c) for c in p["display"]) % 40 + 28}" aria-hidden="true">{esc(monogram(p["display"]))}</span>'
    links = []
    def lk(ic, label, url):
        if url: links.append(ext(url, f'{icon(ic, 16)} {label}', "btn ghost"))
    if h.get("github"): lk("github", "GitHub", f'https://github.com/{h["github"]}')
    if h.get("huggingface"): lk("hf", "Hugging Face", f'https://huggingface.co/{h["huggingface"]}')
    if h.get("scholar"): lk("paper", "Scholar", h["scholar"])
    if h.get("x"): lk("x", "X", f'https://x.com/{h["x"]}')
    lk("globe", "Website", h.get("website")); lk("linkedin", "LinkedIn", h.get("linkedin"))
    sections = []
    sents = p["bio"].split(". ")
    about_text = ". ".join(sents[1:]) if len(sents) > 1 else p["bio"]
    sections.append(f'<section class="blk" id="about"><h2>About</h2><div class="prose-lg"><p>{esc(about_text)}</p></div>' + (f'<p class="fine" style="margin-top:14px">{esc(p["fame_basis"])}</p>' if p["independent"] and p["fame_basis"] else "") + '</section>')
    if p["known_for"]:
        sections.append('<section class="blk" id="known-for"><h2>Known for</h2><ol class="famous">' + "".join(f'<li><span class="n">{i:02d}</span><p>{esc(k)}</p></li>' for i, k in enumerate(p["known_for"], 1)) + "</ol></section>")
    act_html = ""
    if gh and gh.get("calendar") and gh["calendar"].get("weeks"):
        c = gh["calendar"]
        repos = "".join(f'<li><div class="row-top">{ext(r["url"], esc(r["name"]), "row-name")}<span class="kind">&#9733; {fmt(r["stars"])}</span></div>' + (f'<p>{esc(r["description"])}</p>' if r.get("description") else "") + "</li>" for r in gh["top_repos"][:5] if r.get("stars"))
        langs = "".join(f'<span class="tag">{esc(x)}</span>' for x in gh.get("languages", []))
        act_html += f'<div class="act-card"><div class="act-head">{icon("github", 22)}<div><b>GitHub</b><small>{fmt(c["total"])} public contributions in the past year · {fmt(gh["followers"])} followers</small></div></div>{heatmap(c)}' + (f'<div class="tags" style="margin-top:14px">{langs}</div>' if langs else "") + (f'<ul class="mini-list">{repos}</ul>' if repos else "") + "</div>"
    if hf:
        top = "".join(f'<li><div class="row-top">{ext(t["url"], esc(t["name"]), "row-name")}<span class="kind">{esc(t["kind"])}</span></div><p>{fmt(t.get("downloads"))} downloads · {fmt(t.get("likes"))} likes</p></li>' for t in hf.get("top", [])[:4])
        act_html += f'<div class="act-card"><div class="act-head">{icon("hf", 22)}<div><b>Hugging Face</b><small>{fmt(hf.get("models"))} models · {fmt(hf.get("datasets"))} datasets · {fmt(hf.get("spaces"))} spaces · {fmt(hf.get("followers"))} followers</small></div></div>{bars(hf.get("created_by_year"), "Repositories created per year")}<p class="fine" style="margin-top:6px">Repositories created per year</p>' + (f'<ul class="mini-list">{top}</ul>' if top else "") + "</div>"
    if pp and pp.get("works"):
        tw = "".join(f'<li><div class="row-top">' + (ext(t["url"], esc(t["title"]), "row-name") if t.get("url") else f'<span class="row-name">{esc(t["title"])}</span>') + f'<span class="kind">{esc(t.get("year") or "")}</span></div><p>{fmt(t.get("cited_by"))} citations</p></li>' for t in pp.get("top_works", [])[:4] if t.get("title"))
        act_html += f'<div class="act-card"><div class="act-head">{icon("paper", 22)}<div><b>Research</b><small>{fmt(pp["works"])} works · {fmt(pp["cited_by"])} citations · h-index {pp.get("h_index") or "n/a"} (OpenAlex)</small></div></div>{bars(pp.get("works_by_year"), "Works per year")}<p class="fine" style="margin-top:6px">Works per year</p>' + (f'<ul class="mini-list">{tw}</ul>' if tw else "") + "</div>"
    if act_html:
        sections.append(f'<section class="blk" id="activity"><h2>Activity</h2><div class="acts">{act_html}</div><p class="fine">Public data only, fetched {esc(a.get("fetched") or "")}. GitHub counts cover public contributions; Hugging Face counts are repositories created; research data comes from OpenAlex.</p></section>')
    labs_html = ""
    rel = [x for x in p["affiliations"] if x["lab"] and x["lab"] in labs_by_id]
    if rel:
        labs_html = '<section class="blk" id="labs"><h2>Labs</h2><div class="nb-grid">' + "".join(
            f'<a class="nb" href="/labs/{esc(x["lab"])}/">{logo_html(labs_by_id[x["lab"]], "logo sm")}<span><b>{esc(labs_by_id[x["lab"]]["name"])}</b><small>{esc(x.get("role") or "")}{(" · since " + str(x["since"])) if x.get("since") else ""}</small></span></a>' for x in rel) + "</div></section>"
        sections.append(labs_html)
    srcs = "".join(ext(s, esc(s)) for s in p["sources"])
    sections.append(f'<section class="blk" id="sources"><h2>Sources</h2><div class="srcs">{srcs}</div><p class="fine">Compiled from public sources. Something wrong, or would you like this page changed or removed? Tell us on <a href="https://discord.gg/6JUezWZbAm">Discord</a> or open an issue on <a href="https://github.com/RenaissanceLabs-EU/labs-atlas/issues">GitHub</a> and we will act promptly.</p></section>')
    toc = [("about", "About")] + ([("known-for", "Known for")] if p["known_for"] else []) + ([("activity", "Activity")] if act_html else []) + ([("labs", "Labs")] if rel else []) + [("sources", "Sources")]
    toc_html = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in toc)
    ld = {"@context": "https://schema.org", "@type": "Person", "name": p["name"] or p["display"], "description": p["bio"][:300],
          "sameAs": [u for u in ([f'https://github.com/{h["github"]}'] if h.get("github") else []) + ([f'https://huggingface.co/{h["huggingface"]}'] if h.get("huggingface") else []) + [h.get("scholar"), h.get("website"), h.get("linkedin")] if u]}
    if primary and primary.get("org"): ld["jobTitle"] = primary.get("role") or None
    extra = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c") + "</script>\n"
    handle_line = f'<span class="handle">@{esc(h.get("github") or h.get("huggingface"))}</span>' if p["kind"] == "handle" and (h.get("github") or h.get("huggingface")) else ""
    return head(f'{p["display"]} · Open Labs Atlas', p["bio"][:200], f'/people/{p["id"]}/', extra) + f"""<main id="main">
  <section class="lab-hero person-hero">
    <div class="wrap" style="padding-top:clamp(28px,5vh,56px);padding-bottom:clamp(28px,5vh,48px)">
      <p class="crumbs"><a href="/people/">People</a></p>
      <div class="id-row">{av}<p class="eyebrow">{" · ".join(sub) if sub else "Independent"}</p></div>
      <h1>{esc(p["display"])} {kind_badge}</h1>
      {handle_line}
      <p class="lede">{esc(p["bio"].split(". ")[0].rstrip(".") + ".")}</p>
      <div class="actions">{"".join(links)}</div>
    </div>
  </section>
  <div class="wrap lab-layout">
    <nav class="toc" aria-label="On this page"><span class="eyebrow">On this page</span>{toc_html}</nav>
    <div class="lab-body">{"".join(sections)}</div>
  </div>
</main>
""" + foot()


def people_index(labs_by_id):
    cards = []
    def rank(x):
        if x.get("contributor"): return 2
        return 0 if (x.get("enriched") or not x.get("auto")) else 1
    for p in sorted(PEOPLE.values(), key=lambda x: (rank(x), x["display"].lower())):
        a = (p["activity"] or {})
        aff = next((x for x in p["affiliations"] if x["current"]), p["affiliations"][0] if p["affiliations"] else None)
        lab = labs_by_id.get(aff["lab"]) if aff and aff["lab"] else None
        where = (lab["name"] if lab else (aff["org"] if aff else "")) or ""
        role = (aff or {}).get("role") or ""
        kind = "handle" if p["kind"] == "handle" else "independent" if p["independent"] else "contributor" if p.get("contributor") else "lab"
        av = f'<span class="logo sm"><img src="/assets/people/{esc(p["id"])}.png" alt="" width="46" height="46" loading="lazy"></span>' if p["avatar"] else f'<span class="logo sm mono" style="--h:{sum(ord(c) for c in p["display"]) % 40 + 28}" aria-hidden="true">{esc(monogram(p["display"]))}</span>'
        spark = ""
        cal = (a.get("github") or {}).get("calendar")
        if cal and cal.get("weeks"):
            tot = [sum(w) for w in cal["weeks"]]
            mx = max(tot) or 1
            pts = " ".join(f"{i*3},{22 - int(20*t/mx)}" for i, t in enumerate(tot))
            spark = f'<svg class="spark" viewBox="0 0 {len(tot)*3} 24" preserveAspectRatio="none" aria-hidden="true"><polyline points="{pts}" fill="none" stroke="#c79a3f" stroke-width="1.6"/></svg>'
        hay = " ".join([p["display"], p["name"] or "", where, role, p["bio"], " ".join(p["known_for"])]).lower()
        cards.append(f'<a class="card pcard" href="/people/{esc(p["id"])}/" data-kind="{kind}" data-search="{esc(hay)}"><span class="card-top">{av}<span class="loc">{esc(where) or "Independent"}<br>{esc(role)[:60]}</span></span><h3>{esc(p["display"])}</h3><p>{esc(p["bio"])}</p>{spark}</a>')
    n = len(PEOPLE)
    return head("People · Open Labs Atlas", f"{n} people behind open AI: founders, researchers, maintainers and independent builders, with their public GitHub, Hugging Face and research activity.", "/people/") + f"""<main id="main">
  <section class="intro" style="padding-bottom:20px">
    <p class="eyebrow">People</p>
    <h1>The people building the open frontier of intelligence.</h1>
    <p class="lede">Founders, researchers, maintainers and independent builders, with what they have shipped in public.</p>
  </section>
  <div class="toolbar"><div class="wrap">
    <div class="search"><input id="pq" type="search" placeholder="Search people, labs, topics" aria-label="Search people"></div>
    <div class="chips" role="group" aria-label="Group">
      <button class="chip" data-pk="all" aria-pressed="true">All</button><button class="chip" data-pk="lab" aria-pressed="false">Leaders and researchers</button><button class="chip" data-pk="contributor" aria-pressed="false">Contributors</button><button class="chip" data-pk="independent" aria-pressed="false">Independent</button><button class="chip" data-pk="handle" aria-pressed="false">Handles</button>
    </div>
    <span class="count" id="pcount">{n} people</span>
  </div></div>
  <section class="list wrap"><div class="grid" id="pgrid">{"".join(cards)}</div><p class="empty" id="pempty" hidden>No one matches.</p><p style="text-align:center;margin-top:28px"><button class="btn ghost" id="pmore" type="button" hidden>Show more people</button></p></section>
</main>
""" + foot()


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    labs, skipped = load()
    if not labs:
        print("no labs found in data/regions/*.json"); sys.exit(1)
    shutil.rmtree("labs", ignore_errors=True)
    shutil.rmtree("people", ignore_errors=True)
    load_people(labs)
    # labs that share (almost) the same city point get a small ring offset for the map only (mlat/mlon)
    import collections
    groups = collections.defaultdict(list)
    for l in labs:
        groups[(round(l["lat"], 2), round(l["lon"], 2))].append(l)
    for g in groups.values():
        if len(g) < 2: continue
        g.sort(key=lambda x: x["id"])
        r = min(0.12, 0.025 * math.sqrt(len(g)))
        for i, l in enumerate(g):
            ang = 2 * math.pi * i / len(g) - math.pi / 2
            l["mlat"] = round(l["lat"] + r * math.sin(ang), 5)
            l["mlon"] = round(l["lon"] + r * math.cos(ang) / max(0.2, math.cos(math.radians(l["lat"]))), 5)
    for l in labs:
        l["logo"] = os.path.exists(f"assets/logos/{l['id']}.png")
    write("data/labs.json", json.dumps({"generated": TODAY, "count": len(labs), "labs": labs}, ensure_ascii=False, indent=1))
    cols = ["id", "name", "type", "founded", "country", "city", "region", "lat", "lon", "website", "huggingface", "github", "x", "discord", "linkedin", "contact_email", "summary", "focus", "openness"]
    with open("labs.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for l in labs:
            w.writerow([("; ".join(l[c]) if c == "focus" else l[c]) for c in cols])
    write("index.html", index_page(labs))
    write("about/index.html", about_page(labs))
    write("map/index.html", map_page(labs))
    labs_by_id = {l["id"]: l for l in labs}
    if PEOPLE:
        write("people/index.html", people_index(labs_by_id))
        for p in PEOPLE.values():
            write(f"people/{p['id']}/index.html", person_page(p, labs_by_id))
    for l in labs:
        write(f"labs/{l['id']}/index.html", lab_page(l, labs))
    urls = ["/", "/map/", "/about/"] + (["/people/"] + [f"/people/{i}/" for i in PEOPLE] if PEOPLE else []) + [f"/labs/{l['id']}/" for l in labs]
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
          "".join(f"<url><loc>{SITE}{u}</loc><lastmod>{TODAY}</lastmod></url>\n" for u in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    write("llms.txt", "# Open Labs Atlas\n\n> Directory of independent AI labs committed to open source, by Renaissance Labs.\n\n" +
          "".join(f"- [{l['name']}]({SITE}/labs/{l['id']}/): {(l['tagline'] or l['summary'])[:140]}\n" for l in labs))
    write("CNAME", DOMAIN)
    write("_headers", "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'\n")
    print(f"built {len(labs)} labs; skipped {len(skipped)}")
    for n, why in skipped:
        print("  skipped:", n, "-", why)


if __name__ == "__main__":
    main()
