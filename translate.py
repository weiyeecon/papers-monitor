"""为新增论文生成结构化中文摘要。

支持两类接口，按环境变量自动选择，不用改代码：

  DEEPSEEK_API_KEY   → DeepSeek（OpenAI 兼容格式，默认 https://api.deepseek.com）
  LLM_API_KEY        → 任意 OpenAI 兼容服务（配合 LLM_BASE_URL，如 Kimi、通义、
                       智谱、硅基流动、OpenRouter、OpenAI 本身）
  ANTHROPIC_API_KEY  → Anthropic 原生接口

同时配了多个就按上面的顺序取第一个。模型 ID 会先向服务端 /models 校验一次，
写错或模型下线会自动挑一个可用的顶上，不会让整场跑挂掉。

要点：
- 只处理"新增且尚无中文"的条目，历史条目不会重复付费；
- 有每次运行的条数上限，防止某周源站补发大量历史条目导致费用失控。
"""
from __future__ import annotations

import os
import time

import requests

ANTHROPIC_VERSION = "2023-06-01"

PROMPT = """你是一位金融经济学研究助理。下面是一篇工作论文的题录与英文摘要。
请用简体中文输出，严格按下列六行格式，每行以标签开头，不要输出任何多余内容、不要加粗、不要项目符号：

一句话：用不超过40字说清这篇研究做了什么
问题：研究问题是什么，一句话
数据：具体数据来源、样本范围与时间跨度；摘要没写就写"摘要未说明"
方法：识别策略或建模方法；摘要没写就写"摘要未说明"
发现：主要结论，一到两句，尽量保留关键数量级
含义：对金融稳定或政策的含义，一句话；若不相关写"不直接相关"

翻译术语时请遵循中文金融学界惯例，例如 run 译"挤兑"、depeg 译"脱锚"、
disintermediation 译"脱媒"、tokenized deposit 译"代币化存款"、
difference-in-differences 译"双重差分"、collateral 译"抵押品"。
如果摘要缺失或过短，就依据标题作合理概括，并在"数据"与"方法"两行写"摘要未提供"。

机构：{org}（{org_cn}）
类型：{ptype}
标题：{title}
作者：{authors}
日期：{date}
英文摘要：{abstract}"""

FIELDS = ["一句话", "问题", "数据", "方法", "发现", "含义"]

# 模型自动回退时的偏好顺序：先便宜的小模型
_PREFER = ("flash", "haiku", "mini", "turbo", "lite", "air", "pro", "sonnet")


