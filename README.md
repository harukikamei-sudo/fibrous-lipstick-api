---
title: Fibrous Lipstick API
emoji: 💄
colorFrom: pink
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Fibrous Lipstick API

口紅推奨ロジック MVP の Python 処理を集約した FastAPI サーバー。
商品画像 URL を投げると K-means + 形状特徴ベースで口紅スウォッチ色を抽出し、
CIE Lab 値を返す。

- **公開エンドポイント**: <https://tamable-fibrous-lipstick-api.hf.space>
- **Swagger UI**: <https://tamable-fibrous-lipstick-api.hf.space/docs>
- **ソースコード**: <https://github.com/harukikamei-sudo/fibrous-lipstick-api>

## エンドポイント

| Method | Path | 用途 | 状態 |
|---|---|---|---|
| GET  | `/health`             | ヘルスチェック        | ✅ |
| GET  | `/`                   | サービス情報          | ✅ |
| POST | `/extract_lab`        | 画像URL1件 → Lab     | ✅ |
| POST | `/extract_lab_batch`  | 画像URL最大50件 → Lab| ✅ |
| POST | `/estimate_s`         | ライン S 逆推定       | ⏳ 未実装(501) |
| POST | `/compute_km_table`   | K-M バッチ計算       | ⏳ 未実装(501) |

## クイックスタート

### curl

```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/extract_lab \
  -H "Content-Type: application/json" \
  -d '{"image_url":"https://cloudflare.lipscosme.com/image/1146e2669f8f25c9f3298df7-1687245280.png"}'
```

レスポンス:
```json
{
  "status": "auto_high",
  "lab": {"L": 37.04, "a": 36.18, "b": 21.13},
  "notes": "sat=0.62, hue=3°, size=0.43, edge=0.01, spread=0.165, adj=0.06, aspect=2.06, container=False"
}
```

### JavaScript / Apps Script

```js
const res = UrlFetchApp.fetch(
  "https://tamable-fibrous-lipstick-api.hf.space/extract_lab",
  {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({image_url: imageUrl}),
    muteHttpExceptions: true,
  }
);
const data = JSON.parse(res.getContentText());
// data.status, data.lab.L, data.lab.a, data.lab.b
```

スプレッドシート連携の完全サンプルは [`sample_gas.gs`](./sample_gas.gs)。

### バッチ (最大50件)

```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/extract_lab_batch \
  -H "Content-Type: application/json" \
  -d '{"products":[
    {"id":"a","image_url":"https://example.com/lipstick_a.png"},
    {"id":"b","image_url":"https://example.com/lipstick_b.png"}
  ]}'
```

## レスポンス仕様

### `status` (3段階)

| 値 | 意味 |
|---|---|
| `auto_high` | 高信頼。`edge<0.05` かつ `size>0.30` かつ (`adj>0.10` または 容器形状でない) |
| `auto_low`  | 抽出はできたが目視レビュー推奨 |
| `excluded`  | 抽出失敗(赤系の支配色なし / 画像取得失敗 / 容器のみ画像) |

### `lab`

CIE Lab (D65)。`status="excluded"` のとき `null`。

### `notes`

抽出メタの内訳: `sat`(彩度) / `hue`(色相°) / `size`(クラスタ占有率) / `edge`(エッジ密度) /
`spread`(空間分散) / `adj`(背景隣接率) / `aspect`(縦横比) / `container`(容器形状判定)。

## 制限・注意

- **画像サイズ**: 1 枚 **10MB** まで(超えると `413`)
- **バッチ件数**: **50 件** まで(超えると `422`)
- **SSRF 対策**: `http(s)` 以外、loopback / private / link-local IP は `400`
- **CPU basic** で動作。ピーク時はレイテンシ揺れあり
- **無認証**: 公開 API。トークン不要だが、悪用時は Space を private 化する可能性あり

## モジュール構成

| ファイル | 役割 |
|---|---|
| `app.py` | FastAPI アプリ |
| `extract_lab.py` | 画像 → Lab 抽出ロジック(CLI と API で共通)、`classify_status` |
| `lab_utils.py` | 色空間変換(RGB ↔ Lab、Lab ↔ 反射率、HSV) |
| `estimate_s.py` | ライン S 逆推定(雛形) |
| `km.py` | K-M モデル計算(雛形) |
| `test_lab_utils.py` | Lab ↔ 反射率往復テスト(ΔE < 1) |
| `test_dark_swatch.py` | ダーク系維持テスト |

## ローカル実行

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

`http://localhost:8000/docs` で Swagger UI。

## CLI バッチ(API を経由せず手元で実行)

```bash
python extract_lab.py
```

カレントの `products.csv` (`id`, `image_url` 列を含む)を読み、
`products_with_lab.csv` / `excluded_list.csv` / `thumbnails/{id}.png` を出力。

## デプロイ更新

```bash
git push origin main   # GitHub
git push hf main       # HF Spaces(自動再ビルド)
```

詳細は [`DEPLOY.md`](./DEPLOY.md)。

## OpenAPI / TypeScript 型生成(A5)

API スキーマからフロント(color-capture)の型を自動生成し、手書き型と
`models_v13.py` の乖離を防ぐ。

```bash
# API 側: openapi.json を再生成(uvicorn 起動不要、app.openapi() を直ダンプ)
python scripts/export_openapi.py            # → リポジトリ直下 openapi.json
```

- `openapi.json` は**生成物**。エンドポイント/モデルを変えたら再生成すること
  (`sort_keys` 付きで安定出力=差分ノイズ最小)。
- フロント側(color-capture)は `openapi.json` から `openapi-typescript` で
  `src/lib/apiTypes.gen.ts` を生成する(手順は color-capture の README 参照)。
  当面は既存の手書き `apiTypes.ts` を残し、生成型との差分を確認してから置換。

## License

MIT
