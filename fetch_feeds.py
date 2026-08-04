"""服务端抓取：RSS / Atom / RDF + NBER、Crossref、World Bank 三个 JSON 接口。

跑在 GitHub Actions 里，没有浏览器同源策略，因此不需要任何 CORS 代理。
"""
from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
SOURCES = CFG["sources"]

UA = (
    "policy-papers-monitor/1.0 (weekly research-paper feed reader; "
    "+https://github.com/) python-requests"
)
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, application/json, text/xml, */*"}
TIMEOUT = 45
RETRIES = 3

_TAG = re.compile(r"<[^>]+>")
_JATS = re.compile(r"</?jats:[^>]*>", re.I)
_WS = re.compile(r"\s+")


def clean(text: str | None) -> str:
    if not text:
        return ""
    t = html.unescape(str(text))
    t = _JATS.sub(" ", t)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    return _WS.sub(" ", t).strip()


def _short(exc: Exception) -> str:
    """把异常压成一行短信息，避免层层包装出 'RuntimeError: RuntimeError: ...'。"""
    msg = str(exc).strip() or type(exc).__name__
    msg = _WS.sub(" ", msg)
    if not re.match(r"^(HTTP \d|[A-Za-z]+Error|[A-Za-z]+Exception)", msg):
        msg = f"{type(exc).__name__}: {msg}"
    return msg[:160]


def get(url: str, as_json: bool = False):
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504, 529):
                last = f"HTTP {r.status_code}（服务端限流或临时故障）"
                time.sleep(2 ** attempt * 3)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            return r.json() if as_json else r.content
        except Exception as exc:                       # noqa: BLE001
            last = _short(exc)
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(last or "未知错误")


def _to_iso(struct_time, fallback: str | None = None) -> str | None:
    if struct_time:
        try:
            return datetime(*struct_time[:6], tzinfo=timezone.utc).isoformat()
        except Exception:                              # noqa: BLE001
            pass
    if fallback:
        for fmt in ("%Y-%m-%d", "%B %Y", "%b %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y/%m/%d"):
            try:
                d = datetime.strptime(fallback.strip()[:24], fmt)
                return d.replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------
# 各类源的解析器
# --------------------------------------------------------------------------
def parse_feed(raw: bytes, src: dict) -> list[dict]:
    parsed = feedparser.parse(raw)
    out = []
    for e in parsed.entries:
        link = e.get("link") or ""
        if not link:
            for l in e.get("links", []):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href", "")
                    break
        if not link:
            link = e.get("id", "")
        summary = e.get("summary", "")
        if e.get("content"):
            longest = max((c.get("value", "") for c in e["content"]), key=len, default="")
            if len(longest) > len(summary):
                summary = longest
        authors = e.get("author", "") or ", ".join(
            a.get("name", "") for a in e.get("authors", []) if a.get("name")
        )
        out.append({
            "title": clean(e.get("title")),
            "link": re.sub(r"#fromrss$", "", link.strip()),
            "abstract": clean(summary),
            "authors": clean(authors),
            "date": _to_iso(e.get("published_parsed") or e.get("updated_parsed"),
                            e.get("published") or e.get("updated") or e.get("date")),
            "ptype": src["ptype"],
        })
    return out


def parse_nber(raw: bytes, src: dict) -> list[dict]:
    j = json.loads(raw)
    rows = j.get("results") or j.get("data") or []
    out = []
    for r in rows:
        url = r.get("url") or f"/papers/{r.get('backofficeid', '')}"
        if not url.startswith("http"):
            url = "https://www.nber.org" + ("" if url.startswith("/") else "/") + url
        authors = r.get("authors")
        if isinstance(authors, list):
            authors = ", ".join(str(a) for a in authors)
        out.append({
            "title": clean(r.get("title")),
            "link": url,
            "abstract": clean(r.get("abstract")),
            "authors": clean(authors),
            "date": _to_iso(None, r.get("publisheddate") or r.get("displaydate")),
            "ptype": src["ptype"],
        })
    return out


_CR_KEEP = re.compile(
    r"working paper|fintech note|departmental paper|staff climate note|technical note|"
    r"global financial stability|policy paper|analytical note", re.I)
_CR_DROP = re.compile(
    r"^(front|back) matter$|^copyright|^contents$|^preface|^acknowledg|^abbreviation|"
    r"^executive board|^statistical appendix|^glossary|^annex|^chapter \d", re.I)


def parse_crossref(raw: bytes, src: dict) -> list[dict]:
    items = json.loads(raw).get("message", {}).get("items", [])
    out = []
    for it in items:
        title = (it.get("title") or [""])[0]
        container = (it.get("container-title") or [""])[0]
        if not title or _CR_DROP.search(title.strip()):
            continue
        if not (_CR_KEEP.search(container) or _CR_KEEP.search(title)):
            continue
        created = (it.get("created") or {}).get("date-time")
        out.append({
            "title": clean(title),
            "link": it.get("URL") or f"https://doi.org/{it.get('DOI', '')}",
            "abstract": clean(it.get("abstract")),
            "authors": ", ".join(
                " ".join(x for x in (a.get("given"), a.get("family")) if x)
                for a in it.get("author", [])),
            "date": created,
            "ptype": container or src["ptype"],
            "doi": it.get("DOI", ""),
        })
    return out


def parse_worldbank(raw: bytes, src: dict) -> list[dict]:
    docs = json.loads(raw).get("documents", {})
    out = []
    for key, d in docs.items():
        if key == "facets" or not isinstance(d, dict) or not d.get("display_title"):
            continue
        abstracts = d.get("abstracts") or {}
        if isinstance(abstracts, dict):
            abstract = abstracts.get("cdata!") or abstracts.get("cdata") or ""
            if isinstance(abstract, dict):
                abstract = abstract.get("cdata!") or abstract.get("cdata") or ""
        else:
            abstract = str(abstracts)
        out.append({
            "title": clean(d.get("display_title")),
            "link": d.get("pdfurl") or d.get("url") or d.get("guid") or "",
            "abstract": clean(abstract),
            "authors": clean(d.get("authr")),
            "date": _to_iso(None, (d.get("docdt") or "")[:10]),
            "ptype": d.get("docty") or src["ptype"],
        })
    return out


PARSERS = {
    "rss": (parse_feed, False),
    "nber": (parse_nber, False),
    "crossref": (parse_crossref, False),
    "worldbank": (parse_worldbank, False),
}


def fetch_source(src: dict) -> tuple[dict, list[dict], str | None]:
    parser, _ = PARSERS[src["kind"]]
    try:
        raw = get(src["url"])
        items = parser(raw, src)
        for it in items:
            it["src_id"] = src["id"]
            it["org"] = src["org"]
            it["org_cn"] = src["cn"]
            it["group"] = src["group"]
        items = [i for i in items if i["title"] and i["link"]]
        return src, items, None
    except Exception as exc:                           # noqa: BLE001
        return src, [], _short(exc)


def fetch_all(max_workers: int = 6) -> tuple[list[dict], list[dict]]:
    items, status = [], []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_source, s) for s in SOURCES]
        for fut in as_completed(futures):
            src, got, err = fut.result()
            status.append({
                "id": src["id"], "org": src["org"], "cn": src["cn"], "url": src["url"],
                "state": "err" if err else ("ok" if got else "warn"),
                "n": len(got), "err": err or ("解析出 0 条" if not got else None),
            })
            items.extend(got)
            print(f"  {'✗' if err else '✓'} {src['org']:<14} {src['cn']:<18} "
                  f"{len(got):>4} 条  {err or ''}")
    status.sort(key=lambda s: (s["state"] != "err", s["id"]))
    return items, status


# --------------------------------------------------------------------------
# OpenAlex 摘要回填 —— IMF 走 Crossref 常常没有摘要，用 DOI 去 OpenAlex 补
# --------------------------------------------------------------------------
def backfill_abstracts(items: list[dict], mailto: str = "", limit: int = 40) -> int:
    todo = [i for i in items if i.get("doi") and len(i.get("abstract") or "") < 120][:limit]
    filled = 0
    for it in todo:
        try:
            url = f"https://api.openalex.org/works/doi:{it['doi']}"
            if mailto:
                url += f"?mailto={mailto}"
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code != 200:
                continue
            inv = r.json().get("abstract_inverted_index")
            if not inv:
                continue
            positions: dict[int, str] = {}
            for word, idxs in inv.items():
                for i in idxs:
                    positions[i] = word
            text = " ".join(positions[k] for k in sorted(positions))
            if len(text) > len(it.get("abstract") or ""):
                it["abstract"] = clean(text)
                filled += 1
        except Exception:                              # noqa: BLE001
            continue
        time.sleep(0.15)                               # 对 OpenAlex 礼貌一点
    return filled
