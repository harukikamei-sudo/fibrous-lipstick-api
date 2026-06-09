"""冒険度 β と「似合い度」の関係を可視化(レビュー/説明用)。

`test_explore_does_not_ignore_color` が守る性質
  ——「冒険度 β を上げても推薦の似合い度がゼロにならない(色を無視しない)」——
を、本番の recommend_v2 を実際に呼んでグラフ化する。

横軸: 冒険度 = user.theta_explore.mu を 0→1 スイープ(β = β_max·explore でβも 0→5)。
      ※相殺は β·familiarity 経由なので、explore_weight(rerank用)でなく theta_explore.mu を振る。
縦軸: おすすめ上位N件の平均 ΔE2000(eff_lab, θ_color.mu)。小さいほど似合う。
線:  (1) 本番(係数すべて既定 = 色 exploit −α·ΔE あり)
      (2) 参考(alpha=0 = 色 exploit を外す = 色を無視するポリシー)
         ※w3=0(familiarity の色項のみ除去)では α が支配的すぎて本番と区別がつかないため、
           「色を無視する」対比としては α=0(色 exploit そのものを外す)を用いる。
係数(α, β_max, w3)はハードコードせず RecommendV2Request の既定値から取得。

出力: docs/figures/explore_vs_fit.png + 各点の数値を標準出力。
既存コード/テストは変更しない(描画スクリプトを足すだけ)。
"""
from __future__ import annotations

import csv
import os
import statistics
from typing import List, Tuple

from models_v13 import (
    GaussianLab, GaussianScalar, GaussianVec20, KMTableRow,
    LabValue, RecommendV2Request, UserState,
)
from recommend_v2 import recommend_v2

TOP_N = 5
N_STEPS = 11           # explore 0.0, 0.1, ..., 1.0
LIP = (62.0, 22.0, 12.0)

# 偏り回避: 複数の μ_color(似合う色中心)で平均。PC 別中心 + 中庸を数パターン。
MU_COLORS: List[Tuple[float, float, float]] = [
    (55, 45, 30),   # イエベ春寄り
    (40, 40, 25),   # イエベ秋寄り
    (55, 35, 5),    # ブルベ夏寄り
    (40, 50, 15),   # ブルベ冬寄り
    (50, 30, 15),   # 中庸
]


