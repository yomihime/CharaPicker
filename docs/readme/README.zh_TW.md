# CharaPicker / 拾卡姬（繁體中文）

[简体中文](../../README.md) | [日本語](README.ja_JP.md) | [English](README.en_US.md)

## 專案簡介

CharaPicker（拾卡姬）是一個桌面工具，從番劇、漫畫、影片、圖片或文字素材中提取角色資訊，並產出結構化角色檔案與洞察。

## 核心目標

- Extract Once：素材盡量只處理一次，沉澱可重用知識庫。
- Targeted Insight：圍繞指定角色或世界觀輸出定向洞察。
- Visible Thinking：在介面中展示關鍵洞察流，而不只是除錯日誌。

## 目前狀態

- 版本：`v0.7.0-beta`（開發中）
- 文件更新時間：`2026-06-05`

## 已實現內容

- 啟動流程與預熱鏈路：啟動畫面、主題套用、基礎環境探測。
- 主介面骨架：專案頁、角色卡頁、模型頁、提示詞頁、設定頁、關於頁。
- 專案配置管理：專案配置保存/讀取、最近專案列表。
- 素材處理鏈路：導入 `raw/`、連結/處理到 `materials/`，支援 FFmpeg 分段與轉碼配置。
- 洞察流介面：InsightStreamPanel 卡片時間線顯示與流式更新。
- 雲端模型接入：透過統一中介層發起 OpenAI-compatible 請求並記錄 token usage。
- 預覽鏈路打通：`project -> extractor -> insight stream -> preview knowledge base`。
- 角色卡頁面：支援專案內角色卡海報牆、搜尋、建立、編輯、封面裁剪、預覽、編譯、匯入和匯出。

## 專案進度

- 已完成：可執行的 UI 骨架與預覽主流程。
- 進行中：從真實素材生成更高品質、可重用的結構化洞察。
- 下一階段重點：先穩住正式提取品質與可觀測性，再做多素材前解耦，最後推進文字、音訊、圖片、漫畫等多素材支援。

## 未完成項

- 真實素材預覽已開始接入 `materials/` 中的影片 chunk 和雲端模型，但文字、字幕、漫畫／圖片等完整真實素材消費鏈路仍在完善。
- 角色卡編譯已能從正式知識庫生成 CharaPicker JSON，並具備分層證據、別名重分類、品質診斷和未出場角色失敗保護。
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
- 專案內角色卡管理與 CharaPicker JSON 母本
- 提取階段洞察事件流（Insight Stream）
- 角色卡 Markdown、HTML、Character Card V2 JSON 和 AstrBot 手動複製清單匯出（持續迭代中）

## 截圖

- 截圖文件待補充。

## 文件導航

- [简体中文 README](../../README.md)
- [日本語 README](README.ja_JP.md)
- [English README](README.en_US.md)
- [更新日誌](../../CHANGELOG.md)
- [docs 架構說明](../ARCHITECTURE.md)
- [根目錄架構說明](../../ARCHITECTURE.md)

## 開發說明

- 本專案遵循目錄邊界：`core` / `gui` / `utils` 分層清楚。
- UI 可見文字應透過 `i18n/` 管理，避免長期硬編碼。
- 執行時資源統一放在 `res/`。

## 授權

- CharaPicker 自有原始碼採用 [Mozilla Public License 2.0](../../LICENSE)（`MPL-2.0`）。
- 第三方依賴與打包產物中的第三方元件遵循各自授權，見 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。
- 目前開源構建使用 GPL 授權的 PyQt6 / PyQt6-Fluent-Widgets 元件；發布二進位包時也需要遵守這些第三方授權義務。
