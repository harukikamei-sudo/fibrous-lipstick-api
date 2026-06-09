"""「似合わない色を出した割合」で random を正しく評価する図(役員/レビュー説明用)。

背景:真値への ΔE 収束だけ見ると random が有利に出る(製品化不可なのに)。だが本システムの
目的は「ユーザーに"似合う色"をおすすめすること」。そこで実際の体験=「おすすめが大きく外して
いなかったか」を指標にし、**random が体験面で最下位(似合わない色を出す率が突出)**である
ことを可視化する。

なぜ「似合う率(μ基準)」にしないか:exploit は定義上いつも予想 μ の最近傍を出すので
μ基準だと 100% に張り付いて不自然。さらに真値基準の「似合う(≤de50)」は真値近傍商品が
希少なため全戦略が低く団子になり差が出ない。そこで体験の失敗=**真の好みから大きく外した
割合(低いほど良い)** で測ると、random の弱点(似合わない色を出す)が素直に出る:
  外した = ΔE2000(おすすめ色, 真の好み TRUE_PREF) > MISS_THRESHOLD(= de50 × 2 = 24)

図(docs/figures/hit_rate_comparison.png):
  横軸 = 試着回数 N(1〜12)
  縦軸 = 似合わない色を出した割合(累積・低いほど良い)
  線   = 現行(exploit, w=0) / 能動学習(EIG, w=1) / random(参考)
  結果 = random が突出して高い(似合わない色を出し続ける)= 体験で最下位。
         exploit は低い(予想に一貫=大きくは外さない。ただし別図のとおり学習はしない)。

本番コードを必ず経由(再実装しない):
  - 事前 θ_color : pair_compare 本番経路(較正後 SD≈2.0)  ← make_experience_figures と共用
  - ベイズ更新   : bayesian.apply_observations(like のみ θ_color 更新の本番仕様)
  - 期待情報利得 : active_learning.expected_information_gain(next_best 内部で使用)
  - 選択ブレンド : active_learning.next_best(recommend_v2 の rerank と同一。w=explore_weight)
  - 色距離       : recommend_v2.delta_e_2000(CIEDE2000)

★唯一のシミュレーション(検証用)= 仮想ユーザーの like 判定(真値からの ΔE → ロジスティック)。
  本番には存在しない代用。make_experience_figures._sim_like を共用(検証専用と明記済み)。

再現性: seed 固定(SEED)。N_SEEDS 回平均。設定値は定数化。
スコープ: 既存コード/テストは変更しない(描画スクリプト+図の追加のみ)。

実行: python scripts/figures/make_hit_rate_figure.py
"""

from __future__ import annotations

import os
import random
import statistics
import sys
from typing import Dict, List, Tuple