def _load_km_table() -> List[KMTableRow]:
    """products_with_lab.csv から 145商品 × 21段 の applied_Lab テーブルを構築。

    eff_lab は唇→商品色の線形補間(本番 km と同形の近似。描画用途では十分)。
    x20 は CSV の実カラムをそのまま使う。
    """
    rows: List[KMTableRow] = []
    with open("products_with_lab.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "excluded":
                continue
            try:
                L, a, b = float(r["L"]), float(r["a"]), float(r["b"])
            except (KeyError, ValueError, TypeError):
                continue
            x20 = []
            ok = True
            for i in range(20):
                v = next((r[c] for c in r if c.startswith(f"x20_{i:02d}_")), None)
                if v is None:
                    ok = False
                    break
                x20.append(float(v or 0.0))
            if not ok:
                continue
            applied = []
            for i in range(21):
                w = i / 20.0
                applied.append(LabValue(
                    L=LIP[0] * (1 - w) + L * w,
                    a=LIP[1] * (1 - w) + a * w,
                    b=LIP[2] * (1 - w) + b * w,
                ))
            rows.append(KMTableRow(product_id=r["id"], applied=applied, x20=x20,
                                   name=r.get("color_name", ""),
                                   line_category=r.get("line_category", "tint")))
    return rows


def _make_user(mu_color, explore) -> UserState:
    return UserState(
        user_id="probe", lip_lab=LabValue(L=LIP[0], a=LIP[1], b=LIP[2]),
        pc_season="ブルベ夏",
        theta_color=GaussianLab(mu=LabValue(L=mu_color[0], a=mu_color[1], b=mu_color[2]),
                                var=LabValue(L=4.0, a=4.0, b=4.0)),  # 較正済 SD≈2
        theta_pref=GaussianVec20(mu=[1.0] + [0.0] * 19, var=[1.0] * 20),
        theta_explore=GaussianScalar(mu=explore, var=0.25),
        theta_thickness=GaussianScalar(mu=1.0, var=0.05),
    )


def _mean_top_de(km, mu_color, explore, alpha=None) -> Tuple[float, float]:
    """その explore でおすすめ上位 TOP_N の平均 ΔE と β を返す。

    alpha=None なら本番既定(色 exploit あり)。alpha=0.0 を渡すと
    色 exploit 項(−α·ΔE)を外した「色を無視するポリシー」になる(参考線用)。
    """
    user = _make_user(mu_color, explore)
    kw = {} if alpha is None else {"alpha": 0.0}
    req = RecommendV2Request(user=user, km_table=km, top_n=TOP_N, **kw)
    res = recommend_v2(req)
    des = [it.delta_e_to_color for it in res.results]
    return statistics.mean(des), res.beta_used


def main() -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    # 役員向け: 日本語フォント(Hiragino 等)を設定。無ければ英語にフォールバック。
    jp = False
    _names = {f.name for f in fm.fontManager.ttflist}
    for _cand in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic",
                  "Arial Unicode MS", "AppleGothic"):
        if _cand in _names:
            matplotlib.rcParams["font.family"] = _cand
            matplotlib.rcParams["axes.unicode_minus"] = False  # マイナス記号の豆腐回避
            jp = True
            break

    km = _load_km_table()
    # 本番既定の係数を req から取得(ハードコードしない)
    _def = RecommendV2Request(user=_make_user(MU_COLORS[0], 0.0), km_table=km[:1])
    alpha, beta_max, w_def = _def.alpha, _def.beta_max, _def.familiarity_weights
    # 「似合う色」しきい値も p(like)=0.5 境界(de50)から取得(ハードコードしない)
    try:
        from active_learning import DE50_DEFAULT as FIT_THRESHOLD
    except Exception:
        FIT_THRESHOLD = 12.0

    explores = [i / (N_STEPS - 1) for i in range(N_STEPS)]
    prod_curve, noColor_curve, betas = [], [], []

    print(f"coeffs (production defaults): alpha={alpha}, beta_max={beta_max}, "
          f"familiarity_weights={w_def} / reference line uses alpha=0 (color exploit removed)")
    print(f"TOP_N={TOP_N}, averaged over {len(MU_COLORS)} mu_color patterns, "
          f"{len(km)} candidate products")
    print(f"{'explore':>8} {'beta':>6} {'meanDE(prod)':>14} {'meanDE(noColor)':>16}")
    for e in explores:
        p_vals, nc_vals, b_vals = [], [], []
        for mc in MU_COLORS:
            p, b = _mean_top_de(km, mc, e, alpha=None)     # 本番(色 exploit あり)
            nc, _ = _mean_top_de(km, mc, e, alpha=0.0)      # 参考(色 exploit を外す)
            p_vals.append(p)
            nc_vals.append(nc)
            b_vals.append(b)
        pm, ncm, bm = (statistics.mean(p_vals), statistics.mean(nc_vals),
                       statistics.mean(b_vals))
        prod_curve.append(pm)
        noColor_curve.append(ncm)
        betas.append(bm)
        print(f"{e:8.2f} {bm:6.2f} {pm:14.2f} {ncm:16.2f}")

    # 床(本番カーブの最悪値=最大 ΔE)= 最冒険でも似合い度はここまでしか崩れない。
    floor_val = max(prod_curve)

    # 体験型ラベル(役員向け・日本語。フォント無しなら英語)
    C_PROD, C_IGNORE, C_THRESH = "#e75480", "#9a9a9a", "#1f6fb0"
    if jp:
        lab_prod = "本番ロジック(冒険度を上げても色は尊重)"
        lab_ignore = "参考:色を無視した場合"
        lab_thresh = "似合うライン(これ以下なら似合う)"
        title = "冒険度を上げても、似合う色から外れない"
        xlabel = "冒険度(高いほど冒険的な提案)"
        ylabel = "← 下ほど 似合う色をおすすめできている"
        ann_prod = "最大に冒険しても\n似合うラインの下"
        ann_ignore = "色を無視すると\n冒険するほど似合わなくなる"
        caption = ("※ 本番 recommend_v2 を実際に呼んで計算(5つの好みパターン平均)。"
                   "冒険度 = β ÷ β_max。")
    else:
        lab_prod = "production (color respected)"
        lab_ignore = "reference: color ignored"
        lab_thresh = "fitting line (suitable below this)"
        title = "Raising adventurousness does NOT abandon suitable colors"
        xlabel = "adventurousness (higher = bolder suggestions)"
        ylabel = "lower = better at recommending suitable colors"
        ann_prod = "even at max,\nstays below the line"
        ann_ignore = "ignoring color gets\nworse as you explore"
        caption = ("Production recommend_v2 actually invoked (avg over 5 preference "
                   "patterns). adventurousness = beta / beta_max.")

    ytop = max(noColor_curve) * 1.12
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(explores, prod_curve, color=C_PROD, lw=3.0, marker="o", ms=5, label=lab_prod)
    ax.plot(explores, noColor_curve, color=C_IGNORE, lw=2.0, ls=":", marker="s", ms=5,
            label=lab_ignore)
    # しきい線: p(like)=0.5 となる ΔE=de50。これ以下なら「似合う色」。本番はずっと下側。
    ax.axhline(FIT_THRESHOLD, color=C_THRESH, ls="-.", lw=1.4, label=lab_thresh)
    ax.fill_between(explores, prod_curve, noColor_curve, color=C_IGNORE, alpha=0.10)
    # 本番ラインの優位を注記(最大冒険でもしきい値の下に留まる)
    ax.annotate(ann_prod, xy=(explores[-1], prod_curve[-1]),
                xytext=(explores[-1] - 0.03, FIT_THRESHOLD * 0.5), ha="right",
                fontsize=9, color="#b03b6b",
                arrowprops=dict(arrowstyle="->", color="#b03b6b", lw=1.2))
    ax.text(0.5, max(noColor_curve) * 0.9, ann_ignore, ha="center", fontsize=9,
            color="#777")

    ax.set_title(title, fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(0, ytop)
    ax.set_xticks([0.0, 0.25, 0.5, 0.75, 1.0])
    ax.tick_params(axis="y", left=False, labelleft=False)  # 役員向け:縦軸の数値は隠す
    ax.grid(alpha=0.25, axis="x")
    ax.legend(fontsize=10, loc="upper left", framealpha=0.95)
    fig.text(0.5, 0.01, caption, ha="center", fontsize=9, color="#666")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "docs", "figures", "explore_vs_fit.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"\nproduction: explore0={prod_curve[0]:.2f} -> explore1={prod_curve[-1]:.2f} "
          f"(rise {prod_curve[-1]-prod_curve[0]:.2f}, floor dE<= {floor_val:.1f})")
    print(f"reference(alpha=0): explore0={noColor_curve[0]:.2f} -> "
          f"explore1={noColor_curve[-1]:.2f} (color ignored = far worse fit)")
    gap = noColor_curve[-1] - prod_curve[-1]
    print(f"gap at max explore: {gap:.1f} dE (=value of the color-exploit guard)")
    under = all(v <= FIT_THRESHOLD for v in prod_curve)
    print(f"fitting threshold (de50) = {FIT_THRESHOLD:.0f} dE; "
          f"production stays under it for all beta: {under} "
          f"(max prod dE = {floor_val:.1f})")
    print(f"✅ saved: {out}")


if __name__ == "__main__":
    main()
