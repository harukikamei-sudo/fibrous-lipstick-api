"""Kawano さん協議用の検証結果グラフ4枚(kawano_*.png)。

★数値は **本セッションの A4 / collapse 調査 CI 実測値**(LOG.md エポック16 記載)を
そのまま定数として使う。新しい値を作らない・推定しない。実データが harness に無い図は
生成しない方針(本ファイルの4図は全て実測あり)。

出典(すべて make_a4_validation.py を CI(test.yml の a4 ジョブ)で実行した実測):
  - 図1 収束: [1] 収束表(flat+10 / scene+6/7/8 の hit と σ²)
  - 図2 機序: [diag] (3) TOP5 f-score 内訳(|色項| と |好み項| の平均、支配比 9x/6x)
  - 図3 限界: [pairsep] v1 試算 + [draft v2] 6案不採用
  - 図4 実証: [reasons] mina/aya(共有5・固有軸0/1)vs mina/yuki(共有0・固有軸3/5)

skimage 非依存(matplotlib のみ)。ローカルで動けばそのまま、ダメなら CI で artifact 化。
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")

# 日本語フォント: japanize-matplotlib(CI)→ macOS の Hiragino 等(ローカル)→ 無ければ英語。
try:
    import japanize_matplotlib  # noqa: F401
    JP = True
except Exception:
    JP = False
    from matplotlib import font_manager as _fm
    _names = {f.name for f in _fm.fontManager.ttflist}
    for _cand in ("Hiragino Sans", "YuGothic", "Hiragino Maru Gothic Pro",
                  "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "Arial Unicode MS"):
        if _cand in _names:
            matplotlib.rcParams["font.family"] = _cand
            matplotlib.rcParams["axes.unicode_minus"] = False
            JP = True
            break
    if not JP:  # 表記揺れ対策(Noto Sans CJK JP / Hiragino 系の family 名差)
        for _n in _names:
            if ("CJK" in _n) or ("Hiragino" in _n) or _n.startswith("Noto Sans JP"):
                matplotlib.rcParams["font.family"] = _n
                matplotlib.rcParams["axes.unicode_minus"] = False
                JP = True
                break

import matplotlib.pyplot as plt  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = _HERE
GREEN = "#2a9d8f"   # 改善 / 良い
RED = "#e76f51"     # 悪化 / 注意
BLUE = "#3b7fd0"    # 中立(現行など)
GRAY = "#bbbbbb"


def L(jp: str, en: str) -> str:
    return jp if JP else en


def _save(fig, name: str) -> str:
    out = os.path.join(OUT_DIR, name)
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"✅ {out}")
    return out


def _bar_labels(ax, bars, fmt="{:.2f}", dy=0.0):
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt.format(h), (b.get_x() + b.get_width() / 2, h),
                    ha="center", va="bottom", fontsize=10, fontweight="bold",
                    xytext=(0, 2 + dy), textcoords="offset points")


# ============ 図1: 問数削減 ============
def fig_npairs() -> str:
    # 出典: [1] 収束表(persona 平均)
    labels = ["flat+10", "scene+6", "scene+7", "scene+8"]
    hit = [0.47, 0.40, 0.47, 0.47]
    var = [0.376, 0.442, 0.440, 0.402]
    colors = [BLUE, GRAY, GREEN, GREEN]

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    bars = ax.bar(labels, hit, color=colors, width=0.6)
    _bar_labels(ax, bars)
    ax.axhline(0.47, color=BLUE, ls="--", lw=1.3)
    # 基準線ラベルは scene+6(0.40)上の空白域に置く(各棒の値ラベルと重ねない)
    ax.text(1.0, 0.485, L("flat+10 の精度", "flat+10 level"),
            color=BLUE, fontsize=9, ha="center", va="bottom")
    ax.set_ylim(0, 0.6)
    ax.set_ylabel(L("hit率(TOP5 ∩ 好み商品 / 高いほど良い)", "hit rate (higher=better)"))
    ax.set_title(L("シーンを聞けば 7問で 10問と同じ精度(質問を3問削減)",
                   "Asking the scene: 7 questions match 10 (−3 questions)"),
                 fontsize=13, fontweight="bold")
    # σ² を小さく注記
    for i, v in enumerate(var):
        ax.annotate(f"σ²={v:.2f}", (i, 0.02), ha="center", fontsize=8, color="#666")
    return _save(fig, "kawano_npairs.png")


# ============ 図2: collapse の機序(色項 >> 好み項)============
def fig_collapse() -> str:
    # 出典: [diag] (3) TOP5 平均 |色項|=6.78、|好み項| mina=0.79(9x)/aya=1.12(6x)
    groups = ["mina", "aya"]
    color_term = [6.78, 6.78]
    pref_term = [0.79, 1.12]
    x = range(len(groups))
    w = 0.36

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    b1 = ax.bar([i - w / 2 for i in x], color_term, w, color=BLUE,
                label=L("色の一致度(−α·ΔE)", "color term (−α·ΔE)"))
    b2 = ax.bar([i + w / 2 for i in x], pref_term, w, color=RED,
                label=L("好みの軸(μ_pref·x20)", "preference term"))
    _bar_labels(ax, b1)
    _bar_labels(ax, b2)
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel(L("推薦スコアへの寄与(絶対値・大きいほど支配的)",
                    "contribution to score (|magnitude|)"))
    ax.legend(loc="upper right")
    ax.set_title(L("推薦は「色」が「好み」を 6〜9倍 支配 → 色が近い人は推薦も同じ",
                   "Color dominates preference 6-9x → similar color = same recs"),
                 fontsize=12.5, fontweight="bold")
    ax.annotate(L("9倍", "9x"), (-w / 2, 6.78), xytext=(-w / 2, 5.2),
                ha="center", color=BLUE, fontsize=9)
    return _save(fig, "kawano_collapse.png")


# ============ 図3: 色ペアで割ると別の同一化(構造的限界)============
def fig_pairfix() -> str:
    # 出典: [pairsep] v1 試算(現行 vs 分離色ペア v1)
    #   mina/aya Jaccard 1.00→0.00、mina/yuki 0.00→0.67、mina hit 0.20→0.00
    #   [draft v2] 制約付き6案はすべて不採用
    metrics = [L("mina/aya\n同一度", "mina/aya\noverlap"),
               L("mina/yuki\n同一度", "mina/yuki\noverlap"),
               L("mina\nhit率", "mina\nhit")]
    current = [1.00, 0.00, 0.20]
    after = [0.00, 0.67, 0.00]
    # 改善(緑)/悪化(赤): Jaccard は低いほど良い、hit は高いほど良い
    after_colors = [GREEN, RED, RED]  # ma↓=改善, my↑=悪化, hit↓=悪化
    x = range(len(metrics))
    w = 0.36

    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    b1 = ax.bar([i - w / 2 for i in x], current, w, color=GRAY,
                label=L("現行の色ペア", "current pairs"))
    b2 = ax.bar([i + w / 2 for i in x], after, w, color=after_colors,
                label=L("色ペアを分離力で改修(v1)", "separation-max pairs (v1)"))
    _bar_labels(ax, b1)
    _bar_labels(ax, b2)
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel(L("Jaccard(低=分離)/ hit率(高=良)", "Jaccard (low=split) / hit (high=good)"))
    ax.legend(loc="upper center", ncol=2, fontsize=9)
    ax.set_title(L("色ペアで mina/aya を割ると mina↔yuki が新たに同一化(構造的限界)",
                   "Splitting mina/aya by color creates a NEW mina-yuki collapse"),
                 fontsize=12, fontweight="bold")
    ax.annotate(L("※ 精度を落とさず分離する制約付き6案も すべて不採用",
                  "* 6 constrained recipes all failed the gate too"),
                (0.5, -0.22), xycoords="axes fraction", ha="center",
                fontsize=9, color=RED)
    return _save(fig, "kawano_pairfix.png")


# ============ 図4: 戦略(A)の実証(似た人/異なる人)============
def fig_reasons() -> str:
    # 出典: [reasons] mina/aya: 共有TOP5=5, 固有理由軸 mina0+aya1=1
    #                mina/yuki: 共有TOP5=0, 固有理由軸 mina3+yuki5=8
    groups = [L("似た人\n(mina vs aya)", "similar\n(mina vs aya)"),
              L("異なる人\n(mina vs yuki)", "different\n(mina vs yuki)")]
    shared = [5, 0]            # 共有 TOP5 件数(0-5)
    unique_axes = [1, 8]       # 固有の推薦理由 軸数(合計)
    x = range(len(groups))
    w = 0.36

    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    b1 = ax.bar([i - w / 2 for i in x], shared, w, color=BLUE,
                label=L("共有する推薦(TOP5 中)", "shared recs (of TOP5)"))
    b2 = ax.bar([i + w / 2 for i in x], unique_axes, w, color=GREEN,
                label=L("固有の推薦理由(軸数)", "distinct reason axes"))
    _bar_labels(ax, b1, fmt="{:.0f}")
    _bar_labels(ax, b2, fmt="{:.0f}")
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel(L("件数 / 軸数", "count"))
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title(L("似た人=同じ推薦(正当)/ 異なる人=別推薦・別理由(差別化が機能)",
                   "Similar→same recs (valid) / Different→different recs & reasons"),
                 fontsize=12, fontweight="bold")
    return _save(fig, "kawano_reasons.png")


# ============ 図5(日報/上長用・別枠): EIG vs ランダム vs 固定 の収束 ============
def fig_eig() -> str:
    # 出典: [3] EIG vs random vs fixed 収束カーブ(persona 平均 hit、steps 0,2,4,6,8,10)
    steps = [0, 2, 4, 6, 8, 10]
    eig = [0.33, 0.13, 0.53, 0.47, 0.47, 0.47]
    fixed = [0.33, 0.20, 0.47, 0.47, 0.47, 0.47]
    rand = [0.33, 0.20, 0.40, 0.07, 0.27, 0.47]

    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    ax.plot(steps, eig, "o-", color=GREEN, lw=2.4, ms=7, label=L("能動学習(EIG)", "active (EIG)"))
    ax.plot(steps, fixed, "^--", color=BLUE, lw=1.7, ms=6, label=L("固定順", "fixed order"))
    ax.plot(steps, rand, "s:", color=RED, lw=1.7, ms=6, label=L("ランダム", "random"))
    ax.set_xlabel(L("回答した質問数", "# questions answered"))
    ax.set_ylabel(L("hit率(高いほど良い)", "hit rate (higher=better)"))
    ax.set_xticks(steps)
    ax.set_ylim(0, 0.62)
    ax.legend(loc="lower right")
    ax.annotate(L("ランダムは序盤の悪手で急落", "random collapses on early mistakes"),
                (6, 0.07), xytext=(6.2, 0.24), color=RED, fontsize=9, ha="center",
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.annotate(L("EIG は4問で最高精度", "EIG peaks by Q4"),
                (4, 0.53), xytext=(3.2, 0.585), color=GREEN, fontsize=9, ha="center")
    ax.set_title(L("能動学習(EIG)は早く高精度で安定 / ランダムは不安定",
                   "Active (EIG) is fast & stable; random is unstable"),
                 fontsize=12.5, fontweight="bold")
    return _save(fig, "kawano_eig.png")


def main() -> None:
    print(f"japanize-matplotlib: {'有効' if JP else '無し(英語ラベル)'}")
    fig_npairs()
    fig_collapse()
    fig_pairfix()
    fig_reasons()
    fig_eig()  # 日報/上長用(協議4枚とは別枠)
    print("✅ Kawano 図 5枚(協議4 + 日報用1)生成完了")


if __name__ == "__main__":
    main()
