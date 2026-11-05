# CLAUDE.md

本專案的規則全部寫在 AGENTS.md，Claude Code 和其他 agent 共用同一份：

@AGENTS.md

## Claude Code 補充

- 回覆用繁體中文。
- 動手前先讀 AGENTS.md 第 7 節「新增一頁的步驟」，照順序做。每改完一頁就跑 `python scripts/check.py --slug <slug>`。
- 內容來源在貓健康站的原始碼（content/articles/*.md）；本機沒有的話，只能用 data/site_articles.json 已列出的文章，不要上網找別的來源。
- check.py 回報 FAIL 時，改內容，不改規則；認為規則本身有問題，先問負責人。
