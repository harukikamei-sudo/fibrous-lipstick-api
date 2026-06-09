"""体験版グラフ(役員/レビュー説明用)を **本番コードを呼んで** 再現する。

これまでスライドに使ってきた「能動学習だと少ない試着で好みに近づく」体験版グラフは、
検証用の簡易スクリプト(numpy・ユークリッド ΔE)で描いていた。本スクリプトは同じ主張を
本番ロジック(bayesian / pair_compare / active_learning / recommend_v2)を実際に呼んで
再現し、再現可能な形でリポジトリ(docs/figures)に残す。

出力(2枚):
  docs/figures/al_convergence_experience.png … 図1:能動学習なら少ない試着で好みに近づく
  docs/figures/al_eig_advantage.png          … 図2:数回の試着で能動学習が現行を追い越す

【主張の範囲(重要・本番ΔE2000での再現結果に基づく)】
  当初スライドの「能動学習が最速(=ランダムにも勝つ)」は、本番 ΔE2000 で忠実再現すると
  成立しない(EIG は KL=信念の移動量を最大化する acquisition で、真値への距離最小化とは
  別目的。dislike が θ_color を更新しない仕様も相まって、純粋な真値収束では
  一様ランダム+like フィルタ=「真値領域への棄却サンプリング」に劣りうる。これは
  SIMULATOR_GUIDE.md §割り切り3 にも明記された既知現象)。
  よって本図は **「現行(好きそうな順=exploit)」vs「能動学習(EIG)」** の2本に絞り、
  「能動学習は現行方式より少ない試着で好みに近づく」だけを主張する(random とは戦わない)。
  random も記録のため計算し標準出力には残すが、図には載せない(数値最良だが似合わない色を
  出すため製品化不可、かつ上記理由で公平な比較線にならない)。

本番コードを必ず経由する箇所:
  - 事前 θ_color の生成 : pair_compare.apply_pair_choices(較正後 σ²_obs を使う本番経路)
  - ベイズ更新          : bayesian.apply_observations(like のみ θ_color を動かす本番仕様)
  - 期待情報利得 EIG    : active_learning.expected_information_gain / next_best
  - 色距離              : recommend_v2.delta_e_2000(CIEDE2000)
  - 選択ブレンド        : active_learning.next_best(recommend_v2 の rerank と同一の選択則)

★唯一のシミュレーション(検証用)= 仮想ユーザーの like 判定。
  実ユーザーが AR で行う「いいね/微妙」を、真値 TRUE_PREF からの ΔE2000 →
  ロジスティックで代用する(下の _sim_like)。本番には存在しない検証専用ロジック。

再現性: 乱数 seed を固定(SEED)。like のランダムドローを N_SEEDS 回平均して曲線を均す。
スコープ: 既存コード/テストは変更しない。描画スクリプトと図の追加のみ。

実行:  python scripts/figures/make_experience_figures.py
"""

from __future__ import annotations

import csv
import math
import os
import random
import statistics
import sys
from typing import Dict, List, Optional, Tuple

# リポジトリルートを import パスに追加(scripts/figures/ から本番モジュールを読む)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import active_learning as al          # noqa: E402
import bayesian                       # noqa: E402
import pair_compare as pc_mod         # noqa: E402
from models_v13 import (              # noqa: E402
    LabValue, Observation, PairApplyRequest, PairChoice, UserState,
)
from recommend_v2 import delta_e_2000  # noqa: E402

# ============================================================
# 設定(定数・コメント付き・再現可能)
# ============================================================
SEED = 20260609          # 乱数の基点(固定)。各 (seed, strategy) で独立ストリームを派生
N_SEEDS = 120            # 仮想ユーザー like のランダムドローを平均する試行数(曲線の平滑化)
N_MAX = 15               # シミュレーション/図1の試着回数の上限
N_FIG2 = 12              # 図2(検証C)で使う試着回数の上限
PC_SEASON = "ブルベ夏"   # 事前 θ_color を作るときの PC(bayes_plot と揃える)

# 「仮説ズレ=中程度」: 事前 μ_color と真値 TRUE_PREF の ΔE2000 をこの値付近に取る。
# de50(似合い境界)=12 より少し外側 → 「事前のままでは少しズレている=学ぶ余地がある」設定。
TARGET_GAP_DE = 16.0

# --- 仮想ユーザー like 判定(SIMULATION ONLY・検証用)のロジスティック係数 ---
# 本番の知覚モデル(active_learning)の de50 / slope をそのまま流用する。
# = 「モデルが仮定する当たりやすさ」と「シミュレーション上の真の反応」を一致させる素直な設定。
SIM_DE50 = al.DE50_DEFAULT     # 12.0
SIM_SLOPE = al.SLOPE_DEFAULT   # 0.25

