# assets/lips — 唇プリセット画像(UI Lv2 用)

`ui_app.py` の塗布シミュ合成に使う唇画像。**Format A(暫定)** の置き場所。

## 期待ファイル(LIP_PRESETS に対応する 5 枚)

| ファイル名 | プリセット | km.LIP_PRESETS の Lab(下地色) |
|---|---|---|
| `lip_pale_pink.png`    | pale_pink    | 淡いピンク |
| `lip_healthy_pink.png` | healthy_pink | 健康的なピンク |
| `lip_reddish.png`      | reddish      | やや赤め |
| `lip_beige.png`        | beige        | ベージュ寄り |
| `lip_dark.png`         | dark         | 暗め |

## 形式
- PNG・**背景透過(αチャネル)**、唇のみ。サイズ 400x300 程度。
- 唇マスク = α(不透明=唇, 透明=背景)。α が無い PNG は「全面=唇」として扱う。

## ロード優先順位(ui_app.load_lip_image)
1. `lip_<preset>.png`(プリセット個別)があればそれ
2. **`model.png`**(全プリセット共用の実写モデル)← 現状これを使用
3. どちらも無ければ楕円ベースの**ダミー唇を動的生成**

## 現在の model.png
- Wikimedia Commons "My Red Lips" by Trina(**CC BY 3.0**)。α は唇の赤を色しきい値
  で自動抽出し羽化したもの。色は applied_lab で上書きするので実写の唇色は不問
  (写真は形/質感/陰影を担当)。帰属は `CREDITS.txt`、UI 上にもクレジット表示。
- 差し替えたい場合は同形式(RGBA, α=唇マスク)の PNG を model.png として置く。

## 将来(Format B: Kawano さんデータ)
データ形式が固まったら `ui_app.load_lip_image(preset_name) -> (rgb_uint8, mask)`
の内部実装だけ差し替える(インターフェースは固定)。
