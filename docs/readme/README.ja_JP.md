# CharaPicker (日本語)

[简体中文](../../README.md) | [繁體中文](README.zh_TW.md) | [English](README.en_US.md)

## プロジェクト概要

CharaPicker は、アニメ・漫画・動画・画像・テキスト素材からキャラクター情報を抽出し、構造化されたキャラクタープロファイルとインサイトを生成するデスクトップツールです。

## コア目標

- Extract Once: 素材をできるだけ一度だけ処理し、再利用可能なナレッジベースに蓄積する。
- Targeted Insight: 指定キャラクターや世界観に対する定向インサイトを出力する。
- Visible Thinking: デバッグログではなく、重要なインサイトの流れを UI で可視化する。

## 現在の状態

- バージョン：`v0.8.0-beta`（開発中）
- ドキュメント更新日：`2026-07-21`

## 実装済み内容

- 起動・ウォームアップ経路：スプラッシュ、テーマ適用、基本環境チェック。
- メイン UI 骨組み：プロジェクト、キャラクターカード、モデル、プロンプト、設定、About ページ。
- プロジェクト設定管理：保存/読込、最近のプロジェクト一覧。
- 素材処理経路：`raw/` への取り込み、`materials/` へのリンク/処理、FFmpeg 分割・トランスコード対応。
- 複数コンテンツ形態の抽出：動画、画像、音声、テキストが run plan、プレビュー／正式分配、ナレッジベース集約、出典追跡の基盤を共有。
- 入力前処理：ZIP、CBZ、EPUB、テキスト PDF、7z、RAR、CBR を既存のテキストまたは画像素材へ派生してから抽出経路へ渡す。
- インサイト UI：InsightStreamPanel のカード表示とストリーミング更新。
- クラウドモデル接続：共通ミドルウェアで OpenAI-compatible 呼び出しと token usage 記録。
- プレビュー経路接続：`project -> extractor -> insight stream -> preview knowledge base`。
- キャラクターカードページ：プロジェクト内カードギャラリー、検索、作成、編集、カバーのトリミング、プレビュー、コンパイル、インポート、エクスポートに対応。

## 進捗

- 完了：実行可能な UI、4 メディア種別の抽出基盤、キャラクターカードのライフサイクル、7 種類の複雑入力形式の制御付き前処理。
- 進行中：実素材からの高品質・再利用可能な構造化インサイト生成。
- 次フェーズ：実素材の抽出品質、ナレッジベース品質、キャラクターカードの競合解決と品質評価を継続的に改善する。

## 未完了項目

- 複数コンテンツ形態は共通のプレビュー／正式抽出基盤へ入りますが、実素材品質、コンテンツ間の関連付け、失敗フィードバックは引き続き検証が必要です。
- キャラクターカードコンパイルは正式ナレッジベースから CharaPicker JSON を生成でき、階層化された証拠、別名の再分類、品質診断、直接証拠のないキャラクターを生成しない保護に対応しています。
- `facts.json` / `targeted_insights.json` への安定した自動書き込みループは未完成。

## 要件

- Python `>=3.10`
- テキスト PDF の前処理には `pypdf>=6.14.2,<7` が必要

## 対応入力

- 直接素材：一般的な動画、静止画像、音声、TXT/Markdown/JSON、SRT/ASS など。
- 制御付き前処理：`.zip`、`.cbz`、`.epub`、`.pdf`、`.7z`、`.rar`、`.cbr`。
- PDF 初版は既存テキストのみを抽出し、OCR は実行しません。暗号化 PDF、DRM EPUB、パスワード付きアーカイブは明示的に拒否されます。
- 7z/RAR/CBR にはローカルの 7-Zip が必要です。アプリはプロジェクト内 `bin/`、`PATH`、Windows 標準インストール先、`CHARAPICKER_7ZIP_PATH` を確認し、7-Zip を自動ダウンロードしません。
- 入れ子のコンテナは再帰展開しません。元コンテナは `raw/` に保持し、派生素材と出典マッピングは `materials/derived_inputs/` と前処理 manifest に保存します。

## インストール

```powershell
python -m pip install -r requirements.txt
```

## 実行

```powershell
python main.py
```

## 機能概要

- プロジェクト単位の素材管理（`projects/{project_id}`）
- プロジェクト内キャラクターカード管理と CharaPicker JSON 母本
- 抽出段階のインサイトイベントストリーム（Insight Stream）
- キャラクターカード Markdown、HTML、Character Card V2 JSON、AstrBot 手動コピーリストのエクスポート（継続的に改善中）

## スクリーンショット

- スクリーンショット資料は後日追加予定。

## ドキュメント案内

- [简体中文 README](../../README.md)
- [繁體中文 README](README.zh_TW.md)
- [English README](README.en_US.md)
- [更新ログ](../../CHANGELOG.md)
- [docs アーキテクチャ](../ARCHITECTURE.md)
- [ルート アーキテクチャ](../../ARCHITECTURE.md)

## 開発メモ

- 本プロジェクトは `core` / `gui` / `utils` の責務分離を維持する。
- UI の表示文言は `i18n/` で管理し、長期的なハードコードを避ける。
- 実行時リソースは `res/` に統一する。

## ライセンス

- CharaPicker の自有ソースコードは [Mozilla Public License 2.0](../../LICENSE)（`MPL-2.0`）でライセンスされます。
- サードパーティ依存関係およびバイナリに含まれるコンポーネントは、それぞれのライセンスに従います。詳しくは [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) を参照してください。
- 現在のオープンソースビルドは GPL ライセンスの PyQt6 / PyQt6-Fluent-Widgets コンポーネントを使用します。バイナリ配布時には、これらのサードパーティライセンス上の義務にも従う必要があります。
