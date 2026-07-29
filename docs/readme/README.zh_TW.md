# CharaPicker / 拾卡姬（繁體中文）

[简体中文](../../README.md) | [日本語](README.ja_JP.md) | [English](README.en_US.md)

## 這是什麼

CharaPicker（拾卡姬）是一個個人實驗性質的桌面工具。它嘗試從番劇、漫畫、影片、圖片、音訊和文字素材裡整理角色相關資訊，再把這些資訊沉澱成可追蹤的知識庫和角色檔案。

它不是成熟的商業軟體，也不是可以直接交付重要資料的生產工具。這個專案很大程度上是純 vibe coding：邊試、邊寫、邊重構，用 AI 協助把想法快速落到程式裡。文件會盡量寫清楚目前能做什麼、哪裡還不穩，以及使用時需要自己判斷的風險。

## 我想解決的問題

- 素材不要反覆分析。一次處理後，結果應盡量進入可重用的知識庫。
- 角色卡不要只靠一次大模型自由發揮。後續生成應優先讀取結構化結果和證據。
- 長任務不能像黑盒。提取、跳過、失敗和整理過程應該在介面裡有可讀的回饋。

## 目前狀態

- 仍處在 beta 階段，功能、資料結構和提取效果還會繼續調整。
- 最新發布包與每個版本的變更請看 [GitHub Releases](https://github.com/yomihime/CharaPicker/releases) 和 [更新日誌](../../CHANGELOG.md)。

## 現在能做什麼

- 建立專案、導入素材，並把原始素材保留在 `raw/`，處理後的入口放到 `materials/`。
- 掃描影片、圖片、音訊和文字四類素材，生成預覽或正式提取 run plan。
- 對 ZIP、CBZ、EPUB、文字型 PDF、7z、RAR、CBR 做受控預處理，再交給既有文字或圖片鏈路。
- 透過統一模型中介層呼叫 OpenAI-compatible 後端，並記錄 token usage。
- 在洞察流面板看到提取過程中的關鍵事件，而不是只看日誌。
- 在角色卡頁面管理專案內角色卡：建立、編輯、封面裁剪、預覽、編譯、匯入和匯出。
- 從正式知識庫編譯 CharaPicker JSON，並匯出 Markdown、HTML、Character Card V2 JSON 和 AstrBot 手動複製清單。

## 還不穩的地方

- 真實素材提取品質還在打磨，尤其是跨集、跨媒體和長文本上下文。
- 角色卡衝突消解、品質評估和證據取捨仍需要更多樣本驗證。
- `facts.json`、`targeted_insights.json` 等早期知識庫檔案還沒有形成穩定的自動寫入閉環。
- 大模型輸出有成本、失敗率和幻覺風險；重要結果需要人工複核。

## 環境需求

- Python `>=3.10`
- 主要依賴：
  - `PyQt6>=6.6`
  - `PyQt6-Fluent-Widgets>=1.5`
  - `pydantic>=2.6`
  - `pypdf>=6.14.2,<7`

## 支援的輸入

- 直接素材：常見影片、靜態圖片、音訊、TXT/Markdown/JSON、SRT/ASS 等格式。
- 受控預處理：`.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr`。
- PDF 首版只提取既有文字，不執行 OCR；加密 PDF、DRM EPUB 和密碼壓縮檔會被明確拒絕。
- 7z/RAR/CBR 需要本機 7-Zip。應用程式會檢查專案內 `bin/`、`PATH`、Windows 標準安裝目錄與 `CHARAPICKER_7ZIP_PATH`，不會自動下載 7-Zip。
- 巢狀容器不會遞迴展開；原容器保留在 `raw/`，派生素材與來源映射分別寫入 `materials/derived_inputs/` 和預處理 manifest。
- 通用 ZIP/7z/RAR 內的影片不會被展開；影片必須作為獨立素材明確導入。CBZ/CBR 繼續只接納漫畫圖片頁。

## 安裝

```powershell
python -m pip install -r requirements.txt
```

## 執行

```powershell
python main.py
```

## 建置

```powershell
build.bat
```

- 產物輸出到 `release/` 目錄。
- 常用參數範例：
  - `build.bat --tag=vX.Y.Z-beta`
  - `build.bat --version=X.Y.Z --stage=beta`
  - `build.bat --local`

## 主要功能

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
- [GitHub Releases](https://github.com/yomihime/CharaPicker/releases)
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
