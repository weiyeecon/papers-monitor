#!/usr/bin/env python3
"""每周主流程：抓取 → 去重入库 → 规则分析 → 中文摘要 → 产出看板与周报。

本地跑：
    pip install -r requirements.txt
    DEEPSEEK_API_KEY=sk-... python run.py
不带 key 也能跑，只是没有中文摘要，卡片退回规则提取的要点。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build                                            # noqa: E402
import fetch_feeds                                      # noqa: E402
import translate                                        # noqa: E402
from analyse import analyse, days_ago                    # noqa: E402

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "papers.json"

KEEP_IRRELEVANT_DAYS = int(os.environ.get("KEEP_IRRELEVANT_DAYS", "120"))
TRANSLATE_LIMIT = int(os.environ.get("TRANSLATE_LIMIT", "60"))
OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "")

_KEYCLEAN = re.compile(r"[^a-z0-9一-鿿]")


def key_of(item: dict) -> str:
    return _KEYCLEAN.sub("", (item.get("title") or "").lower())[:90]


def load_store() -> list[dict]:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("! data/papers.json 解析失败，本次从空库重建")
    return []


def save_store(items: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"=== 抓取开始 {now} ===")

    fetched, status = fetch_feeds.fetch_all()
    ok = sum(1 for s in status if s["state"] == "ok")
    print(f"--- 抓取完成：{ok}/{len(status)} 个源正常，共 {len(fetched)} 条原始条目")

    filled = fetch_feeds.backfill_abstracts(fetched, OPENALEX_MAILTO)
    if filled:
        print(f"--- OpenAlex 回填摘要 {filled} 条")

    store = load_store()
    by_key = {i["key"]: i for i in store if i.get("key")}

    new_items: list[dict] = []
    for raw in fetched:
        k = key_of(raw)
        if not k:
            continue
        existing = by_key.get(k)
        if existing:
            # 摘要变长就更新（有些源先发标题、后补摘要），并重跑规则分析
            if len(raw.get("abstract") or "") > len(existing.get("abstract") or ""):
                existing["abstract"] = raw["abstract"]
                existing["meta"] = analyse(existing)
                existing.pop("cn", None)               # 摘要变了，中文重新生成
            continue
        item = dict(raw)
        item["key"] = k
        item["first_seen"] = now
        item["meta"] = analyse(item)
        by_key[k] = item
        new_items.append(item)

    print(f"--- 新增 {len(new_items)} 条，其中主题相关 "
          f"{sum(1 for i in new_items if i['meta']['topics'])} 条")

    items = list(by_key.values())
    before = len(items)
    items = [i for i in items
             if i["meta"]["topics"]
             or days_ago(i.get("date") or i.get("first_seen")) <= KEEP_IRRELEVANT_DAYS]
    if before != len(items):
        print(f"--- 清理无关旧条目 {before - len(items)} 条")

    provider = translate.get_provider()
    if provider:
        print(f"--- 生成中文摘要（{provider['name']}）")
        targets = [i for i in items if i["meta"]["topics"] and not i.get("cn")]
        done = translate.translate_new(targets, provider, TRANSLATE_LIMIT)
        print(f"--- 中文摘要完成 {done} 条")
    else:
        print("--- 未设置任何 API Key（DEEPSEEK_API_KEY / LLM_API_KEY / ANTHROPIC_API_KEY），"
              "跳过中文摘要，卡片使用规则提取要点")

    save_store(items)
    data_path = build.write_data_json(items, status)
    report_path = build.write_report(new_items, items, status)
    print(f"--- 已写出 {data_path.name} 与 {report_path.relative_to(ROOT)}")

    if ok == 0:
        print("!!! 所有源都失败了，请检查网络或源地址")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
