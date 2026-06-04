"""ベイズ更新の統計的可視化(personas_cli の `plot` コマンドの実体)。

app(FastAPI / scipy 重依存)を経由せず、bayesian / pair_compare を直接呼んで
各ペルソナに N 観測を逐次適用し、matplotlib で 2×3 パネルのレポート PNG を出力する。

可視化対象は AR like 観測で実際に動く θ_thickness と θ_color のみ
(θ_pref / θ_explore は AR like では更新されないため対象外)。

数理(設計書 v1.3 §7):
  - θ_thickness (§7.5): σ²_N = 1/(1/σ²_0 + N/σ²_obs),  σ²_obs = 0.05
      → σ² はデータ非依存(N だけで決まる)= パネル B で 3 本が重なることを示す
  - θ_color    (§7.2): σ²_N,j = 1/(1/σ²_0,j + Σ y²/σ²_obs),  AR は y=1, σ²_obs = 1.0
  - 情報利得    : KL[posterior || design_prior] を bit で(パネル F)
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

import bayesian
from models_v13 import (
    GaussianLab,
    GaussianScalar,
    LabValue,
    Observation,
    PairApplyRequest,
    PairChoice,
)
import pair_compare as pc_mod

# χ²(2自由度, 0.95) = 5.9915 → 95% 信用楕円の半径係数
CHI2_2DOF_95 = 5.991464547
LN2 = math.log(2.0)

PC_SEASON = "ブルベ夏"


# ============ ペルソナ仕様(personas_cli から渡す軽量 dict) ============
# {"key","label","color","target","lip_lab":(L,a,b),"product_labs":[(L,a,b),...]}

def _eff_lab(lip: Tuple[float, float, float],
             prod: Tuple[float, float, float], t: float) -> Tuple[float, float, float]:
    """K-M 近似 effective_Lab(step_once と同じ線形補間)。"""
    return tuple(lip[i] * (1 - t) + prod[i] * t for i in range(3))


def _build_observations(spec: Dict, n: int) -> List[Observation]:
    """ペルソナの好み商品から N 件の AR like 観測を生成。"""
    labs = spec["product_labs"]
    lip = spec["lip_lab"]
    t = spec["target"]
    obs: List[Observation] = []
    for k in range(n):
        L, a, b = labs[k % len(labs)]
        e = _eff_lab(lip, (L, a, b), t)
        obs.append(Observation(
            source="ar_view_like",
            product_id=f"{spec['key']}_{k}",
            observed_lab=LabValue(L=e[0], a=e[1], b=e[2]),
            thickness=t,
            y=1.0,
        ))
    return obs


def _build_prior() -> Tuple[GaussianScalar, GaussianLab]:
    """全ペルソナ共通の事前分布を pair_compare(PC + 全 left)で構築。

    返り値: (theta_thickness 事前, theta_color 事前)
    pair 観測は θ_color を縮めるが θ_thickness は触らない(= 0.5, 0.1 のまま)。
    """
    choices = [PairChoice(pair_id=p.pair_id, chose="left") for p in pc_mod.PAIR_BANK]
    resp = pc_mod.apply_pair_choices(
        PairApplyRequest(choices=choices, pc_season=PC_SEASON)
    )
    return resp.theta_thickness, resp.theta_color


def _kl_1d(m1: float, v1: float, m0: float, v0: float) -> float:
    """KL( N(m1,v1) || N(m0,v0) ) [nats]。"""
    return 0.5 * math.log(v0 / v1) + (v1 + (m1 - m0) ** 2) / (2.0 * v0) - 0.5


# ============ 逐次適用 + 統計収集 ============

def _run_persona(spec: Dict, n: int,
                 prior_t: GaussianScalar, prior_c: GaussianLab) -> Dict:
    """N 観測を逐次適用し、各ステップの事後を記録。"""
    obs = _build_observations(spec, n)

    mu_t = [prior_t.mu]
    var_t = [prior_t.var]
    mu_c = [(prior_c.mu.L, prior_c.mu.a, prior_c.mu.b)]
    var_c = [(prior_c.var.L, prior_c.var.a, prior_c.var.b)]

    for k in range(1, n + 1):
        post_t, _ = bayesian.update_theta_thickness(prior_t, obs[:k])
        post_c, _ = bayesian.update_theta_color(prior_c, obs[:k])
        mu_t.append(post_t.mu)
        var_t.append(post_t.var)
        mu_c.append((post_c.mu.L, post_c.mu.a, post_c.mu.b))
        var_c.append((post_c.var.L, post_c.var.a, post_c.var.b))

    return {
        "spec": spec, "n": n,
        "mu_t": mu_t, "var_t": var_t, "mu_c": mu_c, "var_c": var_c,
    }


def _analytic_var_t(prior_var: float, n: int) -> List[float]:
    return [1.0 / (1.0 / prior_var + k / bayesian.SIGMA2_OBS_THICKNESS)
            for k in range(n + 1)]


def _analytic_var_color_L(prior_var: float, n: int) -> List[float]:
    sig_ar = bayesian.SIGMA2_BY_SOURCE["ar_view_like"]
    return [1.0 / (1.0 / prior_var + k * 1.0 / sig_ar) for k in range(n + 1)]


# ============ メイン ============

def generate_report(specs: List[Dict], n: int = 15,
                    out_path: str = "bayes_report.png") -> Tuple[str, List[str]]:
    """各ペルソナに N 観測を適用 → bayes_report.png 出力 + テキストレポート返却。"""
    import matplotlib
    matplotlib.use("Agg")
    try:  # 日本語フォントがあれば使う(無くても英語ラベルで動く)
        import japanize_matplotlib  # noqa: F401
    except Exception:
        pass
    import matplotlib.pyplot as plt
    from matplotlib.patches import Ellipse

    prior_t, prior_c = _build_prior()
    runs = [_run_persona(s, n, prior_t, prior_c) for s in specs]

    # 解析解(全ペルソナ共通:同一事前 → 分散は同一)
    an_var_t = _analytic_var_t(prior_t.var, n)
    an_var_cL = _analytic_var_color_L(prior_c.var.L, n)

    # デザイン事前(ゼロ知識):色 = §3.2 PC中心 + σ²=100、厚み = §7.5 事前 (0.5, 0.1)
    pc_center = pc_mod.PC_MU_COLOR_0[PC_SEASON]
    design_c = ((pc_center.L, pc_center.a, pc_center.b),
                (pc_mod.SIGMA2_BASE,) * 3)
    design_t = (pc_mod.MU_THICKNESS_0, pc_mod.SIGMA2_THICKNESS_0)

    ks = list(range(n + 1))
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    fig.suptitle("Bayesian update — statistical view (AR-like observations, design doc v1.3 §7)",
                 fontsize=14, fontweight="bold")

    # ---- (A) θ_thickness 事前→事後のガウス密度 ----
    axA = axes[0, 0]
    xs = [i / 400 for i in range(401)]

    def gauss(x, m, v):
        return math.exp(-(x - m) ** 2 / (2 * v)) / math.sqrt(2 * math.pi * v)

    axA.plot(xs, [gauss(x, prior_t.mu, prior_t.var) for x in xs],
             color="gray", ls="--", lw=1.5, label="prior")
    for r in runs:
        s = r["spec"]
        axA.plot(xs, [gauss(x, r["mu_t"][-1], r["var_t"][-1]) for x in xs],
                 color=s["color"], lw=2, label=f"{s['label']} post")
        axA.axvline(s["target"], color=s["color"], ls=":", lw=1, alpha=0.6)
    axA.set_title("(A) θ_thickness: prior → posterior density\n(dotted = each persona's target)")
    axA.set_xlabel("thickness (0=thin .. 1=thick)")
    axA.set_ylabel("density")
    axA.legend(fontsize=8)

    # ---- (B) σ²_thickness 逐次収縮 + 解析解 ----
    axB = axes[0, 1]
    for r in runs:
        s = r["spec"]
        axB.plot(ks, r["var_t"], color=s["color"], lw=2.5, alpha=0.55,
                 label=f"{s['label']} (impl)")
    axB.plot(ks, an_var_t, color="black", ls="--", lw=1.4,
             label="analytic 1/(1/σ²₀+N/σ²obs)")
    axB.set_title("(B) σ²_thickness shrink\n(3 personas overlap = variance is data-independent)")
    axB.set_xlabel("N observations")
    axB.set_ylabel("σ²_thickness")
    axB.legend(fontsize=8)

    # ---- (C) μ_thickness 逐次収束 ----
    axC = axes[0, 2]
    for r in runs:
        s = r["spec"]
        axC.plot(ks, r["mu_t"], color=s["color"], lw=2, marker="o", ms=3,
                 label=s["label"])
        axC.axhline(s["target"], color=s["color"], ls=":", lw=1, alpha=0.6)
    axC.set_title("(C) μ_thickness convergence\n(dotted = target)")
    axC.set_xlabel("N observations")
    axC.set_ylabel("μ_thickness")
    axC.set_ylim(-0.02, 1.02)
    axC.legend(fontsize=8)

    # ---- (D) θ_color 95% 信用楕円(a–b 平面) ----
    axD = axes[1, 0]
    rad = math.sqrt(CHI2_2DOF_95)
    for r in runs:
        s = r["spec"]
        ma, mb = r["mu_c"][-1][1], r["mu_c"][-1][2]
        va, vb = r["var_c"][-1][1], r["var_c"][-1][2]
        e = Ellipse((ma, mb), width=2 * rad * math.sqrt(va),
                    height=2 * rad * math.sqrt(vb),
                    facecolor=s["color"], alpha=0.22, edgecolor=s["color"], lw=2)
        axD.add_patch(e)
        axD.plot(ma, mb, "o", color=s["color"], label=s["label"])
    axD.set_title("(D) θ_color 95% credible ellipse (a–b plane)\nradius = √χ²(2,0.95)·σ")
    axD.set_xlabel("a*")
    axD.set_ylabel("b*")
    axD.legend(fontsize=8)
    axD.grid(alpha=0.3)
    axD.autoscale_view()

    # ---- (E) σ²_L 逐次収縮(log軸) ----
    axE = axes[1, 1]
    for r in runs:
        s = r["spec"]
        axE.plot(ks, [v[0] for v in r["var_c"]], color=s["color"], lw=2.5,
                 alpha=0.55, label=f"{s['label']} (impl)")
    axE.plot(ks, an_var_cL, color="black", ls="--", lw=1.4, label="analytic")
    axE.set_yscale("log")
    axE.set_title("(E) σ²_color L* shrink (log scale)")
    axE.set_xlabel("N observations")
    axE.set_ylabel("σ²_L (log)")
    axE.legend(fontsize=8)

    # ---- (F) 情報利得 KL[bit] 積み上げ棒 ----
    axF = axes[1, 2]
    labels, kl_t, kl_c = [], [], []
    report: List[str] = []
    report.append(f"=== Bayesian statistical report (N={n} AR-like obs) ===")
    report.append(f"shared prior: θ_thickness μ0={prior_t.mu:.3f} σ²0={prior_t.var:.4f}"
                  f" / θ_color σ²_L0={prior_c.var.L:.4f}")
    report.append("design prior (zero-knowledge): color = PC center σ²=100, "
                  "thickness = (0.5, 0.1)")
    report.append("")
    for r in runs:
        s = r["spec"]
        labels.append(s["label"])
        mt, vt = r["mu_t"][-1], r["var_t"][-1]
        kt = _kl_1d(mt, vt, design_t[0], design_t[1]) / LN2
        kc = 0.0
        for j in range(3):
            kc += _kl_1d(r["mu_c"][-1][j], r["var_c"][-1][j],
                         design_c[0][j], design_c[1][j]) / LN2
        kl_t.append(kt)
        kl_c.append(kc)

        # 統計の検証(実装 σ²_N == 解析解か)
        ok_t = abs(vt - an_var_t[-1]) < 1e-9
        ok_c = abs(r["var_c"][-1][0] - an_var_cL[-1]) < 1e-9
        ci = 1.96 * math.sqrt(vt)
        shrink = vt / prior_t.var
        report.append(f"[{s['label']}] target_t={s['target']}")
        report.append(f"  μ_thickness 事後 = {mt:.4f}  (95%CI {mt-ci:.3f}..{mt+ci:.3f})")
        report.append(f"  σ²_thickness 収縮率 = {shrink:.4f} ({prior_t.var:.4f}→{vt:.5f})")
        report.append(f"  情報利得 = {kt+kc:.2f} bit (thickness {kt:.2f} + color {kc:.2f})")
        report.append(f"  σ²_N 実装==解析解: thickness {'✓' if ok_t else '✗'} / "
                      f"color_L {'✓' if ok_c else '✗'}")
        report.append("")

    xpos = list(range(len(labels)))
    colors = [s["color"] for s in specs]
    axF.bar(xpos, kl_t, color=colors, alpha=0.55, label="θ_thickness")
    axF.bar(xpos, kl_c, bottom=kl_t, color=colors, alpha=0.95, label="θ_color")
    axF.set_xticks(xpos)
    axF.set_xticklabels(labels, fontsize=8)
    axF.set_title("(F) Information gain from zero-knowledge prior\n(KL[posterior||design prior], bits)")
    axF.set_ylabel("KL [bit]")
    axF.legend(fontsize=8)
    for i, (a, b) in enumerate(zip(kl_t, kl_c)):
        axF.text(i, a + b + 0.05, f"{a+b:.1f}", ha="center", fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out_path, dpi=130)
    plt.close(fig)

    return out_path, report


# ============ 図2: 収束速度の比較 ============

def _mu_thickness_closed(target: float, mu0: float, var0: float,
                         var_obs: float, n: int) -> float:
    """全観測が thickness=target のときの μ_thickness_N(閉形式)。

    μ_N = (μ0·σ²obs + N·t·σ²0) / (σ²obs + N·σ²0)
    """
    return (mu0 * var_obs + n * target * var0) / (var_obs + n * var0)


def _nstar_mean(target: float, mu0: float, var0: float,
                var_obs: float, eps: float) -> float:
    """|μ_N − target| ≤ eps を満たす最小 N(連続値、閉形式)。

    dev_N = |target−μ0|·σ²obs/(σ²obs+N·σ²0) ≤ eps
      → N ≥ (σ²obs/σ²0)·(|target−μ0|/eps − 1)
    """
    gap = abs(target - mu0)
    if gap <= eps:
        return 0.0
    return max(0.0, (var_obs / var0) * (gap / eps - 1.0))


def _nstar_ci(var0: float, var_obs: float, width_thresh: float) -> float:
    """95%CI 幅 ≤ width_thresh を満たす最小 N(全ペルソナ共通=データ非依存)。

    width = 2·1.96·sqrt(σ²_N),  σ²_N = 1/(1/σ²0 + N/σ²obs)
    """
    z = 1.96
    target_var = (width_thresh / (2 * z)) ** 2
    if target_var >= var0:
        return 0.0
    # 1/(1/var0 + N/var_obs) = target_var → N = var_obs·(1/target_var − 1/var0)
    return max(0.0, var_obs * (1.0 / target_var - 1.0 / var0))


def generate_convergence_report(specs: List[Dict], n_max: int = 40,
                                out_path: str = "bayes_convergence.png"
                                ) -> Tuple[str, List[str]]:
    """ペルソナごとに N をスイープし、収束速度を比較する図2を出力。

    (G) 95%CI 幅 vs N(全員共通=データ非依存)+ 閾値到達 N*
    (H) |μ_thickness − target| vs N(log軸)+ ε到達 N* マーカー
    (I) 地形図: |μ_N − target| を (N, target) グリッドで等高線表示 + ペルソナ重畳
    (J) N* 比較棒: 各ペルソナの「μ が target±0.05 に入る N*」+ CI幅0.2 到達 N*(共通)
    """
    import matplotlib
    matplotlib.use("Agg")
    try:
        import japanize_matplotlib  # noqa: F401
    except Exception:
        pass
    import matplotlib.pyplot as plt
    import numpy as np

    prior_t, _ = _build_prior()
    mu0, var0 = prior_t.mu, prior_t.var
    var_obs = bayesian.SIGMA2_OBS_THICKNESS  # 0.05
    z = 1.96
    eps = 0.05  # μ 収束の許容誤差
    ci_thresholds = [0.3, 0.2, 0.1]

    ks = list(range(n_max + 1))
    # 95%CI 幅(共通)
    var_t = [1.0 / (1.0 / var0 + k / var_obs) for k in ks]
    ci_width = [2 * z * math.sqrt(v) for v in var_t]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Bayesian convergence speed — θ_thickness (design doc v1.3 §7.5)",
                 fontsize=14, fontweight="bold")

    # ---- (G) 95%CI 幅 vs N + 閾値到達 N* ----
    axG = axes[0, 0]
    axG.plot(ks, ci_width, color="black", lw=2.5, label="95% CI width (shared)")
    for th in ci_thresholds:
        ns = _nstar_ci(var0, var_obs, th)
        axG.axhline(th, color="gray", ls=":", lw=1)
        axG.annotate(f"width≤{th}\n→ N*={math.ceil(ns)}",
                     xy=(ns, th), xytext=(ns + 1, th + 0.03),
                     fontsize=8, color="darkred",
                     arrowprops=dict(arrowstyle="->", color="darkred", lw=1))
        axG.plot([ns], [th], "o", color="darkred", ms=5)
    axG.set_title("(G) 95% CI width vs N (data-independent)\nconfidence tightens slowly")
    axG.set_xlabel("N observations")
    axG.set_ylabel("95% CI width of θ_thickness")
    axG.legend(fontsize=8)
    axG.grid(alpha=0.3)

    # ---- (H) |μ − target| 収束(log軸)+ N* ----
    axH = axes[0, 1]
    nstars = {}
    for s in specs:
        t = s["target"]
        dev = [abs(_mu_thickness_closed(t, mu0, var0, var_obs, k) - t) for k in ks]
        axH.plot(ks, [max(d, 1e-4) for d in dev], color=s["color"], lw=2,
                 label=f"{s['label']} (t={t})")
        ns = _nstar_mean(t, mu0, var0, var_obs, eps)
        nstars[s["key"]] = ns
        axH.plot([ns], [eps], "o", color=s["color"], ms=6)
    axH.axhline(eps, color="gray", ls=":", lw=1)
    axH.text(n_max * 0.5, eps * 1.15, f"ε={eps} tolerance", fontsize=8, color="gray")
    axH.set_yscale("log")
    axH.set_title("(H) |μ_thickness − target| convergence\n(mean direction learned fast, ~1/N)")
    axH.set_xlabel("N observations")
    axH.set_ylabel("|μ − target| (log)")
    axH.legend(fontsize=8)
    axH.grid(alpha=0.3, which="both")

    # ---- (I) 地形図: |μ_N − target| over (N, target) ----
    axI = axes[1, 0]
    n_grid = np.arange(1, n_max + 1)
    t_grid = np.linspace(0.0, 1.0, 51)
    NN, TT = np.meshgrid(n_grid, t_grid)
    # dev = |target−μ0|·σ²obs/(σ²obs+N·σ²0)
    Z = np.abs(TT - mu0) * var_obs / (var_obs + NN * var0)
    cf = axI.contourf(NN, TT, Z, levels=12, cmap="viridis")
    cs = axI.contour(NN, TT, Z, levels=[eps], colors="white", linewidths=1.5)
    axI.clabel(cs, fmt=f"dev={eps}", fontsize=8)
    fig.colorbar(cf, ax=axI, label="|μ_N − target|")
    for s in specs:
        t = s["target"]
        axI.axhline(t, color=s["color"], ls="--", lw=1.2, alpha=0.8)
        ns = nstars[s["key"]]
        axI.plot([ns], [t], "o", color=s["color"], ms=7, mec="white")
        axI.text(ns + 0.6, t, s["label"].split()[0], color="white", fontsize=8,
                 va="center", fontweight="bold")
    axI.set_title("(I) Convergence terrain: |μ_N − target| over (N, target)\n"
                  "(white line = ε; dots = each persona's N*)")
    axI.set_xlabel("N observations")
    axI.set_ylabel("target thickness")

    # ---- (J) N* 比較棒 ----
    axJ = axes[1, 1]
    labels = [s["label"].split()[0] for s in specs]
    colors = [s["color"] for s in specs]
    xpos = list(range(len(specs)))
    vals = [math.ceil(nstars[s["key"]]) for s in specs]
    axJ.bar(xpos, vals, color=colors, alpha=0.8)
    for i, v in enumerate(vals):
        axJ.text(i, v + 0.1, str(v), ha="center", fontsize=10, fontweight="bold")
    nci = math.ceil(_nstar_ci(var0, var_obs, 0.2))
    axJ.axhline(nci, color="darkred", ls="--", lw=1.5,
                label=f"N* for CI width≤0.2 = {nci}")
    axJ.set_xticks(xpos)
    axJ.set_xticklabels(labels, fontsize=9)
    axJ.set_title(f"(J) N* to reach |μ−target|≤{eps}\n(vs N* to reach CI confidence — much larger)")
    axJ.set_ylabel("N observations")
    axJ.legend(fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out_path, dpi=130)
    plt.close(fig)

    # テキストレポート
    report: List[str] = []
    report.append(f"=== Convergence speed report (N sweep 0..{n_max}) ===")
    report.append(f"shared: μ0={mu0:.2f} σ²0={var0:.4f} σ²obs={var_obs}")
    report.append("σ²(=CI幅)はデータ非依存 → 確信を締めるには共通の観測数が要る:")
    for th in ci_thresholds:
        report.append(f"  95%CI幅 ≤ {th}  → N* = {math.ceil(_nstar_ci(var0, var_obs, th))}")
    report.append("")
    report.append(f"μ が target±{eps} に入る N*(prior-target gap が大きいほど遅い):")
    for s in specs:
        report.append(f"  [{s['label']}] target={s['target']} "
                      f"gap={abs(s['target']-mu0):.2f} → N* = {math.ceil(nstars[s['key']])}")
    report.append("")
    report.append("洞察: 方向(μ)は N*≈3-4 で掴めるが、確信(CI幅0.2)は N*≈19 必要。")
    return out_path, report


# ============ personas_cli から Persona オブジェクト → spec へ ============

def specs_from_personas(personas) -> List[Dict]:
    """personas_cli.Persona のリストを bayes_plot 用 spec dict に変換。"""
    # 図は日本語フォント非依存にするため label は ASCII/romaji
    ascii_label = {"mina": "Mina (warm/thick)",
                   "aya": "Aya (sheer/thin)",
                   "yuki": "Yuki (matte/deep)"}
    color_hex = {"mina": "#e75480", "aya": "#3aa860", "yuki": "#3b7fd0"}
    specs = []
    for p in personas:
        labs = [(float(r["L"]), float(r["a"]), float(r["b"]))
                for r in p.matching_products]
        if not labs:
            continue
        lip = p.user["lip_lab"] if p.user else {"L": 62.0, "a": 22.0, "b": 12.0}
        specs.append({
            "key": p.name,
            "label": ascii_label.get(p.name, p.name),
            "color": color_hex.get(p.name, "#888888"),
            "target": p.target_thickness,
            "lip_lab": (lip["L"], lip["a"], lip["b"]),
            "product_labs": labs,
        })
    return specs
