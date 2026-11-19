# Open Labs Atlas

A world map and directory of independent AI labs committed to open source, by [Renaissance Labs](https://renaissancelabs.eu). Live at https://labs.renaissancelabs.eu.

It is a static site: plain HTML, CSS and a little JavaScript, with the map drawn client side (d3 and a world atlas, vendored in `assets/vendor/`). There is no backend.

## Layout

- `data/regions/*.json`: researched lab records, one array per region.
- `data/patches/*.json`: corrections and editorial layers merged on top by id (later layers win: enrichment, editorial, thin-page pass, curation). `{"id": "...", "_remove": true}` hides a lab; `notice` adds a short update banner.
- `tools/build.py`: merges the data and writes `index.html`, `labs/<slug>/index.html`, `about/`, `data/labs.json`, `labs.csv`, `sitemap.xml`, `llms.txt`.
- `tools/fetch_logos.py`: downloads each lab's GitHub or Hugging Face avatar into `assets/logos/` (monogram fallback when there is none).

## Build

```bash
python3 tools/fetch_logos.py   # optional, macOS (uses sips)
python3 tools/build.py
python3 -m http.server 8790    # preview
```

## Inclusion and corrections

A lab is listed when it works on AI models, data, tooling or infrastructure and has a public record of releasing open weights, code or data. Independence from big tech is the default rule, with a clearly labelled exception for large companies that release a lot openly. Only channels the lab publishes itself are shown. To add, correct or remove a lab, open an issue or tell us on [Discord](https://discord.gg/6JUezWZbAm).

## Licence

Code: MIT. Lab data in `data/` and `labs.csv`: CC BY 4.0, please credit "Open Labs Atlas by Renaissance Labs". Logos belong to their respective organisations and are shown to identify them.

## Updates feed

GitHub Pages serves `/stream.xml` (RSS) and `/stream.json` (JSON).
The Pages workflow rebuilds the feed every four hours, on pushes to main,
and after the weekly Atlas refresh. Each item carries the lab's Atlas ID.

Run a local snapshot build with
`python3 tools/feed/build_feed.py --offline --output /tmp/atlas-stream`.
Add explicit lab blog, video, or release sources in `tools/feed/sources.json`.

The iOS Highlights feed uses the editorial entries in `tools/feed/highlights.json`.
Add a source URL, Atlas ID, publication date, headline and an original summary
that explains the concrete change or finding. Read the source first and keep
experimental results scoped to what was measured. Automated items remain
available in All updates. The scheduled refresh publishes the editorial file
alongside the raw feed, and recent highlights stay eligible for 45 days.
