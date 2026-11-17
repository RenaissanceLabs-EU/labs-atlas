#!/usr/bin/env python3
"""Turn resolved candidates and detected contributors into data/people/<id>.json records.

Rules:
  - A resolved person gets a page only if at least one identity is verified (GitHub, Hugging Face, OpenAlex, Scholar).
  - Bios are factual templates built from the role the lab lists and the lab's own note; leadership people are also
    written to data/people-tierA.json so researched bios can replace the template (see tools/people_enrich brief).
  - Contributors come from the lab's own non-fork repos. A display name is used only when the GitHub profile states a
    real-looking name; otherwise the handle is shown and the record is marked kind "handle".
Existing records in data/people/ are never overwritten. Usage: python3 tools/people_generate.py
"""
import glob, json, os, re, unicodedata, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def strip_accents(s): return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
def norm(s): return re.sub(r"[^a-z0-9]+", " ", strip_accents(s).lower()).strip()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", strip_accents(s).lower()).strip("-") or "person"

labs = {l["id"]: l for l in json.load(open("data/labs.json"))["labs"]}
existing_files = {os.path.basename(f)[:-5] for f in glob.glob("data/people/*.json")}
existing_names, existing_gh = set(), set()
for f in glob.glob("data/people/*.json"):
    p = json.load(open(f))
    for n in (p.get("name"), p.get("display")):
        if n: existing_names.add(norm(n))
    g = (p.get("handles") or {}).get("github")
    if g: existing_gh.add(g.lower())

LEAD = re.compile(r"founder|ceo|cto|coo|chief|head of|director|lead\b|leader|professor|principal|president|executive|creator|maintainer|pi\b|senior|distinguished|vice", re.I)
made, tierA, skipped = 0, [], 0
used = set(existing_files)

def unique(base):
    s, i = base, 2
    while s in used: s = f"{base}-{i}"; i += 1
    used.add(s); return s

# ---- resolved people
for r in json.load(open("data/people-resolved.json")):
    h = r["handles"]
    if not (h.get("github") or h.get("huggingface") or r["openalex"] or h.get("scholar")):
        skipped += 1; continue
    if norm(r["name"]) in existing_names: continue
    aff = []
    for a in r["affiliations"]:
        aff.append({"lab": a["lab"], "org": a["lab_name"], "role": a.get("role"), "current": True, "since": None})
    first = r["affiliations"][0]
    role = (first.get("role") or "").strip()
    lab_name = first["lab_name"]
    bio = f"{r['name']} is listed by {lab_name} as {role[0].lower() + role[1:] if role else 'part of its team'}." if role else f"{r['name']} is listed as part of the team at {lab_name}."
    if len(r["affiliations"]) > 1:
        bio += " They are also listed at " + ", ".join(a["lab_name"] for a in r["affiliations"][1:3]) + "."
    note = (first.get("note") or "").strip()
    if note and len(note) < 220 and not note.lower().startswith(("listed", "named")):
        bio += " " + (note if note.endswith(".") else note + ".")
    srcs = [labs[a["lab"]]["website"] for a in r["affiliations"] if labs.get(a["lab"]) and labs[a["lab"]]["website"]]
    srcs += [e.split(": ", 1)[1] for e in r["evidence"] if e.startswith(("linked on lab page: ", "personal page: "))]
    if r["openalex"]: srcs.append(r["openalex"]["evidence_paper"])
    srcs = list(dict.fromkeys(srcs))[:6]
    pid = unique(slug(r["name"]))
    rec = {"id": pid, "name": r["name"], "display": r["name"], "kind": "person",
           "handles": {"github": h.get("github"), "huggingface": h.get("huggingface"), "x": h.get("x"),
                       "openalex": r["openalex"]["id"] if r["openalex"] else None, "orcid": None, "scholar": h.get("scholar"),
                       "website": h.get("website"), "linkedin": h.get("linkedin")},
           "affiliations": aff, "independent": False, "fame_basis": None, "bio": bio, "known_for": [], "bio_sources": srcs,
           "confidence": "high" if len(r["evidence"]) >= 2 else "medium", "auto": True}
    json.dump(rec, open(f"data/people/{pid}.json", "w"), ensure_ascii=False, indent=1)
    made += 1
    existing_names.add(norm(r["name"]))
    if h.get("github"): existing_gh.add(h["github"].lower())
    if LEAD.search(role) or any(LEAD.search(a.get("role") or "") for a in r["affiliations"]):
        tierA.append({"id": pid, "name": r["name"], "labs": [a["lab_name"] for a in r["affiliations"]], "role": role, "handles": rec["handles"], "evidence": r["evidence"], "sources": srcs})

# ---- contributors
cmade = 0
REAL = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+( [A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+){1,3}$")
for c in json.load(open("data/contributors.json")):
    if c["login"].lower() in existing_gh: continue
    name = (c.get("name") or "").strip()
    real = bool(REAL.match(name)) and len(name.split()) >= 2
    if real and norm(name) in existing_names: continue
    display = name if real else c["login"]
    top = max(c["labs"], key=lambda x: x["contributions"])
    lab = labs.get(top["lab"])
    if not lab: continue
    repos = ", ".join(f'{x["repo"].split("/")[1]}' for x in sorted(top["repos"], key=lambda y: -y["contributions"])[:2])
    n = top["contributions"]
    bio = f"{display} is one of the most active contributors to {lab['name']}'s open source work on GitHub, with {n:,} contributions to {repos}."
    bio_prof = (c.get("bio") or "").strip()
    if bio_prof and len(bio_prof) <= 160 and "@" not in bio_prof and "http" not in bio_prof:
        bio += f" Their public GitHub profile reads: “{bio_prof.rstrip('.')}”."
    pid = unique(slug(display if real else c["login"]))
    rec = {"id": pid, "name": name if real else None, "display": display, "kind": "person" if real else "handle",
           "handles": {"github": c["login"], "huggingface": None, "x": c.get("x"), "openalex": None, "orcid": None, "scholar": None,
                       "website": None, "linkedin": None},
           "affiliations": [{"lab": x["lab"], "org": labs[x["lab"]]["name"], "role": f'Top contributor to {x["repos"][0]["repo"].split("/")[1]}', "current": True, "since": None} for x in c["labs"] if x["lab"] in labs][:3],
           "independent": False, "fame_basis": None, "bio": bio, "known_for": [],
           "bio_sources": [f'https://github.com/{c["login"]}'] + [f'https://github.com/{x["repo"]}' for x in top["repos"][:2]],
           "confidence": "medium", "auto": True, "contributor": True}
    json.dump(rec, open(f"data/people/{pid}.json", "w"), ensure_ascii=False, indent=1)
    cmade += 1
    existing_gh.add(c["login"].lower())
    if real: existing_names.add(norm(name))

if tierA: json.dump(tierA, open("data/people-tierA.json", "w"), ensure_ascii=False, indent=1)
print(f"people records: {made} resolved (skipped {skipped} without a verified identity), {cmade} contributors; tier A (leadership) {len(tierA)}")