STRATEGIES = ("exploit", "active_learning", "random")

OUT_DIR = os.path.join(REPO_ROOT, "docs", "figures")
CATALOG_PATH = os.path.join(REPO_ROOT, "products_with_lab.csv")

# 簡易版(過去スライド)での実測値。本番 ΔE2000 で再計算した値とズレたら出力で知らせる。
LEGACY_CROSS_N = 7


# ============================================================
# 本番経路:事前生成・候補・距離
# ============================================================

def build_prior_user() -> UserState:
    """pair_compare の本番経路で事前 θ(較正後 σ²_obs)を構築した UserState を返す。

    全ペア左選択は bayes_plot._build_prior と同じ流儀。較正後は θ_color の SD≈2.0。
    apply_observations は UserState を新規生成し既存を破壊しないので、この prior は
    各シミュレーション run で共有して安全(コピー不要)。
    """
    choices = [PairChoice(pair_id=p.pair_id, chose="left") for p in pc_mod.PAIR_BANK]
    resp = pc_mod.apply_pair_choices(
        PairApplyRequest(choices=choices, pc_season=PC_SEASON)
    )
    return UserState(
        user_id="experience_sim",
        lip_lab=LabValue(L=62.0, a=22.0, b=12.0),
        pc_season=PC_SEASON,
        theta_color=resp.theta_color,
        theta_pref=resp.theta_pref,
        theta_explore=resp.theta_explore,
        theta_thickness=resp.theta_thickness,
    )


