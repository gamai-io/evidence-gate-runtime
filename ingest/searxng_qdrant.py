#!/usr/bin/env python3
"""Ingest SearXNG HTML results -> bge-m3 embeddings -> Qdrant collection gama_web.

Stdlib only. Env:
  SEARXNG_URL (default http://127.0.0.1:30092)
  EMBED_URL   (default http://10.0.0.7:8064/v1/embeddings)
  EMBED_MODEL (default bge-m3)
  QDRANT_URL  (default http://127.0.0.1:6333)
  COLLECTION  (default gama_web)
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SEARXNG = os.environ.get("SEARXNG_URL", "http://127.0.0.1:30092")
EMBED = os.environ.get("EMBED_URL", "http://10.0.0.7:8064/v1/embeddings")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
QDRANT = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLL = os.environ.get("COLLECTION", "gama_web")

QUERIES = [
    "graco airless", "graco ultra 795", "graco 695", "pjeskarenje pjeskara",
    "kompresor vazduha", "malter masina", "gips masina pft", "elcometer",
    "farbanje airless", "industrijske masine", "airblast", "comprag",
]

UA = {"User-Agent": "Mozilla/5.0 (GAMA ingest; +https://gamai.io)"}
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def clean(s):
    return WS.sub(" ", html.unescape(TAG.sub(" ", s or ""))).strip()


def get(url, timeout=15, data=None, headers=None, method=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search(q):
    url = SEARXNG.rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": q, "language": "all", "safesearch": "0"})
    raw = get(url, timeout=12).decode("utf-8", "replace")
    out = []
    for chunk in raw.split('<article class="result')[1:]:
        m = re.search(r'href="(https?://[^"]+)"[^>]*class="url_header"', chunk) or \
            re.search(r'class="url_header"[^>]*href="(https?://[^"]+)"', chunk) or \
            re.search(r'href="(https?://[^"]+)"', chunk)
        if not m:
            continue
        href = html.unescape(m.group(1))
        t = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.S)
        c = re.search(r'<p class="content">(.*?)</p>', chunk, re.S)
        title = clean(t.group(1)) if t else ""
        snippet = clean(c.group(1)) if c else ""
        if not title and not snippet:
            continue
        out.append({"url": href, "title": title, "snippet": snippet, "query": q})
    return out


def embed(texts):
    body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    d = json.loads(get(EMBED, timeout=60, data=body,
                       headers={"Content-Type": "application/json"}))
    return [x["embedding"] for x in d.get("data", [])]


def ensure_collection(dim):
    try:
        get(QDRANT.rstrip("/") + "/collections/" + COLL, timeout=8)
        return False
    except Exception:
        body = json.dumps({"vectors": {"size": dim, "distance": "Cosine"}}).encode()
        get(QDRANT.rstrip("/") + "/collections/" + COLL, timeout=20, data=body,
            headers={"Content-Type": "application/json"}, method="PUT")
        return True


def upsert(points):
    body = json.dumps({"points": points}).encode()
    return get(QDRANT.rstrip("/") + "/collections/" + COLL + "/points?wait=true",
               timeout=60, data=body, headers={"Content-Type": "application/json"}, method="PUT")


def main():
    seen = {}
    for q in QUERIES:
        try:
            rows = search(q)
        except Exception as exc:
            print("search fail %s: %s" % (q, str(exc)[:90]), file=sys.stderr)
            continue
        for r in rows:
            if r["url"] not in seen:
                r["id"] = int(hashlib.sha1(r["url"].encode()).hexdigest()[:15], 16)
                seen[r["url"]] = r
        print("query %-28s rows=%d total=%d" % (q, len(rows), len(seen)))

    docs = list(seen.values())
    if not docs:
        print("no docs"); return 1

    texts = [(d["title"] + ". " + d["snippet"]).strip()[:4000] for d in docs]
    vecs = []
    for i in range(0, len(texts), 32):
        vecs.extend(embed(texts[i:i + 32]))
    dim = len(vecs[0])
    created = ensure_collection(dim)
    print("docs=%d dim=%d collection_created=%s" % (len(docs), dim, created))

    pts = []
    for d, v in zip(docs, vecs):
        pts.append({"id": d["id"], "vector": v, "payload": {
            "url": d["url"], "title": d["title"], "snippet": d["snippet"],
            "query": d["query"], "source": "searxng", "ts": int(time.time())}})
    for i in range(0, len(pts), 64):
        upsert(pts[i:i + 64])
    info = json.loads(get(QDRANT.rstrip("/") + "/collections/" + COLL, timeout=8))
    print(json.dumps({"collection": COLL, "points": info.get("result", {}).get("points_count"),
                      "vectors": info.get("result", {}).get("config", {}).get("params", {})}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
