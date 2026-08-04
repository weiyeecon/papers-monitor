"""产出 docs/data.json（看板数据）与 reports/YYYY-Www.md（周报）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from analyse import days_ago

ROOT = Path(__file__).resolve().parent
DOCS = ROOT                      # 扁平结构：网页文件就在仓库根目录
REPORTS = ROOT / "reports"
TAX = json.loads((ROOT / "taxonomy.json").read_text(encoding="utf-8"))
GROUPS = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["groups"]

PUBLIC_FIELDS = (
    "key title link abstract authors date first_seen src_id org org_cn group ptype meta cn"
).split()


def write_data_json(items: list[dict], status: list[dict], window_days: int = 400) -> Path:
    keep = [i for i in items if i.get("meta", {}).get("topics")
            and days_ago(i.get("date") or i.get("first_seen")) <= window_days]
    keep.sort(key=lambda i: (i.get("date") or i.get("first_seen") or "", i["meta"]["score"]),
              reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_total": len(items),
        "n_shown": len(keep),
        "groups": GROUPS,
        "topics": [{k: t[k] for k in ("id", "label", "cls", "kw")} for t in TAX["topics"]],
        "cn_search": TAX["cn_search"],
        "status": status,
        "items": [{k: i.get(k) for k in PUBLIC_FIELDS} for i in keep],
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    out = DOCS / "data.json"
    out.write_text(blob, encoding="utf-8")
    # 同时写一份 JS 包装：这样把仓库下载到本地、直接双击 index.html 也能看
    # （file:// 协议下 fetch 会被浏览器拦掉）
    (DOCS / "data.js").write_text("window.__DATA=" + blob + ";", encoding="utf-8")
    return out


def _iso_week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def write_report(new_items: list[dict], all_items: list[dict], status: list[dict]) -> Path:
    now = datetime.now(timezone.utc)
    tag = _iso_week(now)
    fresh = [i for i in new_items if i.get("meta", {}).get("topics")]
    fresh.sort(key=lambda i: -i["meta"]["score"])

    lines = [
        f"# 数字货币与金融稳定 · 每周论文简报 {tag}",
        "",
        f"生成时间：{now.strftime('%Y-%m-%d %H:%M')} UTC　·　"
        f"本周新增主题相关 **{len(fresh)}** 篇　·　库内累计 **{len(all_items)}** 篇",
        "",
    ]

    if not fresh:
        lines += ["本周各机构没有发布与稳定币 / 加密资产 / 代币化 / CBDC / 金融稳定相关的新论文。", ""]
    else:
        by_group: dict[str, list[dict]] = {}
        for it in fresh:
            by_group.setdefault(it.get("group", "other"), []).append(it)
        for g in GROUPS:
            bucket = by_group.get(g["id"])
            if not bucket:
                continue
            lines += [f"## {g['label']}（{len(bucket)} 篇）", ""]
            for it in bucket:
                cn = it.get("cn") or {}
                meta = it["meta"]
                lines.append(f"### [{it['title']}]({it['link']})")
                lines.append("")
                lines.append(
                    f"`{it['org']}` {it['org_cn']} · {it.get('ptype', '')} · "
                    f"{(it.get('date') or '')[:10]} · 相关度 {meta['score']} · "
                    f"{'、'.join(t['label'] for t in meta['topics'])}"
                )
                lines.append("")
                if it.get("authors"):
                    lines.append(f"- **作者**：{it['authors'][:200]}")
                if cn:
                    lines.append(f"- **一句话**：{cn.get('一句话', '')}")
                    for f in ("问题", "数据", "方法", "发现", "含义"):
                        if cn.get(f):
                            lines.append(f"- **{f}**：{cn[f]}")
                else:
                    lines.append(f"- **要点（规则提取）**：{meta['lead']}")
                    if meta.get("finding"):
                        lines.append(f"- **原文结论句**：{meta['finding'][:400]}")
                lines.append("")

    bad = [s for s in status if s["state"] == "err"]
    lines += ["---", "",
              f"### 抓取状态：{sum(1 for s in status if s['state'] == 'ok')}/{len(status)} 个源正常", ""]
    if bad:
        lines.append("失败的源：")
        lines.append("")
        for s in bad:
            lines.append(f"- `{s['org']}` {s['cn']} — {s['err']}")
        lines.append("")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{tag}.md"
    out.write_text("\n".join(lines), encoding="utf-8")

    latest = REPORTS / "latest.md"
    latest.write_text("\n".join(lines), encoding="utf-8")
    return out