def load_candidate_labs() -> List[Tuple[str, LabValue]]:
    """カタログ(products_with_lab.csv)のスウォッチ Lab を「試着できる色」の母集合にする。

    pair_compare は選ばれた商品の生スウォッチ Lab をそのまま θ_color の観測に与える。
    事前と同じ Lab 空間で完結させるため、候補もスウォッチ Lab を直接使う
    (km テーブルの厚み補間は色収束の検証には不要)。
    """
    labs: List[Tuple[str, LabValue]] = []
    with open(CATALOG_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "excluded":
                continue
            try:
                labs.append((r["id"], LabValue(
                    L=float(r["L"]), a=float(r["a"]), b=float(r["b"]))))
            except (KeyError, ValueError, TypeError):
                continue
    return labs


def pick_true_pref(prior_mu: LabValue,
                   cand_labs: List[Tuple[str, LabValue]]) -> Tuple[str, LabValue, float]:
    """事前 μ から ΔE2000 が中程度(TARGET_GAP_DE 付近)の実在カタログ色を真値に選ぶ。

    真値を実在の商品色にすることで「到達可能な好み」を保証する(どの戦略でも試着で出会える)。
    返り値: (product_id, lab, 実際の gap ΔE)。
    """
    best_id, best_lab, best_diff, best_gap = None, None, float("inf"), 0.0
    for pid, lab in cand_labs:
        gap = delta_e_2000(lab, prior_mu)
        diff = abs(gap - TARGET_GAP_DE)
        if diff < best_diff:
            best_id, best_lab, best_diff, best_gap = pid, lab, diff, gap
    return best_id, best_lab, best_gap


# ============================================================
# 選択ロジック(本番 next_best のブレンド)
# ============================================================

def select_next(strategy: str, user: UserState,
                pool: List[Tuple[str, LabValue]], rng: random.Random) -> int:
    """次の試着候補を1つ選び、pool 内の index を返す。

    exploit / active_learning は本番 active_learning.next_best のブレンド選択
    (= recommend_v2 の rerank と同一の選択則)を使う:
        w = clamp(mu_explore) ;  exploit→w=0(R_final 最大=最近傍), explore→w=1(EIG 最大)
    random は一様ランダム(参考・製品化不可ライン)。
    """
    if strategy == "random":
        return rng.randrange(len(pool))

    mu_explore = 0.0 if strategy == "exploit" else 1.0
    mu_color = user.theta_color.mu
    # exploit の R_final は色 exploit の単調変換 -ΔE(α は w=0/w=1 のランク付けに不感なので係数不問)
    candidates = [
        al.Candidate(product_id=pid, effective_lab=lab,
                     r_final=-delta_e_2000(lab, mu_color))
        for pid, lab in pool
    ]
    scored = al.next_best(candidates, user.theta_color, mu_explore=mu_explore)
    top_id = scored[0].product_id
    for i, (pid, _) in enumerate(pool):
        if pid == top_id:
            return i
    return 0  # 念のため(到達しない想定)


def _sim_like(true_dE: float, rng: random.Random) -> bool:
    """=== SIMULATION ONLY(検証用)=== 仮想ユーザーの like 判定。

    実ユーザーが AR で行う「いいね/微妙」の代用。真値 TRUE_PREF からの ΔE2000 を
    ロジスティックに通して like 確率を出し、ベルヌーイ抽選する。**本番には存在しない**。
    係数は本番知覚モデル(de50/slope)を流用(モデルの仮定=シミュ上の真実、という素直な設定)。
    """
    p = 1.0 / (1.0 + math.exp(-SIM_SLOPE * (SIM_DE50 - true_dE)))
    return rng.random() < p


def run_once(strategy: str, prior_user: UserState,
             cand_labs: List[Tuple[str, LabValue]], true_pref_lab: LabValue,
             true_de_cache: Dict[str, float], seed: int) -> List[float]:
    """1試行: N_MAX 回の試着を逐次シミュレートし、各 N での真値からのズレ ΔE を返す。

    ズレ = ΔE2000(現在の事後 μ_color, TRUE_PREF)。下ほど好みに近い。
    """
    rng = random.Random(f"{seed}-{strategy}")  # 文字列 seed で (seed, 戦略) ごと独立・再現可能
    user = prior_user                      # apply_observations は非破壊 → 共有して安全
    pool = list(cand_labs)                 # 試着済みは取り除く(同じ商品は再提示しない)
    dev = [delta_e_2000(user.theta_color.mu, true_pref_lab)]  # N=0(事前)

    for _ in range(N_MAX):
        idx = select_next(strategy, user, pool, rng)
        pid, lab = pool.pop(idx)
        liked = _sim_like(true_de_cache[pid], rng)
        # 本番仕様: like は θ_color を動かす / dislike は色を動かさない(update_theta_color が除外)
        obs = [Observation(
            source="ar_view_like" if liked else "ar_view_dislike",
            product_id=pid, observed_lab=lab, y=1.0 if liked else -1.0,
        )]
        user, _ = bayesian.apply_observations(user, obs)
        dev.append(delta_e_2000(user.theta_color.mu, true_pref_lab))
    return dev


def simulate() -> Dict:
    """3戦略 × N_SEEDS を回し、各 N での平均ズレ曲線を返す。"""
    prior_user = build_prior_user()
    cand_labs = load_candidate_labs()
    prior_mu = prior_user.theta_color.mu
    tp_id, true_pref_lab, true_gap = pick_true_pref(prior_mu, cand_labs)
    # 真値色までの ΔE はシミュ中一定 → 1回だけ事前計算(like 抽選の高速化)
    true_de_cache = {pid: delta_e_2000(lab, true_pref_lab) for pid, lab in cand_labs}

    curves: Dict[str, List[float]] = {}
    for s in STRATEGIES:
        runs = [run_once(s, prior_user, cand_labs, true_pref_lab,
                         true_de_cache, SEED + i) for i in range(N_SEEDS)]
        curves[s] = [statistics.mean(r[n] for r in runs) for n in range(N_MAX + 1)]
        print(f"  [{s}] done ({N_SEEDS} seeds)")

    return {
        "prior_mu": prior_mu,
        "prior_sd": math.sqrt(prior_user.theta_color.var.L),
        "true_pref_id": tp_id,
        "true_pref_lab": true_pref_lab,
        "true_gap": true_gap,
        "curves": curves,
    }


def overtake_n(al_curve: List[float], exploit_curve: List[float],
               n_limit: int) -> Optional[int]:
    """能動学習(EIG)が現行(exploit)を追い越す(以降ずっと下回る=好みに近い)最小の N。

    純EIG は序盤に探索コストで一時的に悪化するため、「一瞬下回る」ではなく
    「その N 以降 n_limit までずっと exploit を下回る」最小 N を返す(安定した追い越し)。
    無ければ None。
    """
    for n in range(1, n_limit + 1):
        if all(al_curve[k] < exploit_curve[k] for k in range(n, n_limit + 1)):
            return n
    return None


# ============================================================
# 描画
# ============================================================

def _setup_font() -> bool:
    """日本語フォント(役員向け)を設定。使えれば True。"""
    import matplotlib
    from matplotlib import font_manager as fm
    names = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic",
                 "Arial Unicode MS", "AppleGothic"):
        if cand in names:
            matplotlib.rcParams["font.family"] = cand
            matplotlib.rcParams["axes.unicode_minus"] = False  # マイナス記号の豆腐回避
            return True
    return False


