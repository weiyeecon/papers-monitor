"use strict";
/* 看板前端：只读同目录下的 data.json，由 GitHub Actions 每周重建。
   没有跨域请求，因此不需要任何代理，也不会有抓取失败。 */

const STATE = {
  data: null, items: [],
  topics: new Set(), groups: new Set(),
  q: "", win: 30, sort: "date", strict: true, onlyCn: false,
};
const $ = (s) => document.querySelector(s);
const grid = $("#grid");

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtDate = (iso) => (iso ? String(iso).slice(0, 10) : "日期未知");
const daysAgo = (iso) => (iso ? (Date.now() - new Date(iso).getTime()) / 864e5 : 9999);

function topicById(id) { return (STATE.data.topics || []).find((t) => t.id === id); }

function expandQuery(q) {
  const map = STATE.data.cn_search || {};
  const terms = [q];
  for (const cn in map) if (q.includes(cn)) terms.push(map[cn]);
  return terms.filter(Boolean).map((t) => t.toLowerCase());
}

function highlight(text, it) {
  if (!text) return "";
  let out = esc(text);
  const kws = [];
  for (const t of it.meta.topics) {
    const full = topicById(t.id);
    if (full) for (const k of full.kw) if (k.length > 4) kws.push(k);
  }
  const uniq = [...new Set(kws)].sort((a, b) => b.length - a.length).slice(0, 40);
  if (uniq.length) {
    const re = new RegExp("(" + uniq.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
    out = out.replace(re, "<mark>$1</mark>");
  }
  return out;
}

function currentList() {
  const qs = STATE.q.trim() ? expandQuery(STATE.q.trim().toLowerCase()) : [];
  const list = STATE.items.filter((it) => {
    if (!STATE.groups.has(it.group)) return false;
    if (STATE.win > 0 && daysAgo(it.date || it.first_seen) > STATE.win) return false;
    if (STATE.strict && !it.meta.topics.length) return false;
    if (STATE.onlyCn && !it.cn) return false;
    if (STATE.topics.size && !it.meta.topics.some((t) => STATE.topics.has(t.id))) return false;
    if (qs.length) {
      const cn = it.cn ? Object.values(it.cn).join(" ") : "";
      const hay = (it.title + " " + it.abstract + " " + (it.authors || "") + " " +
        it.org + " " + it.org_cn + " " + it.meta.lead + " " + cn).toLowerCase();
      if (!qs.some((t) => hay.includes(t))) return false;
    }
    return true;
  });
  list.sort((a, b) => {
    if (STATE.sort === "score" && b.meta.score !== a.meta.score) return b.meta.score - a.meta.score;
    const da = new Date(a.date || a.first_seen || 0).getTime();
    const db = new Date(b.date || b.first_seen || 0).getTime();
    return db !== da ? db - da : b.meta.score - a.meta.score;
  });
  return list;
}

function cnBlock(it) {
  const c = it.cn;
  if (!c) return "";
  const rows = ["问题", "数据", "方法", "发现", "含义"]
    .filter((f) => c[f])
    .map((f) => `<div class="kv"><span class="k">${f}</span><span class="v">${esc(c[f])}</span></div>`)
    .join("");
  return `<div class="brief ai-out">
    <div class="lead"><span class="cn-flag">中文摘要</span>${esc(c["一句话"] || "")}</div>
    ${rows}
  </div>`;
}

function ruleBlock(it) {
  const m = it.meta;
  return `<div class="brief">
    <div class="lead">${esc(m.lead)}</div>
    ${m.question ? `<div class="kv"><span class="k">问题</span><span class="v">${highlight(m.question.slice(0, 300), it)}</span></div>` : ""}
    ${m.finding ? `<div class="kv"><span class="k">发现</span><span class="v">${highlight(m.finding.slice(0, 300), it)}</span></div>` : ""}
    ${m.data.length ? `<div class="kv"><span class="k">数据</span><span class="v">${m.data.map((d) => "<em>" + esc(d) + "</em>").join(" ")}</span></div>` : ""}
    ${m.method.length ? `<div class="kv"><span class="k">方法</span><span class="v">${m.method.map((d) => "<em>" + esc(d) + "</em>").join(" ")}</span></div>` : ""}
    <div class="src-note">规则提取，非模型生成${it.cn ? "；上方为模型中文摘要" : ""}</div>
  </div>`;
}

function render() {
  const list = currentList();
  grid.innerHTML = "";
  $("#empty").style.display = list.length ? "none" : "block";

  const frag = document.createDocumentFragment();
  for (const it of list.slice(0, 500)) {
    const isNew = daysAgo(it.date || it.first_seen) <= 7;
    const c = document.createElement("div");
    c.className = "card" + (isNew ? " new" : "");
    c.innerHTML = `
      <div class="c-top">
        <span class="org">${esc(it.org)}</span>
        <span class="orgcn">${esc(it.org_cn)}</span>
        <span class="ptype">${esc(it.ptype || "")}</span>
        ${isNew ? '<span class="badge-new">本周新增</span>' : ""}
        <span class="date">${fmtDate(it.date || it.first_seen)}</span>
      </div>
      <h3 class="title"><a href="${esc(it.link)}" target="_blank" rel="noopener">${esc(it.title)}</a></h3>
      ${it.authors ? `<p class="authors">${esc(it.authors.slice(0, 160))}</p>` : ""}
      <div class="tags">
        ${it.meta.topics.map((t) => `<span class="tag ${esc(t.cls)}">${esc(t.label)}</span>`).join("")}
        <span class="score ${it.meta.score >= 25 ? "hi" : ""}" title="相关度：标题命中、主题交叉、时效、体裁综合">★ ${it.meta.score}</span>
      </div>
      ${cnBlock(it)}
      ${ruleBlock(it)}
      ${it.abstract
        ? `<details class="abs"><summary>原文摘要（${it.abstract.length} 字符）</summary><div class="abs-txt">${highlight(it.abstract, it)}</div></details>`
        : `<div style="font-size:11.5px;color:var(--tx3)">该源未提供摘要，点标题看原文。</div>`}
      <div class="c-foot"><button class="btn sm" data-cite="${esc(it.key)}">复制引用</button></div>`;
    frag.appendChild(c);
  }
  grid.appendChild(frag);

  const week = list.filter((i) => daysAgo(i.date || i.first_seen) <= 7).length;
  const cn = list.filter((i) => i.cn).length;
  $("#counts").innerHTML =
    `当前显示 <b>${list.length}</b> 篇（本周新增 <b>${week}</b>，含中文摘要 <b>${cn}</b>）` +
    `｜库内主题相关 <b>${STATE.items.length}</b> 篇` +
    (list.length > 500 ? "（列表上限 500）" : "");
  renderChipCounts();
}

function renderChipCounts() {
  const base = STATE.items.filter((it) => STATE.groups.has(it.group) &&
    (STATE.win <= 0 || daysAgo(it.date || it.first_seen) <= STATE.win));
  document.querySelectorAll("#topicChips .chip[data-topic]").forEach((ch) => {
    const n = base.filter((it) => it.meta.topics.some((t) => t.id === ch.dataset.topic)).length;
    const box = ch.querySelector(".n"); if (box) box.textContent = n;
  });
  document.querySelectorAll("#groupChips .chip[data-group]").forEach((ch) => {
    const n = STATE.items.filter((it) => it.group === ch.dataset.group &&
      (STATE.win <= 0 || daysAgo(it.date || it.first_seen) <= STATE.win)).length;
    const box = ch.querySelector(".n"); if (box) box.textContent = n;
  });
}

function renderStatus() {
  const st = STATE.data.status || [];
  const rows = st.map((s) => {
    const cls = s.state === "ok" ? "ok" : s.state === "err" ? "err" : "warn";
    const info = s.state === "ok" ? `${s.n} 条`
      : `<span style="color:var(--${s.state === "err" ? "err" : "warn"})">${esc(s.err || "")}</span>`;
    return `<tr><td style="white-space:nowrap"><span class="dot ${cls}"></span>${esc(s.org)}</td>
      <td style="white-space:nowrap;color:var(--tx3)">${esc(s.cn)}</td>
      <td>${info}</td><td class="mono">${esc((s.url || "").slice(0, 78))}</td></tr>`;
  }).join("");
  $("#srcTable").innerHTML = "<tr><th>机构</th><th></th><th>结果</th><th>Feed</th></tr>" + rows;
  const ok = st.filter((s) => s.state === "ok").length;
  $("#diagsum").textContent = `上次运行成功 ${ok}／${st.length}`;
}

function buildChips() {
  $("#topicChips").innerHTML =
    STATE.data.topics.map((t) => `<button class="chip ${t.cls}" data-topic="${t.id}">${t.label}<span class="n">0</span></button>`).join("") +
    `<button class="chip" id="clearTopics" style="opacity:.7">全部主题</button>`;
  $("#groupChips").innerHTML =
    STATE.data.groups.map((g) => `<button class="chip on" data-group="${g.id}">${g.label}<span class="n">0</span></button>`).join("");
  STATE.groups = new Set(STATE.data.groups.map((g) => g.id));

  document.querySelectorAll("#topicChips .chip[data-topic]").forEach((ch) => {
    ch.onclick = () => {
      const id = ch.dataset.topic;
      STATE.topics.has(id) ? (STATE.topics.delete(id), ch.classList.remove("on"))
                           : (STATE.topics.add(id), ch.classList.add("on"));
      render();
    };
  });
  $("#clearTopics").onclick = () => {
    STATE.topics.clear();
    document.querySelectorAll("#topicChips .chip[data-topic]").forEach((c) => c.classList.remove("on"));
    render();
  };
  document.querySelectorAll("#groupChips .chip[data-group]").forEach((ch) => {
    ch.onclick = () => {
      const id = ch.dataset.group;
      STATE.groups.has(id) ? (STATE.groups.delete(id), ch.classList.remove("on"))
                           : (STATE.groups.add(id), ch.classList.add("on"));
      render();
    };
  });
}

function toMarkdown() {
  const list = currentList();
  let md = `# 数字货币与金融稳定 · 论文速览\n\n导出时间：${new Date().toLocaleString("zh-CN")}　共 ${list.length} 篇\n\n`;
  for (const g of STATE.data.groups) {
    const bucket = list.filter((i) => i.group === g.id);
    if (!bucket.length) continue;
    md += `\n## ${g.label}\n\n`;
    for (const it of bucket) {
      md += `### [${it.title}](${it.link})\n`;
      md += `- **来源**：${it.org}（${it.org_cn}）· ${it.ptype} · ${fmtDate(it.date)}\n`;
      if (it.authors) md += `- **作者**：${it.authors}\n`;
      md += `- **主题**：${it.meta.topics.map((t) => t.label).join("、") || "—"}\n`;
      if (it.cn) {
        md += `- **一句话**：${it.cn["一句话"] || ""}\n`;
        for (const f of ["问题", "数据", "方法", "发现", "含义"]) if (it.cn[f]) md += `- **${f}**：${it.cn[f]}\n`;
      } else {
        md += `- **要点**：${it.meta.lead}\n`;
      }
      md += "\n";
    }
  }
  return md;
}

function toCsv() {
  const list = currentList();
  const head = ["日期", "机构", "机构中文", "类型", "标题", "作者", "主题", "一句话中文", "数据", "方法", "相关度", "链接"];
  const q = (s) => '"' + String(s == null ? "" : s).replace(/"/g, '""') + '"';
  const rows = list.map((it) => [
    fmtDate(it.date), it.org, it.org_cn, it.ptype, it.title, it.authors,
    it.meta.topics.map((t) => t.label).join("|"),
    it.cn ? it.cn["一句话"] : it.meta.lead,
    (it.cn && it.cn["数据"]) || it.meta.data.join("|"),
    (it.cn && it.cn["方法"]) || it.meta.method.join("|"),
    it.meta.score, it.link,
  ].map(q).join(","));
  return "﻿" + head.map(q).join(",") + "\n" + rows.join("\n");
}

async function boot() {
  try {
    if (window.__DATA) {
      // data.js 已随页面加载（file:// 直接打开时走这条路）
      STATE.data = window.__DATA;
    } else {
      const res = await fetch("./data.json?t=" + Date.now());
      if (!res.ok) throw new Error("HTTP " + res.status);
      STATE.data = await res.json();
    }
  } catch (e) {
    $("#grid").innerHTML =
      `<div class="empty"><h2>读不到 data.json</h2><p>${esc(e.message)}</p>
       <p>如果是刚建好仓库，先在 Actions 里手动跑一次 <b>weekly-fetch</b>，等它提交 docs/data.json 之后再刷新。</p></div>`;
    return;
  }
  STATE.items = STATE.data.items || [];
  buildChips();
  renderStatus();
  render();
  const t = new Date(STATE.data.generated_at);
  $("#lastrun").innerHTML = "数据更新于 <b>" +
    t.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) + "</b>";
}

$("#q").oninput = (e) => { STATE.q = e.target.value; render(); };
$("#win").onchange = (e) => { STATE.win = +e.target.value; render(); };
$("#sort").onchange = (e) => { STATE.sort = e.target.value; render(); };
$("#strict").onchange = (e) => { STATE.strict = e.target.checked; render(); };
$("#onlyCn").onchange = (e) => { STATE.onlyCn = e.target.checked; render(); };
$("#weekBtn").onclick = () => {
  STATE.win = 7; STATE.sort = "score";
  $("#win").value = "7"; $("#sort").value = "score";
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
};
$("#themeBtn").onclick = () => {
  const cur = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", cur === "light" ? "dark" : "light");
};
$("#copyMd").onclick = async () => {
  try { await navigator.clipboard.writeText(toMarkdown()); $("#copyMd").textContent = "已复制"; setTimeout(() => ($("#copyMd").textContent = "复制 MD"), 1400); }
  catch (e) { alert("复制失败，请手动选择。"); }
};
$("#dlCsv").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([toCsv()], { type: "text/csv;charset=utf-8" }));
  a.download = "papers_" + new Date().toISOString().slice(0, 10) + ".csv";
  a.click(); URL.revokeObjectURL(a.href);
};
grid.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-cite]");
  if (!btn) return;
  const it = STATE.items.find((i) => i.key === btn.dataset.cite);
  if (!it) return;
  const txt = `${it.authors || it.org} (${(it.date || "").slice(0, 4) || "n.d."}). ${it.title}. ${it.org} ${it.ptype}. ${it.link}`;
  navigator.clipboard.writeText(txt).then(() => {
    btn.textContent = "已复制"; setTimeout(() => (btn.textContent = "复制引用"), 1400);
  });
});
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== $("#q")) { e.preventDefault(); $("#q").focus(); }
});

boot();
