"""「学ぶ × 似合う」2軸トレードオフ図(役員/レビュー説明用)。

収束図(学習)と似合わない率図(体験)は、それぞれ単独だと
  - 学習だけ見る  → random が最良に見える(でも似合わない色を出す)
  - 体験だけ見る  → 現行 exploit が最良に見える(でも好みに近づけない=学ばない)
と誤解を生む。本図は両軸を1枚に重ね、**能動学習(EIG)だけが両立**することを示す。

  横軸 = 学習:好みにどれだけ近づけたか(=初期ズレ − 最終ズレ ΔE2000、右ほど良い)
  縦軸 = 体験:似合う色を出せた割合(= 100% − 似合わない色を出した率、上ほど良い)
         似合わない = ΔE2000(おすすめ, 真の好み) > de50×2
  点   = 現行(exploit) / 能動学習(EIG) / random
  理想 = 右上(よく学び、かつ似合う)。EIG が最も右上に近い。

本番コードを必ず経由(make_experience_figures と共用):
  pair_compare(事前)/ bayesian.apply_observations(更新)/ active_learning(EIG・選択)/
  recommend_v2.delta_e_2000(距離)。仮想 like 判定のみ検証用(真値→ロジスティック)。

再現性: seed 固定・N_SEEDS 平均。スコープ: 既存コード/テストは未変更(描画+図の追加のみ)。
実行: python scripts/figures/make_tradeoff_figure.py
"""

from __future__ import annotations

