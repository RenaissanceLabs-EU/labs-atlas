#!/usr/bin/env python3
"""Build a static RSS and JSON feed from the Renaissance Labs Atlas."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SITE = "https://labs.renaissancelabs.eu/"
NS = "https://labs.renaissancelabs.eu/ns/stream"
ATOM = "http://www.w3.org/2005/Atom"
LIMIT = 8 * 1024 * 1024
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid"}
NOW = datetime.now(timezone.utc)
PAPERS = {"id": "daily-papers", "name": "Daily Papers"}
PAPER_SOURCE = "https://huggingface.co/api/daily_papers?limit=40"


def url(value):
    parsed = urlsplit(value or "")
    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
        return value
    return ""


def account(value, host):
    parsed = urlsplit(value or "")
    if parsed.hostname in {host, "www." + host}:
        parts = parsed.path.strip("/").split("/")
        if all(re.fullmatch(r"[\w.-]+", part, re.ASCII) for part in parts):
            return parts
    return []


def get(address):
    if not url(address):
        raise ValueError("invalid source URL")
    request = Request(address, headers={"User-Agent": "RenaissanceLabsFeed/1.0"})
    with urlopen(request, timeout=8) as response:
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("source exceeds size limit")
        return data, response.geturl()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        file.write(data)
    Path(file.name).replace(path)
    path.chmod(0o644)


def write_json(path, value):
    write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def timestamp(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, IndexError):
            return None
    return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(timezone.utc)


def item(title, link, date):
    return {"title": " ".join(title.split()), "url": link, "published": date}


def canonical(link):
    parsed = urlsplit(link)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in TRACKING]
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/") or "/",
                       urlencode(sorted(query)), ""))


class FeedLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        fields = {key: value or "" for key, value in attrs}
        if tag == "link" and "alternate" in fields.get("rel", "").lower().split():
            if fields.get("type", "").lower() in {"application/rss+xml", "application/atom+xml"}:
                self.links.append(fields.get("href", ""))


def syndicated(data, address):
    root = ET.fromstring(data)
    tag = root.tag.rsplit("}", 1)[-1]
    if tag not in {"rss", "RDF", "feed"}:
        raise ValueError("expected RSS or Atom")
    xml_base = "{http://www.w3.org/XML/1998/namespace}base"
    container = root.find("{*}channel") if tag == "rss" else root
    if container is None:
        raise ValueError("RSS channel missing")
    base = urljoin(address, root.get(xml_base, ""))
    if container is not root:
        base = urljoin(base, container.get(xml_base, ""))
    entries = []
    for node in container.findall("{*}entry" if tag == "feed" else "{*}item"):
        links = node.findall("{*}link")
        link = next((link for link in links if link.get("rel", "alternate") == "alternate"), None)
        if link is None:
            continue
        href = link.get("href") or link.text or ""
        if not href.strip():
            continue
        entry_base = urljoin(base, node.get(xml_base, ""))
        date_fields = ("published", "updated") if tag == "feed" else ("pubDate", "date")
        date = next((d for field in date_fields if (d := node.findtext("{*}" + field))), None)
        entry = item(node.findtext("{*}title", ""),
                     urljoin(urljoin(entry_base, link.get(xml_base, "")), href.strip()), date)
        entries.append(entry)
    return entries


def fetch(kind, address):
    data, final_url = get(address)
    if kind == "paper":
        entries = []
        for record in json.loads(data):
            paper = record["paper"]
            identifier = paper["id"]
            if not re.fullmatch(r"[0-9]{4}\.[0-9]{4,5}", identifier):
                continue
            entry = item(paper["title"], f"https://arxiv.org/abs/{identifier}", paper["publishedAt"])
            entry["paper_votes"] = paper.get("upvotes") or 0
            entry["has_code"] = bool(paper.get("githubRepo") or paper.get("projectPage"))
            entries.append(entry)
        return entries
    if kind == "discover":
        parser = FeedLinks()
        parser.feed(data.decode("utf-8", errors="replace"))
        return list(dict.fromkeys(link for href in parser.links
                                 if href and (link := url(urljoin(final_url, href)))))[:3]
    if kind in {"model", "dataset"}:
        prefix = "datasets/" if kind == "dataset" else ""
        return [item(entry["id"], "https://huggingface.co/" + prefix + entry["id"],
                     entry.get("createdAt"))
                for entry in json.loads(data) if entry.get("id")]
    return syndicated(data, final_url)


def sources(lab, config):
    for kind in ("model", "dataset"):
        owner = account(lab.get("huggingface"), "huggingface.co")
        if len(owner) == 1:
            query = urlencode({"author": owner[0], "sort": "createdAt", "direction": -1, "limit": 12})
            yield kind, f"https://huggingface.co/api/{kind}s?{query}"

    configured = config.get(lab["id"], {})
    fresh = lab.get("fresh") or {}
    repositories = [lab.get("github"), (fresh.get("latest_repo") or {}).get("url")]
    repositories.extend(entry.get("url") for entry in (lab.get("github_highlights") or [])[:3])
    repositories.extend(configured.get("github", []))
    org = account(lab.get("github"), "github.com")[:1]
    for repo in repositories:
        parts = account(repo, "github.com")
        if len(parts) >= 2 and (not org or parts[0].lower() == org[0].lower()
                                or repo in configured.get("github", [])):
            yield "release", f"https://github.com/{parts[0].lower()}/{parts[1].lower()}/releases.atom"

    for kind in ("blog", "media"):
        for address in configured.get(kind, []):
            yield kind, address
    if url(lab.get("website")) and not configured.get("blog"):
        yield "discover", lab["website"]


def snapshot(lab):
    fresh = lab.get("fresh") or {}
    latest = fresh.get("latest") or {}
    repo = fresh.get("latest_repo") or {}
    if latest.get("name") and latest.get("kind") in {"model", "dataset", "space"}:
        yield latest["kind"], item(latest["name"], latest.get("url"), latest.get("date"))
    if repo.get("name"):
        yield "repository_activity", item(repo["name"], repo.get("url"), repo.get("pushed"))


def collect(labs, config, cache, workers, offline, include_papers=True):
    by_id = {lab["id"]: lab for lab in labs}
    owners = defaultdict(set)
    for lab in labs:
        for source in sources(lab, config):
            owners[source].add(lab["id"])

    if include_papers:
        by_id[PAPERS["id"]] = PAPERS
        owners["paper", PAPER_SOURCE].add(PAPERS["id"])

    def read(source):
        kind, address = source
        key = sha256(repr(source).encode()).hexdigest()
        path = cache / (key + ".json")
        prior = json.loads(path.read_bytes()) if path.exists() else None
        if offline or (prior and NOW - timestamp(prior["fetched"]) < timedelta(hours=3)):
            return (prior["items"], "cached") if prior else ([], "skipped")
        try:
            entries = fetch(kind, address)
        except (OSError, ValueError, TypeError, KeyError, ET.ParseError):
            return (prior["items"], "stale") if prior else ([], "failed")
        write_json(path, {"fetched": NOW.isoformat(), "items": entries})
        return entries, "live"

    health = Counter()
    feed_entries = []

    def record(source, values, status):
        kind, address = source
        health[kind, status] += 1
        if kind == "discover":
            return
        if address == "https://huggingface.co/blog/feed.xml":
            # Community posts use /blog/<publisher>/<slug>.
            values = [entry for entry in values
                      if len(urlsplit(entry["url"]).path.strip("/").split("/")) == 2]
        for lab_id in sorted(owners[source]):
            feed_entries.extend((by_id[lab_id], kind, address, entry) for entry in values)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        initial = list(owners)
        initial_set = set(initial)
        for source, (values, status) in zip(initial, pool.map(read, initial)):
            record(source, values, status)
            if source[0] == "discover":
                for address in values:
                    blog = ("blog", address)
                    if blog not in initial_set:
                        owners[blog].update(owners[source])
        discovered = [source for source in owners if source not in initial_set]
        for source, (values, status) in zip(discovered, pool.map(read, discovered)):
            record(source, values, status)

    for lab in labs:
        feed_entries.extend((lab, kind, None, entry) for kind, entry in snapshot(lab))
    return feed_entries, health


def curated(labs, path, include_papers=True):
    by_id = {lab["id"]: lab for lab in labs}
    if include_papers:
        by_id[PAPERS["id"]] = PAPERS
    for post in json.loads(path.read_bytes()):
        lab = by_id.get(post["lab_id"])
        if lab is None:
            continue
        summary = post["summary"].strip()
        if not summary or summary.casefold() == post["title"].strip().casefold():
            raise ValueError(f"Highlight needs an original summary: {post['url']}")
        yield lab, post["kind"], None, {
            **item(post["title"], post["url"], post["published"]),
            "summary": summary, "highlight": True,
        }


def select(entries, days, limit):
    unique = {}
    for lab, kind, source, entry in entries:
        link = url(entry["url"])
        date = timestamp(entry["published"])
        if not link or not entry["title"] or not date:
            continue
        if not NOW - timedelta(days=days) <= date <= NOW + timedelta(days=1):
            continue
        identity = canonical(link)
        previous = unique.get(identity)
        priority = (bool(entry.get("highlight")), bool(source), date.isoformat())
        if previous and priority <= (previous["highlight"], bool(previous["source_url"]), previous["published"]):
            if kind == "paper" and source:
                previous.update(paper_votes=entry["paper_votes"], has_code=entry["has_code"])
            continue
        unique[identity] = {
            **item(entry["title"], link, date.isoformat()),
            "highlight": bool(entry.get("highlight")), "kind": kind,
            "lab_id": lab["id"], "lab_name": lab["name"], "source_url": source,
            "id": "urn:sha256:" + sha256(identity.encode()).hexdigest(),
        }
        if entry.get("highlight"):
            unique[identity]["summary"] = entry["summary"]
        if kind == "paper":
            unique[identity].update(
                paper_votes=entry.get("paper_votes", (previous or {}).get("paper_votes", 0)),
                has_code=entry.get("has_code", (previous or {}).get("has_code", False)),
            )
    counts = Counter()
    by_kind = Counter()
    selected = []
    ordered = sorted(unique.values(), key=lambda entry: (entry["highlight"], entry["kind"] == "paper", entry["published"], entry["id"]), reverse=True)
    for entry in ordered:
        lab = entry["lab_id"]
        pair = (lab, entry["kind"])
        lab_cap, category_cap = (24, 24) if lab == PAPERS["id"] else (5, 2)
        if entry["highlight"] or (counts[lab] < lab_cap and by_kind[pair] < category_cap):
            counts[lab] += 1
            by_kind[pair] += 1
            selected.append(entry)
        if len(selected) == limit:
            break
    return sorted(selected, key=lambda entry: (entry["published"], entry["id"]), reverse=True)


def rss(entries, feed_url):
    ET.register_namespace("rl", NS)
    ET.register_namespace("atom", ATOM)
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Renaissance Labs Updates"
    ET.SubElement(channel, "link").text = SITE
    ET.SubElement(channel, "description").text = (
        "Releases, publications, and updates from labs in the Renaissance Labs Atlas."
    )
    if feed_url:
        ET.SubElement(channel, f"{{{ATOM}}}link", href=feed_url, rel="self", type="application/rss+xml")
    for entry in entries:
        node = ET.SubElement(channel, "item")
        title = entry["title"]
        if entry["kind"] == "repository_activity":
            title = "Repository activity in " + title
        ET.SubElement(node, "title").text = f'{entry["lab_name"]} · {title}'
        ET.SubElement(node, "link").text = entry["url"]
        ET.SubElement(node, "guid", isPermaLink="false").text = entry["id"]
        ET.SubElement(node, "pubDate").text = format_datetime(timestamp(entry["published"]), usegmt=True)
        ET.SubElement(node, "category").text = entry["kind"]
        if entry.get("summary"):
            ET.SubElement(node, "description").text = entry["summary"]
        ET.SubElement(node, f"{{{NS}}}highlight").text = str(entry["highlight"]).lower()
        ET.SubElement(node, f"{{{NS}}}lab", id=entry["lab_id"]).text = entry["lab_name"]
        if entry["source_url"]:
            ET.SubElement(node, f"{{{NS}}}source").text = entry["source_url"]
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", default=str(HERE.parents[1] / "data/labs.json"))
    parser.add_argument("--highlights", type=Path, default=HERE / "highlights.json")
    parser.add_argument("--sources", type=Path, default=HERE / "sources.json")
    parser.add_argument("--output", type=Path, default=HERE / "public")
    parser.add_argument("--cache", type=Path, default=HERE / ".cache")
    parser.add_argument("--feed-url", type=url)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--lab", action="append", help="Limit to these Atlas IDs. Repeatable.")
    parser.add_argument("--offline", action="store_true", help="Use local Atlas and cached sources only.")
    args = parser.parse_args()
    if min(args.workers, args.days, args.limit) < 1:
        parser.error("--workers, --days, and --limit must be positive")
    if url(args.atlas) and args.offline:
        parser.error("--offline requires a local Atlas")
    atlas = json.loads(get(args.atlas)[0] if url(args.atlas) else Path(args.atlas).read_bytes())
    labs = [lab for lab in atlas["labs"] if not args.lab or lab["id"] in args.lab]
    if args.lab and set(args.lab) - {lab["id"] for lab in labs}:
        parser.error("unknown Atlas ID: " + ", ".join(sorted(set(args.lab) - {lab["id"] for lab in labs})))
    config = json.loads(args.sources.read_bytes())
    candidates, health = collect(labs, config, args.cache, args.workers, args.offline,
                                 include_papers=not args.lab)
    candidates.extend(curated(labs, args.highlights, include_papers=not args.lab))
    entries = select(candidates, args.days, args.limit)
    write(args.output / "stream.xml", rss(entries, args.feed_url))
    write_json(args.output / "stream.json", {"items": entries})
    print(f"{len(entries)} items from {len({entry['lab_id'] for entry in entries})} of {len(labs)} labs")
    for (kind, status), count in sorted(health.items()):
        print(f"{kind}: {count} {status}")


if __name__ == "__main__":
    main()
