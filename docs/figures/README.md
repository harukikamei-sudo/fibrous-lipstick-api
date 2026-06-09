# docs/figures — 体験版グラフ(役員/レビュー説明用)

本番ロジック(`bayesian` / `pair_compare` / `active_learning` / `recommend_v2`)を
**実際に呼んで** 描いた、能動学習の効果を説明する図。再現可能。

## 生成方法

```bash
python scripts/figures/make_experience_figures.py   # 図1・図2(収束/追い越し)
python scripts/figures/make_hit_rate_figure.py      # 図3(似合い率=体験の比較)
python plot_explore_vs_fit.py                        # 図4(冒険度βと色exploitの関係)
```

- 乱数 seed は固定(`SEED` 定数)。仮想ユーザーの like 判定を `N_SEEDS` 回平均して曲線を均す。
- 設定値(seed・試着回数・PC・仮説ズレ・de50/slope)はスクリプト冒頭で定数化。
- 既存コード/テストは変更しない(描画スクリプトと図の追加のみ)。

## 図

| ファイル | 内容 |
|---|---|
| `al_convergence_experience.png` | 試着回数 N に対する「好みへの近さ」。**現行(好きそうな順=exploit)** vs **能動学習(EIG)**。試着を重ねるほど能動学習が現行を引き離す。 |
| `al_eig_advantage.png` | 同じ2本を試着回数の現実的範囲(N≤12)で。能動学習が現行を **安定的に追い越す N** を明示(序盤は探索コストで一時的に遠回りする点も正直に注記)。 |
| `hit_rate_comparison.png` | **似合い率(体験)の比較**。出したおすすめのうち「似合う色」だった割合。現行(exploit)・能動学習(EIG)・random の3本。**random が体験面で最下位**(似合わない色を出し続ける)であることを示し、「ランダムでいいのでは」に決着をつける。 |
| `explore_vs_fit.png` | **冒険度βと色exploitの関係**(色を無視しないことの可視化)。横軸=explore(0→max, β=β_max·explore)、縦軸=おすすめ上位の平均 ΔE2000(本番 vs 色exploitを外したα=0参考)。最大βでも本番ラインは ΔE≈3.5 で床打ちし、似合いしきい値(de50=12)の下に留まる=「冒険度を上げても色を無視しない」。`test_explore_does_not_ignore_color` が守る性質の可視化(生成元 `plot_explore_vs_fit.py` はリポジトリルート)。 |

図1・図2の縦軸 = おすすめの中心(事後 μ_color)から真の好み TRUE_PREF までの ΔE2000。下ほど好みに近い。
役員向けに縦軸の数値ラベルは伏せ、相対関係だけを見せる。

### 図3(似合い率)の指標

- ヒット率 = 「出したおすすめ N 件のうち、似合う色だった割合(累積)」(seed 平均)。
- 「似合う」= ΔE2000(おすすめ色, その時点の θ_color.mu)が **de50=12 以下**
  (仮値・Phase3 較正対象。`active_learning.DE50_DEFAULT` から取得、ハードコードしない)。
- 選択は `active_learning.next_best` のブレンド(w=explore_weight)。exploit=w0 / EIG=w1。
- 実測(seed 平均): exploit 100% / EIG(w1) 平均 81%(100%→69%)/ random 平均 43%(終始最下位)。
  ※ 単発(per-step)では EIG が探索局面で一時 random を下回るが、第一定義の累積では終始上回る
  (標準出力に per-step も開示)。
- **示すこと**: random は真値への距離(学習効率)では有利でも、似合わない色を出すため
  似合い率=ユーザー体験では最低 → 製品では採用不可。前2図の「random はなぜダメか」を体験で裏づける。

## 使っている本番ロジック(再実装していない)

- 事前 θ_color 生成 … `pair_compare.apply_pair_choices`(較正後 σ²_obs を使う本番経路、SD≈2.0)
- ベイズ更新 … `bayesian.apply_observations`(like のみ θ_color を動かす本番仕様)
- 期待情報利得 … `active_learning.expected_information_gain` / `next_best`
- 色距離 … `recommend_v2.delta_e_2000`(CIEDE2000)
- 選択ブレンド … `active_learning.next_best`(`recommend_v2` の rerank と同一の選択則)

唯一のシミュレーション(検証用)は **仮想ユーザーの like 判定**(真値からの ΔE → ロジスティック)。
実ユーザーが AR で行う反応の代用で、本番には存在しない(スクリプト内 `_sim_like` に明記)。

## ⚠ 当初スライドからの主張変更(本番 ΔE2000 再現の結果)

当初の簡易版(numpy・ユークリッド ΔE)スライドは「**能動学習が最速 = 試着7回以内なら
ランダムにも勝つ**」と主張していた。本番 ΔE2000 で忠実に再現すると **これは成立しない**:

- EIG は **KL(信念の移動量)を最大化する acquisition** であって「真値への距離最小化」とは別目的。
  さらに dislike は θ_color を更新しない仕様のため、純粋な真値収束では
  **一様ランダム+like フィルタ(=真値領域への棄却サンプリング)に劣りうる**
  (能動学習で既知の現象。`SIMULATOR_GUIDE.md` §割り切り3 にも明記)。
- 実測でも random が N=1〜12 で終始リード(=数値上は最良)。ただし random は
  似合わない色も大量に提示するため **製品化不可**、かつ上記理由で公平な比較線にならない。

→ よって図は **「現行(exploit) vs 能動学習(EIG)」の2本に絞り**、主張を
**「能動学習は現行方式より、試着を重ねるほど好みに近づく」** のみに限定した。
random はスクリプトの標準出力には記録として残すが、図には載せない。
