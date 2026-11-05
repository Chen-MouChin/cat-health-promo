# 貓健康站宣傳網頁

替[貓健康站](https://cathealthtw.com/)做推廣頁的小專案。重點不在某一頁，而是一套規則：寫一個 Markdown 檔、跑一次 build，就多一張衛教小卡、一個網站功能頁或一個族群頁，而且每一頁都會導流回網站。

- 網頁：https://chen-mouchin.github.io/cat-health-promo/
- 規則：[AGENTS.md](AGENTS.md)（[CLAUDE.md](CLAUDE.md) 匯入同一份）

## 三種頁面

| 類型 | 內容 | 例子 |
|---|---|---|
| 衛教小卡 | 一件事、三個重點，附 1080×1350 社群貼文圖 | 公貓尿不出來、砂盆怎麼擺、各年齡怎麼吃、結紮與術後 |
| 網站功能頁 | 網站上一個已上線的功能 | 每篇文章都附出處、全台動物醫院查詢、各縣市結紮補助 |
| 族群頁 | 一種飼主的困擾與建議閱讀順序 | 家裡的貓有慢性病、第一次養貓 |

## 使用

```bash
python scripts/check.py      # 檢查全部內容（用語、出處、術語、連結、欄位）
python build.py              # 檢查通過才產出 docs/
python -m http.server 8000 --bind 127.0.0.1 --directory docs
```

只需要 Python 3.10 以上，不用安裝套件。

## 新增一頁

照 AGENTS.md 第 7 節：複製 `templates/new/<類型>.md` → 填欄位與正文 → `check.py` → `build.py`。

## 來源與授權

- 內容縮寫自貓健康站已審核的文章，出處列在每頁頁尾。
- 色票、線條貓插畫、Logo 為貓健康站自有素材。
- 開發協作：規則、程式與頁面由陳孟擎（Chen-MouChin）規劃，Claude Code（Anthropic）協助撰寫；每次 commit 以 Co-Authored-By 標示。