def get_provider() -> dict | None:
    """返回 {kind, key, base, model, name}；没配任何 key 就返回 None。"""
    # 注意用 `or 默认值` 而不是 os.environ.get 的第二参数：
    # GitHub Actions 里未定义的 vars 会注入成空字符串，而不是不存在。
    def env(name: str, default: str = "") -> str:
        return (os.environ.get(name) or "").strip() or default

    base_url = env("LLM_BASE_URL")

    ds = env("DEEPSEEK_API_KEY")
    if ds:
        return {
            "kind": "openai", "key": ds, "name": "DeepSeek",
            "base": (base_url or "https://api.deepseek.com").rstrip("/"),
            "model": env("LLM_MODEL", "deepseek-v4-flash"),
        }
    generic = env("LLM_API_KEY")
    if generic:
        if not base_url:
            raise RuntimeError("设置了 LLM_API_KEY 就必须同时设置 LLM_BASE_URL")
        return {
            "kind": "openai", "key": generic, "name": f"OpenAI 兼容服务（{base_url}）",
            "base": base_url.rstrip("/"), "model": env("LLM_MODEL", "gpt-4o-mini"),
        }
    an = env("ANTHROPIC_API_KEY")
    if an:
        return {
            "kind": "anthropic", "key": an, "name": "Anthropic",
            "base": (base_url or "https://api.anthropic.com").rstrip("/"),
            "model": env("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        }
    return None


def _headers(p: dict) -> dict:
    if p["kind"] == "anthropic":
        return {"x-api-key": p["key"], "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json"}
    return {"Authorization": "Bearer " + p["key"], "content-type": "application/json"}


def resolve_model(p: dict) -> str:
    """校验模型是否可用；不可用就在服务端可见模型里挑一个便宜的顶上。"""
    want = p["model"]
    url = f"{p['base']}/v1/models" if p["kind"] == "anthropic" else f"{p['base']}/models"
    try:
        r = requests.get(url, headers=_headers(p), timeout=30)
        r.raise_for_status()
        ids = [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
    except Exception as exc:                           # noqa: BLE001
        print(f"  ! 无法列出模型（{exc}），沿用 {want}")
        return want
    if not ids or want in ids:
        return want
    for kind in _PREFER:
        hits = sorted([i for i in ids if kind in i.lower()], reverse=True)
        if hits:
            print(f"  ! 模型 {want} 不可用，改用 {hits[0]}（服务端可见：{', '.join(ids[:8])}）")
            return hits[0]
    print(f"  ! 模型 {want} 不可用，改用 {ids[0]}")
    return ids[0]


def _call(p: dict, model: str, prompt: str) -> str:
    if p["kind"] == "anthropic":
        url = f"{p['base']}/v1/messages"
        body = {"model": model, "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}]}
    else:
        url = f"{p['base']}/chat/completions"
        body = {"model": model, "max_tokens": 800, "temperature": 0.2, "stream": False,
                "messages": [{"role": "user", "content": prompt}]}

    last = None
    for attempt in range(4):
        try:
            r = requests.post(url, headers=_headers(p), json=body, timeout=180)
            if r.status_code in (429, 500, 502, 503, 529):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt * 5)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            j = r.json()
            if p["kind"] == "anthropic":
                return "".join(c.get("text", "") for c in j.get("content", [])).strip()
            return (j["choices"][0]["message"].get("content") or "").strip()
        except Exception as exc:                       # noqa: BLE001
            last = str(exc)[:200]
            time.sleep(2 ** attempt * 4)
    raise RuntimeError(last or "unknown")


def _parse(text: str) -> dict:
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        line = line.strip().lstrip("-•*# ").strip()
        if not line:
            continue
        matched = False
        for f in FIELDS:
            for sep in ("：", ":"):
                if line.startswith(f + sep):
                    out[f] = line[len(f) + 1:].strip()
                    current = f
                    matched = True
                    break
            if matched:
                break
        if not matched and current:
            out[current] = (out[current] + " " + line).strip()
    return out


def translate_new(items: list[dict], provider: dict, limit: int = 60) -> int:
    """就地给 item 写入 item['cn']。返回成功翻译的条数。"""
    todo = [i for i in items if not i.get("cn")]
    if not todo:
        print("  没有需要翻译的新条目")
        return 0

    # 相关度高的优先翻译，触到上限时先保证最该看的那些有中文
    todo.sort(key=lambda i: -(i.get("meta", {}).get("score", 0)))
    skipped = max(0, len(todo) - limit)
    todo = todo[:limit]

    model = resolve_model(provider)
    print(f"  {provider['name']} · 模型 {model}，待翻译 {len(todo)} 条"
          + (f"（本次跳过 {skipped} 条，下周继续）" if skipped else ""))

    done = 0
    for n, it in enumerate(todo, 1):
        prompt = PROMPT.format(
            org=it.get("org", ""), org_cn=it.get("org_cn", ""),
            ptype=it.get("ptype", ""), title=it.get("title", ""),
            authors=it.get("authors") or "未提供",
            date=(it.get("date") or "")[:10] or "未提供",
            abstract=(it.get("abstract") or "（该源未提供摘要）")[:6000],
        )
        try:
            parsed = _parse(_call(provider, model, prompt))
            if parsed.get("一句话"):
                it["cn"] = parsed
                it["cn_model"] = model
                done += 1
            else:
                print(f"  ! 第 {n} 条返回格式不符，跳过：{it['title'][:60]}")
        except Exception as exc:                       # noqa: BLE001
            print(f"  ! 第 {n} 条翻译失败：{exc}")
        if n % 10 == 0:
            print(f"  … {n}/{len(todo)}")
        time.sleep(0.4)
    return done
