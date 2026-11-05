#!/usr/bin/env python3
"""內容檢查：把 AGENTS.md 裡能機器檢查的規則全部檢查一遍。

用法：
    python scripts/check.py              # 檢查全部頁面
    python scripts/check.py --slug X     # 只看某一頁
有任何 FAIL 就回傳 1；build.py 會先跑這支，有 FAIL 就不產出。
規則的資料（禁用詞、術語、出處、可導流的文章）都在 data/，改規則改那邊。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


WORDING = load("wording.json")
TERMS = {k: v for k, v in load("terms.json").items() if not k.startswith("_")}
SOURCES = {k: v for k, v in load("sources.json").items() if not k.startswith("_")}
ARTICLES = load("site_articles.json")["articles"]
BRAND = load("brand.json")
CATS = {p.stem for p in (ROOT / "assets" / "cats").glob("*.svg")}

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CITE_RE = re.compile(r"\[\^([A-Za-z0-9-]+)\]")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")
SCHEME_RE = re.compile(r"^([a-z0-9]+):(.+)$")
NUM_RE = re.compile(r"\d[\d.,～~–\-到至]*\s*(?:" + WORDING["number_units"] + r")")

# 各類型必填欄位、必要段落（## 標題）、字數上限
SCHEMA = {
    "card": {
        "fields": ["type", "title", "headline", "summary", "topic", "cat", "order", "article", "updated"],
        "sections": ["三個重點", "什麼時候要找獸醫"],
        "allowed_sections": ["三個重點", "什麼時候要找獸醫", "在家可以做的事"],
    },
    "feature": {
        "fields": ["type", "title", "summary", "cat", "order", "site_features", "site_link", "updated"],
        "sections": ["怎麼用", "你會看到什麼"],
        "allowed_sections": ["怎麼用", "你會看到什麼", "資料從哪來"],
    },
    "audience": {
        "fields": ["type", "title", "summary", "cat", "order", "articles", "features", "updated"],
        "sections": ["你可能遇過", "貓健康站能幫的地方"],
        "allowed_sections": ["你可能遇過", "貓健康站能幫的地方"],
    },
}
LIMITS = {"title": 24, "summary": 40, "headline": 16}
CARD_POINT_HEAD = 18  # 小卡重點粗體句（第一個句號前）的字數上限，圖上放得下


class Report:
    def __init__(self):
        self.fails: list[str] = []
        self.warns: list[str] = []

    def fail(self, where, msg):
        self.fails.append(f"FAIL {where}: {msg}")

    def warn(self, where, msg):
        self.warns.append(f"WARN {where}: {msg}")


def visible_text(md: str) -> str:
    """正文去掉出處標記與連結網址，只留讀者看得到的字。"""
    md = CITE_RE.sub("", md)
    return LINK_RE.sub(lambda m: m.group(1), md)


def check_page(p: dict, all_slugs: dict, r: Report):
    where = f"{p['type']}/{p['slug']}"
    schema = SCHEMA[p["type"]]

    # 1. 檔名、類型、欄位
    if not SLUG_RE.match(p["slug"]):
        r.fail(where, "檔名要是英文小寫 kebab-case，例如 litter-box-setup.md")
    if p.get("declared_type") != p["type"]:
        r.fail(where, f"frontmatter type 是「{p.get('declared_type')}」，但檔案放在 content/{p['type']}s/")
    for f in schema["fields"]:
        if f not in p or p[f] in ("", []):
            r.fail(where, f"缺欄位 {f}")
    for f, n in LIMITS.items():
        if f in p and isinstance(p[f], str) and len(p[f]) > n:
            r.fail(where, f"{f} 有 {len(p[f])} 字，上限 {n}")
    if p.get("cat") and p["cat"] not in CATS:
        r.fail(where, f"cat「{p['cat']}」不在 assets/cats/，可以用：{', '.join(sorted(CATS))}")
    if p.get("updated") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(p["updated"])):
        r.fail(where, "updated 要寫成 YYYY-MM-DD")

    # 2. 段落
    secs = p["sections"]
    if not secs.get(""):
        r.fail(where, "第一個 ## 標題前要有一段導言（顯示在標題下面）")
    for s in schema["sections"]:
        if s not in secs:
            r.fail(where, f"缺段落「## {s}」")
    for s in secs:
        if s and s not in schema["allowed_sections"]:
            r.fail(where, f"段落「## {s}」不在這個類型允許的段落裡：{'、'.join(schema['allowed_sections'])}")

    if p["type"] == "card" and "三個重點" in secs:
        items = [l[2:] for l in secs["三個重點"].splitlines() if l.startswith("- ")]
        if len(items) != 3:
            r.fail(where, f"「三個重點」要剛好 3 條，現在 {len(items)} 條")
        for i, it in enumerate(items, 1):
            m = re.match(r"^\*\*(.+?)\*\*", it)
            if not m:
                r.fail(where, f"重點 {i} 要用 **粗體短句。** 開頭")
            elif len(m.group(1).rstrip("。")) > CARD_POINT_HEAD:
                r.fail(where, f"重點 {i} 的粗體句 {len(m.group(1))} 字，上限 {CARD_POINT_HEAD}（要放進社群圖）")
            if not CITE_RE.search(it):
                r.fail(where, f"重點 {i} 沒有出處 [^KEY]")

    # 3. 引用與交叉參照
    if p["type"] in ("card", "feature") and p.get("article") and p["article"] not in ARTICLES:
        r.fail(where, f"article「{p['article']}」不在 data/site_articles.json（只能導流到已上線、已審核的文章）")
    for a in p.get("articles", []) if isinstance(p.get("articles"), list) else []:
        if a not in ARTICLES:
            r.fail(where, f"articles 裡的「{a}」不在 data/site_articles.json")
    for f in p.get("site_features", []) if isinstance(p.get("site_features"), list) else []:
        if f not in BRAND["site_features"]:
            r.fail(where, f"site_features「{f}」不在 data/brand.json 的 site_features（只能寫網站上已經有的功能）")
    if p["type"] == "feature" and p.get("site_link") and p["site_link"] not in BRAND["site_links"]:
        r.fail(where, f"site_link「{p['site_link']}」不在 brand.json 的 site_links")
    for key, t in (("features", "feature"), ("cards", "card"), ("related", "card")):
        for s in p.get(key, []) if isinstance(p.get(key), list) else []:
            if s not in all_slugs[t]:
                r.fail(where, f"{key} 裡的「{s}」找不到 content/{t}s/{s}.md")
    if p["type"] == "card" and p.get("topic") and p["topic"] not in BRAND["card_topics"]:
        r.fail(where, f"topic「{p['topic']}」不在 brand.json 的 card_topics：{'、'.join(BRAND['card_topics'])}（要新分類先加進清單）")
    if p["type"] == "card" and p.get("cta") not in (None, "vets", "vets_night"):
        r.fail(where, "cta 只能是 vets 或 vets_night")

    body = p["body"]
    for key in CITE_RE.findall(body):
        if key not in SOURCES:
            r.fail(where, f"出處 [^{key}] 不在 data/sources.json")
        elif SOURCES[key].get("commercial_use") == "no":
            r.fail(where, f"出處 [^{key}] 是 commercial_use: no，推廣頁不能用")
    for text, target in LINK_RE.findall(body):
        if target.startswith("^"):
            continue
        if re.match(r"^https?://", target):
            r.fail(where, f"連結「{text}」寫了網址；請用 article:slug、site:key、card:slug 這類寫法，build 會自動補 UTM")
            continue
        m = SCHEME_RE.match(target)
        if not m:
            r.fail(where, f"看不懂的連結「{target}」")
            continue
        scheme, val = m.groups()
        if scheme == "article" and val not in ARTICLES:
            r.fail(where, f"article:{val} 不在 data/site_articles.json")
        elif scheme == "site" and val not in BRAND["site_links"]:
            r.fail(where, f"site:{val} 不在 brand.json 的 site_links")
        elif scheme in all_slugs and val not in all_slugs[scheme]:
            r.fail(where, f"{scheme}:{val} 找不到對應頁面")
        elif scheme not in ("article", "site", *all_slugs):
            r.fail(where, f"不認得的連結類型 {scheme}:")
    if re.search(r"cathealthtw\.com", body):
        r.fail(where, "正文不要手寫 cathealthtw.com 網址，用 article: 或 site: 連結")

    # 4. 數字要有出處：含單位的數字所在那一行（段落或清單項目）必須有 [^KEY]
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        if NUM_RE.search(visible_text(line)) and not CITE_RE.search(line):
            r.fail(where, f"這行有數字但沒出處：{line.strip()[:50]}")

    # 5. 用語
    texts = [visible_text(body)] + [str(p.get(k, "")) for k in ("title", "summary", "headline")]
    all_text = "\n".join(texts)
    for b in WORDING["banned"]:
        if b["word"] in all_text:
            r.fail(where, f"用了「{b['word']}」→ 改成：{b['use']}")
    for pat in WORDING["patterns"]:
        m = re.search(pat["regex"], all_text)
        if m:
            r.fail(where, f"「{m.group(0)}」：{pat['why']}")

    # 6. 術語：表上的英文第一次出現時要寫成「中文（英文」
    plain = visible_text(body)
    for key, val in TERMS.items():
        idx = re.search(r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])", plain)
        if not idx:
            continue
        zh = val.split("，")[0]
        start = idx.start()
        if plain[max(0, start - len(zh) - 1):start] != zh + "（":
            r.fail(where, f"術語 {key} 第一次出現要寫成「{zh}（{key}" + ("，" + val.split("，", 1)[1] if "，" in val else "") + "）」")


def check_docs(r: Report):
    """build 之後：每個 HTML 都要有固定免責文字。"""
    docs = ROOT / "docs"
    if not docs.exists():
        r.warn("docs", "還沒 build（python build.py）")
        return
    for f in docs.rglob("*.html"):
        if BRAND["disclaimer"] not in f.read_text(encoding="utf-8"):
            r.fail(f"docs/{f.relative_to(docs).as_posix()}", f"沒有固定文字「{BRAND['disclaimer']}」")


def check_data(r: Report):
    """data/ 本身：導流連結文字也要符合用語規則。"""
    for slug, a in ARTICLES.items():
        for b in WORDING["banned"]:
            if b["word"] in a["label"]:
                r.fail(f"site_articles/{slug}", f"label 用了「{b['word']}」→ 改成：{b['use']}")


def run(pages: dict | None = None, quiet: bool = False, only: str | None = None) -> int:
    if pages is None:
        import build
        pages = build.load_pages()
    all_slugs = {t: {p["slug"] for p in ps} for t, ps in pages.items()}
    r = Report()
    check_data(r)
    for ps in pages.values():
        for p in ps:
            if only is None or p["slug"] == only:
                check_page(p, all_slugs, r)
    if not quiet and only is None:
        check_docs(r)
    for line in r.fails + r.warns:
        print(line)
    total = sum(len(v) for v in pages.values())
    if not r.fails and not quiet:
        print(f"通過：{total} 頁，0 個 FAIL")
    return len(r.fails)


if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--slug") + 1] if "--slug" in sys.argv else None
    sys.exit(1 if run(only=only) else 0)