import os
import random
import statistics
import sys
from typing import Dict, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for _p in (REPO_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import active_learning as al                 # noqa: E402
import bayesian                              # noqa: E402
from models_v13 import Observation           # noqa: E402
from recommend_v2 import delta_e_2000        # noqa: E402
import make_experience_figures as EXP        # noqa: E402

SEED = EXP.SEED
N_SEEDS = 120
N_MAX = 15
MISS_THRESHOLD = 2.0 * al.DE50_DEFAULT       # 似合わない=真値から ΔE>24(de50×2)
# 図の3戦略(w=explore_weight)。exploit=0 / EIG=1。
STRATEGIES = (("exploit", 0.0), ("active_learning", 1.0), ("random", None))
OUT = os.path.join(REPO_ROOT, "docs", "figures", "tradeoff_learn_vs_fit.png")


def run(kind: str, w, prior_user, cands, cache, tp_lab, seed: int) -> Tuple[float, float]:
    """1試行 → (最終ズレ ΔE(μ,真値), 似合わない色を出した率)。"""
    rng = random.Random(f"{seed}-trade-{kind}-{w}")
    user = prior_user
    pool = list(cands)
    miss = 0
    for _ in range(N_MAX):
        mu_c = user.theta_color.mu
        if kind == "random":
            idx = rng.randrange(len(pool))
        else:
            cc = [al.Candidate(product_id=pid, effective_lab=lab,
                               r_final=-delta_e_2000(lab, mu_c)) for pid, lab in pool]
            tid = al.next_best(cc, user.theta_color, mu_explore=w)[0].product_id
            idx = next(i for i, (pid, _) in enumerate(pool) if pid == tid)
        pid, lab = pool.pop(idx)
        if cache[pid] > MISS_THRESHOLD:
            miss += 1
        liked = EXP._sim_like(cache[pid], rng)
        obs = [Observation(source="ar_view_like" if liked else "ar_view_dislike",
                           product_id=pid, observed_lab=lab, y=1.0 if liked else -1.0)]
        user, _ = bayesian.apply_observations(user, obs)
    final_de = delta_e_2000(user.theta_color.mu, tp_lab)
    return final_de, miss / N_MAX


def simulate() -> Dict:
    prior_user = EXP.build_prior_user()
    cands = EXP.load_candidate_labs()
    pm = prior_user.theta_color.mu
    tp_id, tp_lab, gap = EXP.pick_true_pref(pm, cands)
    cache = {pid: delta_e_2000(lab, tp_lab) for pid, lab in cands}
    init_de = delta_e_2000(pm, tp_lab)        # 全戦略共通の初期ズレ(=gap)

    out: Dict[str, Dict[str, float]] = {}
    for name, w in STRATEGIES:
        runs = [run(name, w, prior_user, cands, cache, tp_lab, SEED + i)
                for i in range(N_SEEDS)]
        final_de = statistics.mean(r[0] for r in runs)
        miss = statistics.mean(r[1] for r in runs)
        out[name] = dict(
            final_de=final_de,
            improvement=init_de - final_de,        # 好みにどれだけ近づけたか(学習)
            suit=100.0 * (1.0 - miss),             # 似合う色を出せた割合(体験)
        )
        print(f"  [{name}] 最終ズレ={final_de:.2f} 学習={init_de-final_de:.2f} "
              f"似合い={100*(1-miss):.1f}%")
    return {"prior_mu": pm, "true_id": tp_id, "gap": init_de, "stats": out}


def make_figure(data: Dict, jp: bool) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = data["stats"]
    C = {"exploit": "#1a1a1a", "active_learning": "#e75480", "random": "#c0392b"}
    if jp:
        names = {"exploit": "現行(好きそうな順だけ)",
                 "active_learning": "能動学習(かしこく選ぶ)",
                 "random": "でたらめ(参考)"}
        note = {"exploit": "安全だが学ばない\n(好みに近づけない)",
                "active_learning": "両立 ―\n学びながら似合う色",
                "random": "学ぶが似合わない\n色だらけ(製品化不可)"}
        title = "能動学習だけが「学ぶ × 似合う」を両立"
        xlabel = "学習:好みにどれだけ近づけたか →(右ほど良い)"
        ylabel = "↑ 体験:似合う色を出せた割合(上ほど良い)"
        ideal = "理想\n(よく学び・似合う)"
        caption = ("※ 検証用シミュレーション(in silico)。本番ロジックを実際に呼んで作図。"
                   "片方の軸だけ見ると現行 or randomが最良に見えるが、両立するのは能動学習だけ。")
    else:
        names = {"exploit": "current (likely-liked only)",
                 "active_learning": "active learning",
                 "random": "random (reference)"}
        note = {"exploit": "safe but doesn't learn",
                "active_learning": "both: learns &\nstays suitable",
                "random": "learns but unsuitable\n(not productizable)"}
        title = "Only active learning balances learning AND suitability"
        xlabel = "learning: how much closer to preference -> (right is better)"
        ylabel = "experience: share of suitable picks (up is better)"
        ideal = "ideal\n(learns & suits)"
        caption = ("In-silico simulation; production logic invoked. Each single axis flatters "
                   "either current or random; only active learning is good on both.")

    xs = {k: s[k]["improvement"] for k in s}
    ys = {k: s[k]["suit"] for k in s}
    xmin, xmax = min(xs.values()), max(xs.values())
    ymin, ymax = min(ys.values()), max(ys.values())
    xpad = (xmax - xmin) * 0.35 + 0.5
    ypad = (ymax - ymin) * 0.45 + 1.0
    xlo, xhi = xmin - xpad, xmax + xpad
    ylo, yhi = ymin - ypad, ymax + ypad

    fig, ax = plt.subplots(figsize=(10, 7))
    # 右上=理想ゾーン(よく学び・似合う)を薄く塗る
    xmid, ymid = (xlo + xhi) / 2, (ylo + yhi) / 2
    ax.fill_between([xmid, xhi], ymid, yhi, color="#7ec98f", alpha=0.12, zorder=0)
    ax.text(xhi, yhi, ideal, ha="right", va="top", fontsize=10, color="#2e7d4f",
            fontweight="bold")

    # ラベルは点の外側にオフセット(白背景+色文字+引き出し線)。位置は data 座標。
    lpos = {
        "exploit":         (xs["exploit"] + 0.05, ys["exploit"] - 5.5, "center", "top"),
        "active_learning": (xs["active_learning"] - 0.15, ys["active_learning"] - 5.0,
                            "center", "top"),
        "random":          (xs["random"], ys["random"] + 4.5, "center", "bottom"),
    }
    for k in ("exploit", "random", "active_learning"):  # EIG 最後=前面
        big = k == "active_learning"
        ax.scatter([xs[k]], [ys[k]], s=360 if big else 230, color=C[k],
                   edgecolor="white", linewidth=2, zorder=5, alpha=0.95)
        lx, ly, ha, va = lpos[k]
        ax.annotate(f"{names[k]}\n{note[k]}", xy=(xs[k], ys[k]), xytext=(lx, ly),
                    ha=ha, va=va, fontsize=9.5 if big else 9, color=C[k],
                    fontweight="bold", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=C[k], lw=1.2),
                    arrowprops=dict(arrowstyle="-", color=C[k], lw=1.0))

    ax.set_title(title, fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    ax.grid(alpha=0.25)
    fig.text(0.5, 0.01, caption, ha="center", fontsize=8.5, color="#666")

    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(OUT, dpi=140)
    plt.close(fig)
    return OUT


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print("=== 「学ぶ × 似合う」2軸トレードオフ図(本番コード再現)===")
    print(f"設定: SEED={SEED}, N_SEEDS={N_SEEDS}, N_MAX={N_MAX}, "
          f"似合わない境界={MISS_THRESHOLD:.0f}")
    print("シミュレーション中...")
    data = simulate()
    s = data["stats"]
    print(f"\n初期ズレ(全戦略共通)= {data['gap']:.1f} ΔE / 真値={data['true_id']}")
    print(f"\n{'戦略':>16}{'学習(近づけた)':>14}{'似合う率':>10}")
    for k in ("exploit", "active_learning", "random"):
        print(f"{k:>16}{s[k]['improvement']:>12.2f}  {s[k]['suit']:>8.1f}%")
    print("\n→ 現行=似合うが学ばない / random=学ぶが似合わない / 能動学習=両立(右上に最も近い)")

    jp = EXP._setup_font()
    if not jp:
        print("⚠ 日本語フォント未検出 → 英語ラベルで描画")
    out = make_figure(data, jp)
    print(f"\n✅ 図: {out}")


if __name__ == "__main__":
    main()