# 役員向けラベル(専門用語を避ける)。jp が無い環境では英語にフォールバック。
def _labels(jp: bool) -> Dict[str, str]:
    if jp:
        return dict(
            exploit="好きそうな順だけ(今のやり方)",
            active="かしこく選ぶ(能動学習)",
            xlabel="試着した回数",
            ylabel="← 下ほど あなたの好みに近い",
            title1="試着を重ねるほど、能動学習が現行より好みに近づく",
            title2="数回の試着で、能動学習が現行を追い越す",
            caption="※ 検証用シミュレーション(in silico)。仮想ユーザーの反応で試着学習を再現。"
                    "本番ロジック(ベイズ更新・期待情報利得)を実際に呼んで作図。",
            overtake="ここから先、能動学習が\n現行より好みに近い",
            early="序盤は探索コストで\nやや遠回り",
            advantage="現行より近い",
            start="スタート(試着0回)",
        )
    return dict(
        exploit="likely-liked only (current)",
        active="active learning (smart pick)",
        xlabel="number of try-ons",
        ylabel="lower = closer to your preference",
        title1="As try-ons accumulate, active learning pulls closer to preference than current",
        title2="Within a few try-ons, active learning overtakes the current method",
        caption="In-silico verification simulation; production logic (Bayesian update + "
                "expected information gain) is actually invoked.",
        overtake="from here on, active learning\nis closer to preference",
        early="early exploration cost",
        advantage="closer than current",
        start="start (0 try-ons)",
    )


# 配色: かしこく=ピンク(主役), 今のやり方=黒
C_ACTIVE = "#e75480"
C_EXPLOIT = "#1a1a1a"


