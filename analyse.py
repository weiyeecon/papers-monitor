"""主题识别、相关度打分、数据/方法/情境提取。

与前端 docs/index.html 共用 config/taxonomy.json，保证两边口径一致。
这一层不调用任何模型，纯关键词规则，离线可跑。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAX = json.loads((ROOT / "taxonomy.json").read_text(encoding="utf-8"))

TOPICS = TAX["topics"]
DATA_DICT = TAX["data_dict"]
METHOD_DICT = TAX["method_dict"]
CONTEXT_DICT = TAX["context_dict"]

CORE_TOPICS = {"stable", "cbdc", "token", "crypto"}

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_FINDING = re.compile(
    r"\b(we find|we show|we document|results (show|suggest|indicate)|"
    r"findings? (show|suggest|indicate)|our (results|analysis|estimates)|"
    r"the paper (shows|finds)|evidence (shows|suggests)|conclude that|imply that)\b",
    re.I,
)


def _pick(dictionary, haystack: str, limit: int) -> list[str]:
    out: list[str] = []
    for kws, label in dictionary:
        if any(k in haystack for k in kws) and label not in out:
            out.append(label)
    return out[:limit]


def days_ago(iso: str | None) -> float:
    if not iso:
        return 9999.0
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 9999.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400.0


def analyse(item: dict) -> dict:
    """item: {title, abstract, org_cn, ptype, date}. 返回 meta 字典。"""
    title = (item.get("title") or "").lower()
    abstract = (item.get("abstract") or "").lower()
    both = title + "   " + abstract

    topics, score = [], 0
    for t in TOPICS:
        hit_t = sum(1 for k in t["kw"] if k in title)
        hit_a = sum(1 for k in t["kw"] if k not in title and k in abstract)
        if hit_t or hit_a:
            topics.append({"id": t["id"], "label": t["label"], "cls": t["cls"]})
            score += hit_t * 7 + min(hit_a, 4) * 2

    ids = {t["id"] for t in topics}
    if ids & CORE_TOPICS:
        score += 6
        if "fs" in ids:                       # 核心主题 × 金融稳定 的交叉最有价值
            score += 8
    if len(topics) >= 3:
        score += 4

    d = days_ago(item.get("date"))
    if d <= 7:
        score += 8
    elif d <= 30:
        score += 4
    elif d <= 90:
        score += 1

    ptype = (item.get("ptype") or "").lower()
    if re.search(r"working paper|discussion paper|staff report|research", ptype):
        score += 3
    if re.search(r"speech|news", ptype):
        score -= 2
    if len(item.get("abstract") or "") > 400:
        score += 2

    data = _pick(DATA_DICT, both, 3)
    method = _pick(METHOD_DICT, both, 2)
    ctx = _pick(CONTEXT_DICT, both, 3)

    sents = [s for s in _SENT_SPLIT.split(item.get("abstract") or "") if len(s) > 30]
    question = sents[0] if sents else ""
    finding = ""
    for s in sents[1:]:
        if _FINDING.search(s):
            finding = s
            break
    if not finding and len(sents) > 1:
        finding = sents[-1]

    labels = [t["label"] for t in topics]
    lead = f'{item.get("org_cn", "")}「{item.get("ptype") or "出版物"}」'
    if labels:
        lead += "，主题为" + " × ".join(labels)
    if ctx:
        lead += "，切入" + "、".join(ctx)
    if method:
        lead += "，方法上采用" + " + ".join(method)
    if data:
        lead += "，数据来自" + "、".join(data)
    lead += "。"

    return {
        "topics": topics,
        "score": round(score),
        "data": data,
        "method": method,
        "ctx": ctx,
        "question": question,
        "finding": finding,
        "lead": lead,
    }


def is_relevant(meta: dict) -> bool:
    return bool(meta.get("topics"))
