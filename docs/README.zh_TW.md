# CharaPicker / 拾卡姬（繁體中文）

[简体中文](../README.md) | [日本語](README.ja_JP.md) | [English](README.en_US.md)

## 專案簡介

CharaPicker（拾卡姬）是一個桌面工具，從番劇、漫畫、影片、圖片或文字素材中提取角色資訊，並產出結構化角色檔案與洞察。

## 核心目標

- Extract Once：素材盡量只處理一次，沉澱可重用知識庫。
- Targeted Insight：圍繞指定角色或世界觀輸出定向洞察。
- Visible Thinking：在介面中展示關鍵洞察流，而不只是除錯日誌。

## 目前狀態

- 版本：`v0.2.0-alpha.1`（開發中）
- 文件更新時間：`2026-05-13`

## 已實現內容

- 啟動流程與預熱鏈路：啟動畫面、主題套用、基礎環境探測。
- 主介面骨架：專案頁、輸出頁、模型頁、提示詞頁、設定頁、關於頁。
- 專案配置管理：專案配置保存/讀取、最近專案列表。
- 素材處理鏈路：導入 `raw/`、連結/處理到 `materials/`，支援 FFmpeg 分段與轉碼配置。
- 洞察流介面：InsightStreamPanel 卡片時間線顯示與流式更新。
- 雲端模型接入：透過統一中介層發起 OpenAI-compatible 請求並記錄 token usage。
- 預覽鏈路打通：`project -> extractor -> insight stream -> compiler -> output`。

## 專案進度

- 已完成：可執行的 UI 骨架與預覽主流程。
- 進行中：從真實素材生成更高品質、可重用的結構化洞察。
- 下一階段重點：知識庫落盤、編譯階段狀態迭代、衝突處理與輸出品質提升。

## 未完成項

- 真實素材預覽已開始接入 `materials/` 中的影片 chunk 和雲端模型，但文字、字幕、漫畫／圖片等完整真實素材消費鏈路仍在完善。
- 編譯階段仍為占位實作，尚未完成完整的迭代編譯與衝突消解。
- 知識庫檔案（如 `facts.json`、`targeted_insights.json`）尚未形成穩定自動寫入閉環。

## 環境需求

- Python `>=3.10`

## 安裝

```powershell
python -m pip install -r requirements.txt
```

## 執行

```powershell
python main.py
```

## 功能概覽

- 專案化素材管理（`projects/{project_id}`）
- 目標角色配置與處理模式配置
- 提取階段洞察事件流（Insight Stream）
- 角色狀態編譯與結構化輸出（持續迭代中）

## 截圖

- 截圖文件待補充。

## 文件導航

- [简体中文 README](../README.md)
- [日本語 README](README.ja_JP.md)
- [English README](README.en_US.md)
- [docs 架構說明](ARCHITECTURE.md)
- [根目錄架構說明](../ARCHITECTURE.md)

## 開發說明

- 本專案遵循目錄邊界：`core` / `gui` / `utils` 分層清楚。
- UI 可見文字應透過 `i18n/` 管理，避免長期硬編碼。
- 執行時資源統一放在 `res/`。

## 授權

- License 待補充。
