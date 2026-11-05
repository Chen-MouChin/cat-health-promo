#!/usr/bin/env python3
"""貓健康站推廣頁產線：content/**/*.md + data/*.json → docs/（GitHub Pages 從 main 的 /docs 發佈）。

只用 Python 標準函式庫。用法：
    python build.py          # 全量重建 docs/
規則寫在 AGENTS.md；內容檢查在 scripts/check.py（build 前會先跑，有 FAIL 就不產出）。
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
TEMPLATES = ROOT / "templates"
DOCS = ROOT / "docs"

# 頁面類型：資料夾、網址前綴、中文名稱、首頁區塊標題
TYPES = {
    "card": {"dir": "cards", "name": "衛教小卡", "section": "衛教小卡：30 秒看懂一件事"},
    "feature": {"dir": "features", "name": "網站功能", "section": "貓健康站網站上有什麼"},
    "audience": {"dir": "audiences", "name": "給這樣的飼主", "section": "你是哪一種飼主"},
}

CITE_RE = re.compile(r"\[\^([A-Za-z0-9-]+)\]")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([a-z0-9]+):([^)]+)\)")


def load_json(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


BRAND = load_json("brand.json")
SOURCES = load_json("sources.json")
ARTICLES = load_json("site_articles.json")["articles"]


# ---------- 讀檔 ----------

def parse_page(path: Path) -> dict:
    """讀一個 content/*.md：frontmatter（key: value、[a, b] 列表）+ 正文，回傳 dict。"""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path}: 開頭缺 --- frontmatter ---")
    meta: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            value = [x.strip() for x in value[1:-1].split(",") if x.strip()]
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif re.fullmatch(r"-?\d+", value):
            value = int(value)
        meta[key] = value
    meta["slug"] = path.stem
    meta["path"] = path
    meta["body"] = m.group(2).strip("\n")
    meta["sections"] = split_sections(meta["body"])
    return meta


def split_sections(body: str) -> dict:
    """依 `## 標題` 切段，回傳 {標題: 原始 markdown}；第一個標題前的文字放在 key ""。"""
    sections: dict = {}
    current = ""
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            sections[current] = "\n".join(buf).strip()
            current, buf = line[3:].strip(), []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).strip()
    return sections


def list_items(md: str) -> list[str]:
    return [line[2:].strip() for line in md.splitlines() if line.startswith("- ")]


def load_pages() -> dict:
    pages = {t: [] for t in TYPES}
    for t, conf in TYPES.items():
        for path in sorted((CONTENT / conf["dir"]).glob("*.md")):
            page = parse_page(path)
            page["declared_type"] = page.get("type")  # frontmatter 寫的，check.py 會比對資料夾
            page["type"] = t
            pages[t].append(page)
        pages[t].sort(key=lambda p: (p.get("order", 999), p["slug"]))
    return pages


# ---------- 網址 ----------

def with_utm(url: str, medium: str, campaign: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_source={BRAND['utm_source']}&utm_medium={medium}&utm_campaign={campaign}"


def page_href(t: str, slug: str, prefix: str) -> str:
    return f"{prefix}{TYPES[t]['dir']}/{slug}.html"


class Ctx:
    """渲染一頁時的狀態：相對路徑前綴、UTM、出處編號。"""

    def __init__(self, prefix: str, medium: str, campaign: str):
        self.prefix, self.medium, self.campaign = prefix, medium, campaign
        self.cited: list[str] = []

    def link(self, scheme: str, target: str) -> str:
        if scheme in TYPES:
            return page_href(scheme, target, self.prefix)
        if scheme == "article":
            return with_utm(f"{BRAND['site_url']}articles/{target}.html", self.medium, self.campaign)
        if scheme == "site":
            return with_utm(BRAND["site_links"][target]["url"], self.medium, self.campaign)
        raise ValueError(f"不認得的連結 {scheme}:{target}")

    def cite(self, key: str) -> str:
        if key not in self.cited:
            self.cited.append(key)
        n = self.cited.index(key) + 1
        return f'<sup class="cite"><a href="#src-{key}" aria-label="出處 {n}">{n}</a></sup>'


# ---------- markdown（只支援本專案用到的語法） ----------

def inline(s: str, ctx: Ctx) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = CITE_RE.sub(lambda m: ctx.cite(m.group(1)), s)
    s = LINK_RE.sub(lambda m: f'<a href="{html.escape(ctx.link(m.group(2), m.group(3)))}">{m.group(1)}</a>', s)
    return s


def strip_md(s: str) -> str:
    """去掉出處、粗體、連結語法，留純文字（卡片圖、meta description 用）。"""
    s = CITE_RE.sub("", s)
    s = LINK_RE.sub(lambda m: m.group(1), s)
    return s.replace("**", "").strip()


def md_blocks(md: str, ctx: Ctx, h_offset: int = 0) -> str:
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush():
        nonlocal para, items
        if para:
            out.append(f"<p>{inline(''.join(para), ctx)}</p>")
            para = []
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i, ctx)}</li>" for i in items) + "</ul>")
            items = []

    for line in md.splitlines():
        if line.startswith("### "):
            flush()
            out.append(f"<h{3 + h_offset}>{inline(line[4:], ctx)}</h{3 + h_offset}>")
        elif line.startswith("## "):
            flush()
            out.append(f"<h{2 + h_offset}>{inline(line[3:], ctx)}</h{2 + h_offset}>")
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:].strip())
        elif not line.strip():
            flush()
        else:
            if items:
                flush()
            para.append(line.strip())
    flush()
    return "\n".join(out)


# ---------- 共用片段 ----------

def cat_svg(name: str, cls: str = "cat") -> str:
    svg = (ASSETS / "cats" / f"{name}.svg").read_text(encoding="utf-8")
    return svg.replace("<svg ", f'<svg class="{cls}" aria-hidden="true" focusable="false" ', 1)


def sources_block(ctx: Ctx) -> str:
    if not ctx.cited:
        return ""
    rows = []
    for key in ctx.cited:
        s = SOURCES[key]
        year = f"（{s['year']}）" if s.get("year") else ""
        rows.append(
            f'<li id="src-{key}">{html.escape(s["authors"])}{year}. '
            f'<a href="{html.escape(s["url"])}" rel="noopener">{html.escape(s["title"])}</a></li>'
        )
    return '<section class="sources"><h2>出處</h2><ol>' + "".join(rows) + "</ol></section>"


def article_link(slug: str, ctx: Ctx, cls: str = "") -> str:
    a = ARTICLES[slug]
    return (f'<a class="{cls}" href="{html.escape(ctx.link("article", slug))}">'
            f'<span>{html.escape(a["label"])}</span><span class="arrow" aria-hidden="true">→</span></a>')


def site_button(key: str, ctx: Ctx, cls: str = "btn") -> str:
    link = BRAND["site_links"][key]
    return f'<a class="{cls}" href="{html.escape(ctx.link("site", key))}">{html.escape(link["label"])}</a>'


def tile(page: dict, prefix: str) -> str:
    """首頁卡片：只有標題和一句說明。"""
    t = page["type"]
    return (f'<a class="tile" href="{page_href(t, page["slug"], prefix)}">'
            f'<span class="tile-title">{html.escape(page["title"])}</span>'
            f'<span class="tile-summary">{html.escape(page["summary"])}</span></a>')


def flip(fid: str, front: str, back: str, label: str, cls: str = "") -> str:
    """翻面卡：只用 CSS（checkbox + label），不需要 JavaScript。點一下或按空白鍵翻面。
    兩面疊在同一個格子裡，卡片高度取兩面較高的那一面，所以長句會換行、不會撐破版面。"""
    return (f'<div class="flip {cls}"><input class="flip-toggle" type="checkbox" id="{fid}" aria-label="{html.escape(label)}">'
            f'<label class="flip-inner" for="{fid}">'
            f'<div class="face front">{front}<span class="flip-hint" aria-hidden="true">點一下看細節 ↻</span></div>'
            f'<div class="face back">{back}<span class="flip-hint" aria-hidden="true">點一下翻回 ↻</span></div>'
            f'</label></div>')


def card_flip(page: dict, prefix: str, ctx) -> str:
    """首頁的衛教小卡：正面是大標和三個重點短句，背面是導言和兩個出口。"""
    points = [strip_md(pt).split("。")[0] for pt in list_items(page["sections"]["三個重點"])]
    front = (f'<p class="flip-kicker">{html.escape(page.get("topic", ""))}</p>'
             f'<h3 class="flip-title">{headline_html(page["headline"])}</h3>'
             f'<ol class="flip-points">{"".join(f"<li><span>{headline_html(x)}</span></li>" for x in points)}</ol>'
             f'<span class="flip-cat-wrap">{cat_svg(page["cat"], "flip-cat")}</span>')
    back = (f'<h3 class="flip-title">{headline_html(page["title"])}</h3>'
            f'<p class="flip-text">{html.escape(page["summary"])}</p>'
            f'<span class="flip-links"><a href="{page_href("card", page["slug"], prefix)}">看完整小卡 →</a>'
            f'<a href="{html.escape(ctx.link("article", page["article"]))}">讀網站文章 →</a></span>')
    return flip(f'home-{page["slug"]}', front, back, f'翻面看「{page["headline"]}」的細節')


def link_list(items: list, prefix: str) -> str:
    """內頁底部的延伸連結：文字清單，不用卡片。"""
    lis = "".join(
        f'<li><a href="{page_href(q["type"], q["slug"], prefix)}">{html.escape(q["title"])}</a>'
        f'<span>{html.escape(q["summary"])}</span></li>' for q in items)
    return f'<ul class="link-list">{lis}</ul>'


def render(template: str, **kw) -> str:
    out = (TEMPLATES / template).read_text(encoding="utf-8")
    for k, v in kw.items():
        out = out.replace("{{" + k + "}}", str(v))
    leftover = re.findall(r"\{\{\w+\}\}", out)
    if leftover:
        raise ValueError(f"{template} 有沒填的欄位：{leftover}")
    return out


def shell(title: str, description: str, prefix: str, body: str, active: str, ctx: Ctx, cta_html: str) -> str:
    current = ' aria-current="page"'
    nav = "".join(
        f'<a href="{prefix}index.html#{t}"{current if t == active else ""}>{conf["name"]}</a>'
        for t, conf in TYPES.items()
    )
    return render(
        "base.html",
        title=html.escape(title),
        description=html.escape(description),
        prefix=prefix,
        nav=nav,
        body=body,
        sticky_cta=cta_html,
        site_home=html.escape(ctx.link("site", "home")),
        site_name=html.escape(BRAND["name"]),
        disclaimer=html.escape(BRAND["disclaimer"]),
        library=html.escape(ctx.link("site", "library")),
    )


def sticky(href: str, label: str) -> str:
    return f'<a class="sticky-cta" href="{html.escape(href)}">{html.escape(label)}<span aria-hidden="true">→</span></a>'


# ---------- 各類型頁面 ----------

def headline_html(text: str) -> str:
    """大標只在標點後面斷行：每一段包成 inline-block，避免「尿不出／來」這種斷法。"""
    parts = re.findall(r"[^，、：；]+[，、：；]?", text)
    return "".join(f'<span class="nobr">{html.escape(x)}</span>' for x in parts)


def render_card(p: dict, pages: dict) -> tuple[str, str]:
    ctx = Ctx("../", "card", p["slug"])
    points = list_items(p["sections"]["三個重點"])
    vet = p["sections"].get("什麼時候要找獸醫", "")
    home = p["sections"].get("在家可以做的事", "")
    art = p["article"]

    # 社群貼文卡（4:5，網頁上顯示縮小版；-post.html 是 1080×1350 原尺寸給截圖）
    card_points = "".join(f"<li><span>{headline_html(strip_md(pt).split('。')[0])}</span></li>" for pt in points)
    post_card = (f'<div class="post-card"><div class="post-body">'
                 f'<div class="post-top"><img src="../assets/logo.svg" alt="{html.escape(BRAND["name"])}"><span>衛教小卡</span></div>'
                 f'<h2 class="post-headline">{headline_html(p["headline"])}</h2>'
                 f'<ol class="post-points">{card_points}</ol>'
                 f'{cat_svg(p["cat"], "post-cat")}'
                 f'<div class="post-foot"><span>完整文章與出處：cathealthtw.com</span><span>{html.escape(BRAND["disclaimer"])}</span></div>'
                 f'</div></div>')

    def post_back():
        items = []
        for pt in points:
            m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", pt)
            head, detail = (m.group(1), m.group(2)) if m else (pt, "")
            items.append(f"<li><strong>{html.escape(head)}</strong>{inline(detail, ctx)}</li>")
        return (f'<p class="flip-kicker">細節</p><h3 class="flip-title">{headline_html(p["title"])}</h3>'
                f'<ol class="post-back-list">{"".join(items)}</ol>'
                f'<a class="post-back-link" href="#vet">什麼時候要找獸醫 ↓</a>')
    post_flip = flip(f'post-{p["slug"]}', post_card, post_back(), "翻面看這張小卡的細節", "post-flip")

    urgent = p.get("cta") == "vets_night"
    vet_btn = site_button("vets_night" if urgent else "vets", ctx, "btn btn-urgent" if urgent else "btn btn-ghost")
    related = [q for q in pages["card"] if q["slug"] in p.get("related", [])]

    body = f"""
<article class="page page-card">
  <header class="page-head">
    <p class="kicker">衛教小卡・{html.escape(p.get("topic", ""))}</p>
    <h1>{headline_html(p["title"])}</h1>
    <p class="lead">{inline(p["sections"].get("", ""), ctx)}</p>
  </header>
  <div class="card-layout">
    <figure class="post-preview">{post_flip}
      <figcaption>點卡片翻面看細節・<a href="{p['slug']}-post.html">開原尺寸（1080×1350，給社群貼文用）</a></figcaption>
    </figure>
      {f'<section id="vet" class="vet-box{" vet-urgent" if urgent else ""}"><h2>什麼時候要找獸醫</h2>{md_blocks(vet, ctx)}{vet_btn}</section>' if vet else ""}
  </div>
  {f'<section class="home-care"><h2>在家可以做的事</h2>{md_blocks(home, ctx)}</section>' if home else ""}
  <section class="funnel">
    <p class="funnel-label">想知道更多，看網站上的完整文章：</p>
    {article_link(art, ctx, "funnel-main")}
  </section>
  {sources_block(ctx)}
  {f'<section class="more"><h2>其他小卡</h2>{link_list(related, "../")}</section>' if related else ""}
</article>"""
    page = shell(p["title"], p["summary"], "../", body, "card", ctx,
                 sticky(ctx.link("article", art), "讀完整文章"))

    post = render("post.html", title=html.escape(p["title"]), card=post_card)
    return page, post


def render_feature(p: dict, pages: dict) -> str:
    ctx = Ctx("../", "feature", p["slug"])
    audiences = [q for q in pages["audience"] if p["slug"] in q.get("features", [])]
    sections = {k: v for k, v in p["sections"].items() if k}
    body_html = "".join(f"<section><h2>{html.escape(k)}</h2>{md_blocks(v, ctx)}</section>" for k, v in sections.items())
    link = BRAND["site_links"][p["site_link"]]
    body = f"""
<article class="page page-feature">
  <header class="page-head with-cat">
    {cat_svg(p["cat"], "head-cat")}
    <div>
      <p class="kicker">{html.escape(BRAND["name"])}・網站功能</p>
      <h1>{headline_html(p["title"])}</h1>
      <p class="lead">{inline(p["sections"].get("", ""), ctx)}</p>
    </div>
  </header>
  {body_html}
  <section class="funnel">
    <p class="funnel-label">直接到網站上用：</p>
    <a class="funnel-main" href="{html.escape(ctx.link("site", p["site_link"]))}"><span>{html.escape(link["label"])}</span><span class="arrow" aria-hidden="true">→</span></a>
    {f'<p class="funnel-label funnel-sub">相關文章：</p>{article_link(p["article"], ctx, "reading-link")}' if p.get("article") else ""}
  </section>
  {sources_block(ctx)}
  {f'<section class="more"><h2>適合這樣的飼主</h2>{link_list(audiences, "../")}</section>' if audiences else ""}
</article>"""
    return shell(p["title"], p["summary"], "../", body, "feature", ctx, sticky(ctx.link("site", p["site_link"]), link["label"]))


def render_audience(p: dict, pages: dict) -> str:
    ctx = Ctx("../", "audience", p["slug"])
    sections = {k: v for k, v in p["sections"].items() if k}
    body_html = "".join(f"<section><h2>{html.escape(k)}</h2>{md_blocks(v, ctx)}</section>" for k, v in sections.items())
    feats = [q for q in pages["feature"] if q["slug"] in p.get("features", [])]
    cards = [q for q in pages["card"] if q["slug"] in p.get("cards", [])]
    reading = "".join(f"<li>{article_link(a, ctx, 'reading-link')}</li>" for a in p["articles"])
    body = f"""
<article class="page page-audience">
  <header class="page-head with-cat">
    {cat_svg(p["cat"], "head-cat")}
    <div>
      <p class="kicker">給這樣的飼主</p>
      <h1>{headline_html(p["title"])}</h1>
      <p class="lead">{inline(p["sections"].get("", ""), ctx)}</p>
    </div>
  </header>
  {body_html}
  <section class="funnel">
    <h2>先讀這幾篇</h2>
    <ol class="reading">{reading}</ol>
  </section>
  {f'<section class="more"><h2>也可以看</h2>{link_list(cards + feats, "../")}</section>' if cards or feats else ""}
  {sources_block(ctx)}
</article>"""
    first = p["articles"][0]
    return shell(p["title"], p["summary"], "../", body, "audience", ctx, sticky(ctx.link("article", first), "先讀第一篇"))


def render_index(pages: dict) -> str:
    ctx = Ctx("", "index", "home")
    blocks = []
    for t, conf in TYPES.items():
        if pages[t]:
            inner = ("".join(card_flip(p, "", ctx) for p in pages[t]) if t == "card"
                     else "".join(tile(p, "") for p in pages[t]))
            grid = "flip-grid" if t == "card" else "tiles"
            blocks.append(f'<section class="home-section" id="{t}"><h2>{conf["section"]}</h2>'
                          f'<div class="{grid}">{inner}</div></section>')
    body = f"""
<section class="hero">
  {cat_svg("mochi-lying", "hero-cat")}
  <div class="hero-text">
    <h1>{headline_html(BRAND["site_tagline"])}</h1>
    <p class="lead">每篇文章都附上獸醫指引和論文的出處；全台動物醫院可以照縣市查，也能只看夜間急診。</p>
    <p class="app-note"><img src="assets/icon.svg" alt="" width="28" height="28"><span>{html.escape(BRAND["app_status_text"])}</span></p>
    <div class="btn-row">{site_button("home", ctx, "btn")}<a class="btn btn-ghost" href="#card">先看衛教小卡</a></div>
  </div>
</section>
{"".join(blocks)}
<section class="vets-band">
  {cat_svg("carrier", "band-cat")}
  <div><h2>半夜貓不舒服，要找醫院？</h2><p>貓健康站整理了全台動物醫院，可以只看夜間急診。</p>
  <div class="btn-row">{site_button("vets_night", ctx, "btn btn-urgent")}{site_button("vets", ctx, "btn btn-ghost")}</div></div>
</section>"""
    return shell(f'{BRAND["name"]}｜推廣頁', BRAND["site_tagline"], "", body, "", ctx, sticky(ctx.link("site", "home"), "到貓健康站"))


# ---------- 主程式 ----------

def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    import check  # noqa: E402

    pages = load_pages()
    if check.run(pages, quiet=True) > 0:
        print("build 中止：先修好 scripts/check.py 列出的 FAIL（python scripts/check.py）")
        return 1

    # 清空 docs/ 的內容，不刪資料夾本身（資料夾被檔案總管或終端機開著時也能 build）
    DOCS.mkdir(exist_ok=True)
    for child in DOCS.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (DOCS / "assets").mkdir()
    for t, conf in TYPES.items():
        (DOCS / conf["dir"]).mkdir()
    shutil.copytree(ASSETS, DOCS / "assets", dirs_exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    count = 0
    for p in pages["card"]:
        page, post = render_card(p, pages)
        (DOCS / "cards" / f"{p['slug']}.html").write_text(page, encoding="utf-8")
        (DOCS / "cards" / f"{p['slug']}-post.html").write_text(post, encoding="utf-8")
        count += 2
    for p in pages["feature"]:
        (DOCS / "features" / f"{p['slug']}.html").write_text(render_feature(p, pages), encoding="utf-8")
        count += 1
    for p in pages["audience"]:
        (DOCS / "audiences" / f"{p['slug']}.html").write_text(render_audience(p, pages), encoding="utf-8")
        count += 1
    (DOCS / "index.html").write_text(render_index(pages), encoding="utf-8")
    count += 1

    n = {t: len(v) for t, v in pages.items()}
    print(f"完成：{count} 個 HTML → docs/（小卡 {n['card']}、功能 {n['feature']}、族群 {n['audience']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