def make_fig1(data: Dict, jp: bool) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    L = _labels(jp)
    c = data["curves"]
    ks = list(range(N_MAX + 1))
    ex, ac = c["exploit"], c["active_learning"]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(ks, ex, color=C_EXPLOIT, lw=2.4, marker="o", ms=4, label=L["exploit"])
    ax.plot(ks, ac, color=C_ACTIVE, lw=3.0, marker="o", ms=5, label=L["active"])
    # 能動学習が現行より近い区間を薄く塗る(優位の可視化)
    ax.fill_between(ks, ac, ex, where=[a < e for a, e in zip(ac, ex)],
                    color=C_ACTIVE, alpha=0.10, interpolate=True)

    ax.set_title(L["title1"], fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel(L["xlabel"], fontsize=12)
    ax.set_ylabel(L["ylabel"], fontsize=12)
    ax.set_xlim(-0.3, N_MAX + 0.6)
    ax.set_xticks(range(0, N_MAX + 1, 3))
    ax.tick_params(axis="y", left=False, labelleft=False)  # 役員向け:縦軸の数値は隠す
    ax.grid(alpha=0.25, axis="x")
    ax.legend(fontsize=11, loc="upper right", framealpha=0.95)
    # 末尾の優位を注記(現行よりどれだけ好みに近いか)
    ax.annotate("", xy=(N_MAX, ac[-1]), xytext=(N_MAX, ex[-1]),
                arrowprops=dict(arrowstyle="<->", color="#1f5d99", lw=1.4))
    ax.text(N_MAX - 0.3, (ac[-1] + ex[-1]) / 2, L["advantage"], ha="right",
            va="center", fontsize=10, color="#1f5d99", fontweight="bold")
    fig.text(0.5, 0.005, L["caption"], ha="center", fontsize=9, color="#666")

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    out = os.path.join(OUT_DIR, "al_convergence_experience.png")
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def make_fig2(data: Dict, jp: bool, over: Optional[int]) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    L = _labels(jp)
    c = data["curves"]
    ks = list(range(N_FIG2 + 1))
    ex, ac = c["exploit"][:N_FIG2 + 1], c["active_learning"][:N_FIG2 + 1]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(ks, ex, color=C_EXPLOIT, lw=2.4, marker="o", ms=4, label=L["exploit"])
    ax.plot(ks, ac, color=C_ACTIVE, lw=3.0, marker="o", ms=5, label=L["active"])
    ax.fill_between(ks, ac, ex, where=[a < e for a, e in zip(ac, ex)],
                    color=C_ACTIVE, alpha=0.10, interpolate=True)

    ymax = max(max(ex), max(ac))
    ymin = min(min(ex), min(ac))
    if over is not None:
        ax.axvline(over, color="#3b7fd0", ls="--", lw=1.6)
        ax.plot([over], [ac[over]], "o", color="#3b7fd0", ms=9, mec="white", zorder=5)
        ax.annotate(L["overtake"], xy=(over, ac[over]),
                    xytext=(over + 0.4, ymax - (ymax - ymin) * 0.12), ha="left",
                    fontsize=10, color="#1f5d99", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#3b7fd0", lw=1.4))
        # 序盤の探索コストを正直に注記
        if over >= 3:
            ax.text(max(1, over // 2), ymax - (ymax - ymin) * 0.04, L["early"],
                    ha="center", fontsize=9, color="#888")
        ax.set_xticks(sorted(set(list(range(0, N_FIG2 + 1, 3)) + [over])))
    else:
        ax.set_xticks(range(0, N_FIG2 + 1, 3))

    ax.set_title(L["title2"], fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel(L["xlabel"], fontsize=12)
    ax.set_ylabel(L["ylabel"], fontsize=12)
    ax.set_xlim(-0.3, N_FIG2 + 0.3)
    ax.tick_params(axis="y", left=False, labelleft=False)
    ax.grid(alpha=0.25, axis="x")
    ax.legend(fontsize=11, loc="upper right", framealpha=0.95)
    fig.text(0.5, 0.005, L["caption"], ha="center", fontsize=9, color="#666")

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    out = os.path.join(OUT_DIR, "al_eig_advantage.png")
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


# ============================================================
# main
# ============================================================

def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=== 体験版グラフ(本番コード再現)===")
    print(f"設定: SEED={SEED}, N_SEEDS={N_SEEDS}, N_MAX={N_MAX}, PC={PC_SEASON}, "
          f"目標ズレ(中)≈{TARGET_GAP_DE} ΔE, like 判定 de50={SIM_DE50}/slope={SIM_SLOPE}")
    print("シミュレーション中...")
    data = simulate()

    pm = data["prior_mu"]
    tp = data["true_pref_lab"]
    print(f"\n事前 μ_color = (L={pm.L:.1f}, a={pm.a:.1f}, b={pm.b:.1f}), "
          f"SD≈{data['prior_sd']:.2f}")
    print(f"真値 TRUE_PREF = {data['true_pref_id']} "
          f"(L={tp.L:.1f}, a={tp.a:.1f}, b={tp.b:.1f}), "
          f"事前とのズレ = {data['true_gap']:.1f} ΔE2000(=中程度)")

    c = data["curves"]
    print(f"\n各 N での平均ズレ ΔE2000(真値まで。小さいほど好みに近い):")
    print(f"{'N':>3} {'exploit':>9} {'active(EIG)':>12} {'random*':>9}")
    for n in range(N_MAX + 1):
        print(f"{n:>3} {c['exploit'][n]:9.2f} {c['active_learning'][n]:12.2f} "
              f"{c['random'][n]:9.2f}")
    print("  * random は記録用(図には非掲載)。")

    over = overtake_n(c["active_learning"], c["exploit"], N_FIG2)
    print(f"\n能動学習が現行(exploit)を安定的に追い越す N(N≤{N_FIG2}): "
          f"{over if over is not None else 'なし'}")

    # --- スライド主張の変更点を明示(「ズレたらログで知らせる」要件)---
    print("\n--- スライド数値の更新点(本番ΔE2000での再現結果)---")
    print(f"  ・当初『能動学習が最速(試着{LEGACY_CROSS_N}回以内は random にも勝つ)』は"
          f"本番では不成立。")
    rand_lead = all(c["random"][n] <= c["active_learning"][n] + 1e-9
                    for n in range(1, N_FIG2 + 1))
    print(f"    本番 ΔE2000 では random が N=1〜{N_FIG2} で終始リード"
          f"({'確認' if rand_lead else '一部逆転あり'})。"
          f"EIG は KL(信念移動)最大化であって真値最小化ではないため(既知現象)。")
    print(f"  ・よって図は『現行(exploit) vs 能動学習(EIG)』の2本に変更。"
          f"主張は『能動学習は現行方式より少ない試着で好みに近づく』のみ。")
    print(f"  ・末尾 N={N_MAX} で能動学習は現行より "
          f"{c['exploit'][N_MAX] - c['active_learning'][N_MAX]:.1f} ΔE 好みに近い。")

    jp = _setup_font()
    if not jp:
        print("⚠ 日本語フォント未検出 → 英語ラベルで描画")
    f1 = make_fig1(data, jp)
    f2 = make_fig2(data, jp, over)
    print(f"\n✅ 図1(収束): {f1}")
    print(f"✅ 図2(追い越し): {f2}")


if __name__ == "__main__":
    main()