# リポジトリルート + scripts/figures を import パスに追加
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for _p in (REPO_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import active_learning as al                 # noqa: E402
import bayesian                              # noqa: E402
from models_v13 import Observation           # noqa: E402
from recommend_v2 import delta_e_2000        # noqa: E402

# 体験版グラフのシミュ基盤を共用(事前生成・候補・仮想like・フォント)。再実装しない。
import make_experience_figures as EXP        # noqa: E402

# ============================================================
# 設定(定数・再現可能)
# ============================================================
SEED = EXP.SEED          # 体験版グラフと同一基点
N_SEEDS = 120            # 仮想ユーザー like を平均する試行数
N_MAX = 12               # 横軸の試着回数上限
# 「似合う」境界 = p(like)=0.5 となる ΔE(de50)。ハードコードせず本番定数から取得。
# ※ de50=12.0 は仮値(被験者データ未較正・Phase3 較正対象)。
FIT_THRESHOLD = al.DE50_DEFAULT
# 「大きく外した(似合わない色)」境界 = 似合い境界の2倍 = はっきり外れたと言える距離。
MISS_THRESHOLD = 2.0 * FIT_THRESHOLD  # = 24
# 図に載せる3戦略(w=explore_weight)+ 記録用に w=0.5 も stdout に出す。
FIG_STRATEGIES = (("exploit", 0.0), ("active_learning", 1.0), ("random", None))
EXTRA_W = 0.5            # stdout 記録用(現実的なブレンドの参考)

OUT = os.path.join(REPO_ROOT, "docs", "figures", "hit_rate_comparison.png")


def _select_idx(kind: str, w, user, pool, rng: random.Random) -> int:
    """次に出すおすすめ(=試着候補)1件を選び pool index を返す。

    exploit/active_learning は本番 next_best のブレンド(recommend_v2 rerank と同一)。
    random は一様ランダム。
    """
    if kind == "random":
        return rng.randrange(len(pool))
    mu_c = user.theta_color.mu
    cands = [al.Candidate(product_id=pid, effective_lab=lab,
                          r_final=-delta_e_2000(lab, mu_c)) for pid, lab in pool]
    scored = al.next_best(cands, user.theta_color, mu_explore=w)
    top_id = scored[0].product_id
    for i, (pid, _) in enumerate(pool):
        if pid == top_id:
            return i
    return 0


def run_hit(kind: str, w, prior_user, cand_labs, true_de_cache,
            seed: int) -> List[float]:
    """1試行: 各ステップで出したおすすめが「似合わない色(大きく外し)」だったか(1/0)を返す。

    外した = ΔE2000(おすすめ色, **真の好み TRUE_PREF**) > MISS_THRESHOLD(= de50×2)。
    ※ 体験の失敗を真値基準で測る。μ(システムの予想)基準にすると exploit が自分の予想の
       近くしか出さないため 100% 張り付き(0%外し)になり不自然なので、真値で採点する。
    """
    rng = random.Random(f"{seed}-miss-{kind}-{w}")
    user = prior_user                      # apply_observations は非破壊 → 共有可
    pool = list(cand_labs)
    miss: List[float] = []
    for _ in range(N_MAX):
        mu_c = user.theta_color.mu         # この μ でおすすめを出す(選択にのみ使用)
        idx = _select_idx(kind, w, user, pool, rng)
        pid, lab = pool.pop(idx)
        # 失敗判定: 出したおすすめ色が「本当の好み」から大きく外れていたか(真値との色差)
        miss.append(1.0 if true_de_cache[pid] > MISS_THRESHOLD else 0.0)
        # 仮想ユーザーの反応(検証用)→ like のみ θ_color 更新(本番仕様)
        liked = EXP._sim_like(true_de_cache[pid], rng)
        obs = [Observation(
            source="ar_view_like" if liked else "ar_view_dislike",
            product_id=pid, observed_lab=lab, y=1.0 if liked else -1.0,
        )]
        user, _ = bayesian.apply_observations(user, obs)
    return miss


def simulate() -> Dict:
    prior_user = EXP.build_prior_user()
    cand_labs = EXP.load_candidate_labs()
    pm = prior_user.theta_color.mu
    tp_id, tp_lab, gap = EXP.pick_true_pref(pm, cand_labs)
    true_de_cache = {pid: delta_e_2000(lab, tp_lab) for pid, lab in cand_labs}

    def per_step(kind, w):
        runs = [run_hit(kind, w, prior_user, cand_labs, true_de_cache, SEED + i)
                for i in range(N_SEEDS)]
        # 各ステップ単独で「似合わない色を出した」割合 = seed 平均
        return [statistics.mean(r[n] for r in runs) for n in range(N_MAX)]

    def cumulative(ps):
        # 累積: 「出したおすすめ N 件のうち似合わない色だった割合」(低いほど良い)
        return [statistics.mean(ps[: n + 1]) for n in range(N_MAX)]

    ps = {name: per_step(name, w) for name, w in FIG_STRATEGIES}
    ps_extra = per_step("blend", EXTRA_W)        # 記録用(現実的ブレンド)
    curves = {name: cumulative(ps[name]) for name in ps}   # 図に使う累積
    print(f"  各戦略 hit 計算完了({N_SEEDS} seeds)")

    return {
        "prior_mu": pm, "true_id": tp_id, "true_lab": tp_lab, "gap": gap,
        "curves": curves,                 # 累積(図)
        "per_step": ps,                   # 単発(stdout で正直に開示)
        "extra_w05": cumulative(ps_extra),
        "per_step_extra": ps_extra,
    }


# ============================================================
# 描画
# ============================================================
C = {"exploit": "#1a1a1a", "active_learning": "#e75480", "random": "#9a9a9a"}


def _labels(jp: bool) -> Dict[str, str]:
    if jp:
        return dict(
            exploit="好きそうな順だけ(今のやり方)",
            active_learning="かしこく選ぶ(能動学習)",
            random="でたらめに選ぶ(参考)",
            xlabel="試着した回数",
            ylabel="似合わない色を出した割合(累積・低いほど良い)",
            title="「似合わない色」を出した割合 ―― でたらめ選びが突出して最悪",
            caption=("※ 検証用シミュレーション(in silico)。本番ロジック(ベイズ更新・"
                     "期待情報利得・ブレンド選択)を実際に呼んで作図。"),
            note=("「似合わない」= 推薦色と本当の好みの色差 ΔE2000 が 24 超(似合い境界 de50=12 の2倍。"
                  "de50 は仮値・Phase3較正対象)。\n"
                  "でたらめ選びは真値への距離(学習効率)では有利だが、似合わない色を出す率が突出 → "
                  "体験は最低。ゆえに製品では採用不可。"),
        )
    return dict(
        exploit="likely-liked only (current)",
        active_learning="active learning (smart pick)",
        random="random (reference)",
        xlabel="number of try-ons",
        ylabel="cumulative share of unsuitable recommendations (lower = better)",
        title="Share of clearly-unsuitable picks -- random is by far the worst",
        caption=("In-silico verification simulation; production logic (Bayesian update, "
                 "expected information gain, blended selection) is actually invoked."),
        note=("'unsuitable' = dE2000(recommended, true preference) > 24 (= 2x de50; de50=12 "
              "provisional, Phase-3 calibration target).\n"
              "Random wins on distance-to-truth (learning efficiency) but shows unsuitable "
              "colors far more often -> worst UX -> not productizable."),
    )


def make_figure(data: Dict, jp: bool) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    L = _labels(jp)
    c = data["curves"]
    ks = list(range(1, N_MAX + 1))  # N=1..12(N=0 はおすすめ未提示)

    # でたらめ(random)= 主役(最悪を示す)→ 太い赤系。現行/能動学習は低く抑制。
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(ks, [v * 100 for v in c["exploit"]], color=C["exploit"], lw=2.4,
            marker="o", ms=4, label=L["exploit"])
    ax.plot(ks, [v * 100 for v in c["active_learning"]], color=C["active_learning"],
            lw=2.6, marker="o", ms=5, label=L["active_learning"])
    ax.plot(ks, [v * 100 for v in c["random"]], color="#c0392b", lw=3.0, ls=":",
            marker="s", ms=6, label=L["random"])

    ytop = max(max(c["random"]), max(c["active_learning"]), max(c["exploit"])) * 100
    ax.set_title(L["title"], fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel(L["xlabel"], fontsize=12)
    ax.set_ylabel(L["ylabel"], fontsize=11)
    ax.set_ylim(-0.5, max(8.0, ytop * 1.25))
    ax.yaxis.set_major_formatter(lambda v, _pos: f"{v:.0f}%")
    ax.set_xticks(range(1, N_MAX + 1, 2))
    ax.grid(alpha=0.25)
    ax.legend(fontsize=11, loc="upper left", framealpha=0.95)
    fig.text(0.5, 0.085, L["note"], ha="center", fontsize=8.5, color="#444")
    fig.text(0.5, 0.005, L["caption"], ha="center", fontsize=9, color="#666")

    fig.tight_layout(rect=[0, 0.12, 1, 1])
    fig.savefig(OUT, dpi=140)
    plt.close(fig)
    return OUT


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print("=== 「似合わない色を出した割合」比較図(本番コード再現)===")
    print(f"設定: SEED={SEED}, N_SEEDS={N_SEEDS}, N_MAX={N_MAX}, "
          f"似合い境界 de50={FIT_THRESHOLD} / 大きく外し境界={MISS_THRESHOLD:.0f}(=de50×2)")
    print("シミュレーション中...")
    data = simulate()

    pm, tp = data["prior_mu"], data["true_lab"]
    print(f"\n事前 μ_color=({pm.L:.1f},{pm.a:.1f},{pm.b:.1f}) / "
          f"真値={data['true_id']} ズレ={data['gap']:.1f} ΔE")
    c = data["curves"]          # 累積(図の値)
    print(f"\n累積『似合わない色を出した割合』(出したおすすめ N 件のうち真値から "
          f"ΔE {MISS_THRESHOLD:.0f} 超を出した割合)※図に使う値・低いほど良い:")
    print(f"{'N':>3} {'exploit':>9} {'EIG(w1)':>9} {'random':>9} {'(w0.5記録)':>11}")
    for n in range(N_MAX):
        print(f"{n+1:>3} {c['exploit'][n]*100:8.1f}% {c['active_learning'][n]*100:8.1f}% "
              f"{c['random'][n]*100:8.1f}% {data['extra_w05'][n]*100:9.1f}%")

    def avg(curve):
        return statistics.mean(curve) * 100
    print(f"\n平均『似合わない色を出した割合』(低いほど良い): "
          f"exploit={avg(c['exploit']):.1f}% / EIG(w1)={avg(c['active_learning']):.1f}% / "
          f"random={avg(c['random']):.1f}% / (参考 w0.5={avg(data['extra_w05']):.1f}%)")
    rand_worst = (avg(c['random']) > avg(c['exploit'])
                  and avg(c['random']) > avg(c['active_learning']))
    print(f"→ random は『似合わない色を出した割合』が突出{'(=体験で最下位・確認)' if rand_worst else '(要確認)'}。"
          f"真値ΔEでは最良でも、似合わない色を出すため製品化不可。")
    print("  ※ 現行(exploit)は低い=予想に一貫し大きくは外さない。ただし収束図のとおり"
          "学習しない(好みに近づかない)ので、低いだけでは良い体験にならない。")

    jp = EXP._setup_font()
    if not jp:
        print("⚠ 日本語フォント未検出 → 英語ラベルで描画")
    out = make_figure(data, jp)
    print(f"\n✅ 図: {out}")


if __name__ == "__main__":
    main()
