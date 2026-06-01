# CharaPicker (日本語)

[简体中文](../../README.md) | [繁體中文](README.zh_TW.md) | [English](README.en_US.md)

## プロジェクト概要

CharaPicker は、アニメ・漫画・動画・画像・テキスト素材からキャラクター情報を抽出し、構造化されたキャラクタープロファイルとインサイトを生成するデスクトップツールです。

## コア目標

- Extract Once: 素材をできるだけ一度だけ処理し、再利用可能なナレッジベースに蓄積する。
- Targeted Insight: 指定キャラクターや世界観に対する定向インサイトを出力する。
- Visible Thinking: デバッグログではなく、重要なインサイトの流れを UI で可視化する。

## 現在の状態

- バージョン：`v0.5.1-beta`（開発中）
- ドキュメント更新日：`2026-06-01`

## 実装済み内容

- 起動・ウォームアップ経路：スプラッシュ、テーマ適用、基本環境チェック。
- メイン UI 骨組み：プロジェクト、キャラクターカード、モデル、プロンプト、設定、About ページ。
- プロジェクト設定管理：保存/読込、最近のプロジェクト一覧。
- 素材処理経路：`raw/` への取り込み、`materials/` へのリンク/処理、FFmpeg 分割・トランスコード対応。
- インサイト UI：InsightStreamPanel のカード表示とストリーミング更新。
- クラウドモデル接続：共通ミドルウェアで OpenAI-compatible 呼び出しと token usage 記録。
- プレビュー経路接続：`project -> extractor -> insight stream -> preview knowledge base`。
- キャラクターカードページ：プロジェクト内カードギャラリー、検索、作成、編集、カバーのトリミング、プレビュー、コンパイル、インポート、エクスポートに対応。

## 進捗

- 完了：実行可能な UI 骨格とプレビュー主経路。
- 進行中：実素材からの高品質・再利用可能な構造化インサイト生成。
- 次フェーズ：ナレッジベース品質向上、コンパイル段階の状態反復、競合解決とキャラクターカード品質向上。

## 未完了項目

- 実素材プレビューは `materials/` 内の動画 chunk とクラウドモデルの利用を開始していますが、テキスト、字幕、漫画／画像などを含む完全な実素材消費経路はまだ整備中です。
- キャラクターカードコンパイルは正式ナレッジベースから CharaPicker JSON を生成できますが、完全な競合解決と品質評価は引き続き改善が必要です。
- `facts.json` / `targeted_insights.json` への安定した自動書き込みループは未完成。

## 要件

- Python `>=3.10`

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
