# 雲端 Telegram 排程

此工作流程以 GitHub Actions 在每天台灣時間 08:00 執行 `analyze_twse_momentum.py`，由 GitHub 的雲端執行器讀取資料來源並推播 Telegram，因此不依賴個人電腦開機。

## 首次啟用

1. 將此專案推送到你自己的 GitHub 私有儲存庫。
2. 在 GitHub 儲存庫的 `Settings → Secrets and variables → Actions` 新增兩個 Repository secrets：
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. 到 `Actions → Daily Taiwan Stock Tier Telegram` 點選 `Run workflow` 一次，確認能收到測試訊息。

Token 僅存在 GitHub 的加密 Secrets，絕對不要寫進程式碼、README 或 Git commit。

## 範圍

這個雲端工作流程會抓取最新排行並發送 Telegram。網站目前使用 Sites 發布，尚未提供可由 GitHub Actions 自動更新的發布憑證；因此網站自動發布與每日 LLM 產品覆核需要另接雲端部署／LLM 執行服務，不能將本機憑證複製進 workflow。
