"""💄 Fibrous Lipstick — 3 ペルソナ並走シミュレータ (CLI)

「同じ初期状態から始めた 3 人が、観測を重ねるごとに違う方向に進化していく」
を、ターミナルから対話的に観察できるシミュレータ。

起動: .venv/bin/python personas_cli.py
"""

from __future__ import annotations

import csv
import math
import readline  # noqa: F401 — input() に履歴/編集を付ける
import sys
from typing import Any, Callable, Dict, List

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

# ============ ANSI カラー ============
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
PINK = "\033[95m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
GRAY = "\033[90m"
BLUE = "\033[94m"

PERSONA_COLORS = {"mina": PINK, "aya": GREEN, "yuki": CYAN}
PERSONA_LABELS = {"mina": "🌸 ミナ", "aya": "🌿 アヤ", "yuki": "💎 ユウキ"}


# ============ カタログロード ============

with open("products_with_lab.csv", encoding="utf-8") as f:
    CATALOG = list(csv.DictReader(f))
CATALOG_BY_ID = {r["id"]: r for r in CATALOG}


# ============ ペルソナ定義 ============

class Persona:
    def __init__(self, name: str, target_thickness: float,
                 product_filter: Callable[[Dict], bool], description: str):
        self.name = name
        self.label = PERSONA_LABELS[name]
        self.color = PERSONA_COLORS[name]
        self.target_thickness = target_thickness
        self.product_filter = product_filter
        self.description = description
        self.matching_products = [r for r in CATALOG if product_filter(r)]
        self.matching_idx = 0
        self.user: Dict | None = None
        self.initial_top5: List[str] = []
        self.obs_history: List[Dict] = []
        self.last_update_detail: Dict | None = None

    def next_like_product(self) -> Dict | None:
        if not self.matching_products:
            return None
        p = self.matching_products[self.matching_idx % len(self.matching_products)]
        self.matching_idx += 1
        return p


# ペルソナフィルタは products_with_lab.csv の「実在する」x20 カラムで定義する。
# DB 20軸の実カラムは x20_00_hue 〜 x20_19_korean(catalog_x20.AXIS_NAMES 準拠)。
# 旧版は x20_11_warm_tone / x20_18_korean / x20_02_transparency 等の
# 存在しないカラムを参照しており matching_products が空になっていた(修正済み)。

def _x(r: Dict, col: str) -> float:
    """x20 カラムを安全に float 取得(欠損は 0.0)。"""
    return float(r.get(col) or 0.0)


PERSONAS = [
    Persona(
        "mina", 0.9,
        lambda r: (
            r["line_category"] == "tint"
            and _x(r, "x20_01_saturation") > 0.4   # 鮮やか
            and _x(r, "x20_19_korean") > 0.05       # 韓国っぽい(MLBB)
        ),
        "高1・濃いめ暖色 韓国っぽい派",
    ),
    Persona(
        "aya", 0.2,
        lambda r: (
            r["line_category"] in ("gloss", "tint")
            and _x(r, "x20_06_sheer") > 0.4          # 透け感
            and _x(r, "x20_02_brightness") > 0.5     # 明るい
        ),
        "OL・薄めヌード ナチュラル派",
    ),
    Persona(
        "yuki", 0.95,
        lambda r: (
            r["line_category"] in ("matte", "velvet")
            and _x(r, "x20_02_brightness") < 0.45    # 深い(暗い)
            and _x(r, "x20_07_velvet") > 0.25        # ベルベット感
        ),
        "大学生・マット深色 マチュア派",
    ),
]


# ============ 解釈ラベル(数値を言葉に) ============

def interp_thickness(mu: float) -> str:
    if mu < 0.30:
        return f"{BLUE}薄めが好き 💧{RESET}"
    if mu < 0.45:
        return f"{BLUE}やや薄め寄り{RESET}"
    if mu < 0.55:
        return f"{GRAY}中立(まだ未知){RESET}"
    if mu < 0.70:
        return f"{YELLOW}やや濃いめ寄り{RESET}"
    if mu < 0.85:
        return f"{YELLOW}濃いめが好き 💋{RESET}"
    return f"{RED}ガッツリ濃いめ ❤️‍🔥{RESET}"


def interp_var(var: float, var_0: float) -> str:
    """σ² の縮みを「確信度」として解釈。"""
    if var >= var_0 * 0.9:
        return f"{GRAY}確信なし{RESET}"
    if var >= var_0 * 0.5:
        return f"{GRAY}少し動き始めた{RESET}"
    if var >= var_0 * 0.2:
        return f"{YELLOW}方向性が見えてきた{RESET}"
    if var >= var_0 * 0.05:
        return f"{GREEN}かなり確信{RESET}"
    return f"{GREEN}{BOLD}ほぼ確定{RESET}"


def progress_bar(value: float, vmin: float = 0.0, vmax: float = 1.0,
                 width: int = 20) -> str:
    """0.0〜1.0 の値を■と□で視覚化。"""
    norm = (value - vmin) / (vmax - vmin)
    norm = max(0.0, min(1.0, norm))
    n_filled = int(round(norm * width))
    return "■" * n_filled + "□" * (width - n_filled)


# ============ 初期化 ============

def initialize_all() -> None:
    print(GRAY + "  API 叩いてペアを取得…" + RESET)
    pairs = client.get("/v13/pair_compare/init").json()["pairs"]
    choices = [{"pair_id": p["pair_id"], "chose": "left"} for p in pairs]
    print(GRAY + f"  全 {len(pairs)} ペア取得済。全員 left を選んだ前提で事前分布構築…" + RESET)
    apply_res = client.post("/v13/pair_compare/apply", json={
        "choices": choices, "pc_season": "ブルベ夏",
    }).json()
    for p in PERSONAS:
        p.user = {
            "user_id": f"{p.name}_persona",
            "lip_lab": {"L": 62.0, "a": 22.0, "b": 12.0},
            "pc_season": "ブルベ夏",
            "theta_color": dict(apply_res["theta_color"]),
            "theta_pref": dict(apply_res["theta_pref"]),
            "theta_explore": dict(apply_res["theta_explore"]),
            "theta_thickness": dict(apply_res["theta_thickness"]),
        }
        rec = client.post("/v13/recommend", json={
            "user": p.user, "top_n": 5,
        }).json()
        p.initial_top5 = [r["product_id"] for r in rec["results"]]
        p.obs_history = []
        p.matching_idx = 0
        p.last_update_detail = None


# ============ 観測流し ============

def step_once(p: Persona) -> Dict | None:
    if p.user is None:
        return None
    prod = p.next_like_product()
    if prod is None:
        return None

    lip = p.user["lip_lab"]
    L, a, b = float(prod["L"]), float(prod["a"]), float(prod["b"])
    t = p.target_thickness
    eff_lab = {
        "L": lip["L"] * (1 - t) + L * t,
        "a": lip["a"] * (1 - t) + a * t,
        "b": lip["b"] * (1 - t) + b * t,
    }
    obs = {
        "source": "ar_view_like",
        "product_id": prod["id"],
        "observed_lab": eff_lab,
        "thickness": t,
        "y": 1.0,
    }
    user_before = p.user
    res = client.post("/v13/update_user", json={
        "user": user_before, "observations": [obs],
    }).json()
    p.user = res["user"]

    p.obs_history.append({
        "n": len(p.obs_history) + 1,
        "product_id": prod["id"],
        "name": prod["color_name"],
        "thickness": t,
    })
    p.last_update_detail = {
        "obs": obs,
        "before": {
            "mu_t": user_before["theta_thickness"]["mu"],
            "var_t": user_before["theta_thickness"]["var"],
            "mu_L": user_before["theta_color"]["mu"]["L"],
            "var_L": user_before["theta_color"]["var"]["L"],
        },
        "after": {
            "mu_t": p.user["theta_thickness"]["mu"],
            "var_t": p.user["theta_thickness"]["var"],
            "mu_L": p.user["theta_color"]["mu"]["L"],
            "var_L": p.user["theta_color"]["var"]["L"],
        },
    }
    return {"prod": prod, "obs": obs, "before": p.last_update_detail["before"],
            "after": p.last_update_detail["after"]}


def step_all(n: int = 1) -> None:
    for round_idx in range(n):
        print(BOLD + YELLOW + f"\n── 観測ラウンド #{round_idx + 1} ──" + RESET)
        for p in PERSONAS:
            r = step_once(p)
            if r is None:
                print(f"  {p.color}{p.label}{RESET}: 候補商品なし")
                continue
            prod = r["prod"]
            bef = r["before"]
            aft = r["after"]
            # Narrative
            dt_mu = aft["mu_t"] - bef["mu_t"]
            arrow = "↑" if dt_mu > 0.01 else ("↓" if dt_mu < -0.01 else "→")
            print(
                f"  {p.color}{p.label}{RESET}: 👍 "
                f"{BOLD}{prod['color_name']}{RESET} "
                f"{GRAY}({prod['line_category']}, t={r['obs']['thickness']}){RESET}"
            )
            print(
                f"     μ_thickness: {bef['mu_t']:.3f} {arrow} {aft['mu_t']:.3f}   "
                f"{GRAY}({interp_thickness(aft['mu_t'])}){RESET}"
            )


# ============ 表示 ============

def get_top_n(p: Persona, n: int = 3) -> List[Dict]:
    if p.user is None:
        return []
    rec = client.post("/v13/recommend", json={
        "user": p.user, "top_n": n,
    }).json()
    return rec["results"]


def print_state_table() -> None:
    print(BOLD + "\n📌 各ペルソナの現在の脳内パラメータ" + RESET)
    print(GRAY + "  μ = ベイズ事後の中心値(=「だいたいこの値だと思ってる」)" + RESET)
    print(GRAY + "  σ² = 事後分散(=どれだけ確信あるか。小さいほど確信)" + RESET)
    print(GRAY + "  μ_thickness は 0=極薄, 1=濃ベタ。観測で動く" + RESET)
    print(BOLD + "─" * 95 + RESET)
    print(
        f"{'ペルソナ':16s} "
        f"{'μ_thickness':>13s} {'バー':>22s} "
        f"{'σ²_thick':>10s} "
        f"{'確信度':>20s} "
        f"{'N観測':>5s}"
    )
    print(BOLD + "─" * 95 + RESET)
    var_t_0 = 0.10  # 事前分散
    for p in PERSONAS:
        if p.user is None:
            continue
        u = p.user
        mu_t = u["theta_thickness"]["mu"]
        var_t = u["theta_thickness"]["var"]
        n_obs = len(p.obs_history)
        print(
            f"{p.color}{p.label:16s}{RESET} "
            f"{mu_t:>13.4f}  "
            f"{progress_bar(mu_t):>22s}  "
            f"{var_t:>10.5f} "
            f"{interp_var(var_t, var_t_0):>20s} "
            f"{n_obs:>5d}"
        )

    print()
    print(BOLD + "  μ_color(似合う色の中心 Lab):" + RESET)
    for p in PERSONAS:
        if p.user is None:
            continue
        u = p.user
        print(
            f"  {p.color}{p.label:14s}{RESET}: "
            f"L={u['theta_color']['mu']['L']:5.1f}  "
            f"a={u['theta_color']['mu']['a']:5.1f}  "
            f"b={u['theta_color']['mu']['b']:5.1f}  "
            f"{GRAY}σ²_L={u['theta_color']['var']['L']:.4f}{RESET}"
        )
    print()


def print_top_table(n: int = 3) -> None:
    rows = []
    for p in PERSONAS:
        top = get_top_n(p, n)
        rows.append((p, top))

    print(BOLD + f"\n🏆 各ペルソナの TOP-{n}(R_final 降順)" + RESET)
    print(GRAY + "  R_final = -α·ΔE(eff_Lab, μ_color) + μ_pref·x_20 - β·familiarity (Part IV+VI)" + RESET)
    print(GRAY + "  eff_Lab = μ_thickness で K-M 補間した「塗布後の見え方」" + RESET)
    print(BOLD + "─" * 100 + RESET)
    header = "  ".join(f"{p.color}{p.label:^30s}{RESET}" for p, _ in rows)
    print(header)
    print(BOLD + "─" * 100 + RESET)
    for i in range(n):
        cells = []
        for p, top in rows:
            if i < len(top):
                it = top[i]
                catalog = CATALOG_BY_ID.get(it["product_id"], {})
                name = catalog.get("color_name", it["product_id"])[:18]
                line = catalog.get("line_category", "?")
                eff = it["effective_lab"]
                cell = (
                    f"#{i+1} {name}\n"
                    f"     [{line}] eff L{eff['L']:.0f}a{eff['a']:.0f}b{eff['b']:.0f}\n"
                    f"     R={it['r_final']:.2f} ΔE={it['delta_e_to_color']:.1f}"
                )
            else:
                cell = "-"
            cells.append(cell)
        max_lines = max(c.count("\n") + 1 for c in cells)
        for li in range(max_lines):
            parts = []
            for c in cells:
                lines = c.split("\n")
                parts.append(lines[li] if li < len(lines) else "")
            print("  ".join(f"{part:<30s}" for part in parts))
        print()


def print_formula() -> None:
    print(BOLD + "\n📐 直近の更新で動いたベイズ式 + 設計書 vs 実装の一致確認" + RESET)
    print(GRAY + "  ✓ が出れば「設計書の式」と「実装の出力」が完全一致" + RESET)
    print(GRAY + "─" * 80 + RESET)
    for p in PERSONAS:
        d = p.last_update_detail
        if d is None:
            print(f"\n{p.color}{p.label}{RESET}: まだ観測なし")
            continue
        obs = d["obs"]
        bef = d["before"]
        aft = d["after"]
        sigma_obs_t = 0.05
        sigma_obs_ar = 1.0
        new_var_t = 1.0 / (1.0 / bef["var_t"] + 1.0 / sigma_obs_t)
        new_mu_t = new_var_t * (bef["mu_t"] / bef["var_t"] + obs["thickness"] / sigma_obs_t)

        print(f"\n{p.color}{BOLD}{p.label}{RESET} (target_thickness={p.target_thickness}):")
        print(f"  観測 1 件: t={obs['thickness']}, observed_lab.L={obs['observed_lab']['L']:.1f}")
        print(f"  {YELLOW}── θ_thickness 更新 (設計書 §7.5) ──{RESET}")
        print(f"  σ²_N = 1 / (1/σ²_0 + N/σ²_obs)")
        print(f"       = 1 / (1/{bef['var_t']:.5f} + 1/{sigma_obs_t}) = {new_var_t:.5f}")
        print(f"       {GREEN}implementation: {aft['var_t']:.5f}  ✓{RESET}" if abs(new_var_t-aft['var_t'])<1e-4
              else f"       {RED}implementation: {aft['var_t']:.5f}  ✗{RESET}")
        print(f"  μ_N = σ²_N × (μ_0/σ²_0 + Σt_k/σ²_obs)")
        print(f"      = {new_var_t:.5f} × ({bef['mu_t']:.3f}/{bef['var_t']:.5f} + {obs['thickness']}/{sigma_obs_t})")
        print(f"      = {new_mu_t:.4f}")
        print(f"       {GREEN}implementation: {aft['mu_t']:.4f}  ✓{RESET}" if abs(new_mu_t-aft['mu_t'])<1e-3
              else f"       {RED}implementation: {aft['mu_t']:.4f}  ✗{RESET}")

        y = obs["y"]
        obs_L = obs["observed_lab"]["L"]
        new_var_L = 1.0 / (1.0 / bef["var_L"] + (y * y) / sigma_obs_ar)
        new_mu_L = new_var_L * (bef["mu_L"] / bef["var_L"] + (y * obs_L) / sigma_obs_ar)
        print(f"  {YELLOW}── θ_color (L成分) 更新 (設計書 §7.2) ──{RESET}")
        print(f"  σ²_N = 1/(1/{bef['var_L']:.5f} + {y*y}/{sigma_obs_ar}) = {new_var_L:.5f}")
        print(f"       {GREEN}implementation: {aft['var_L']:.5f}  ✓{RESET}" if abs(new_var_L-aft['var_L'])<1e-4
              else f"       {RED}implementation: {aft['var_L']:.5f}  ✗{RESET}")
        print(f"  μ_N = {new_var_L:.5f} × ({bef['mu_L']:.2f}/{bef['var_L']:.5f} + {y}×{obs_L:.2f}/{sigma_obs_ar})")
        print(f"      = {new_mu_L:.4f}  → impl: {aft['mu_L']:.4f}")
    print()


def print_diff() -> None:
    print(BOLD + "\n📊 初期 TOP-5 vs 現在 TOP-5 の比較" + RESET)
    print(GRAY + "  全員が同じ初期 TOP-5 からスタート → 観測でどう分岐したか" + RESET)
    print(GRAY + "─" * 80 + RESET)
    for p in PERSONAS:
        if p.user is None:
            continue
        current = get_top_n(p, 5)
        current_ids = [r["product_id"] for r in current]
        initial_ids = p.initial_top5
        n_overlap = len(set(current_ids) & set(initial_ids))
        n_new = 5 - n_overlap

        print(f"\n{p.color}{BOLD}{p.label}{RESET} (観測 N={len(p.obs_history)}):")
        print(f"  初期 TOP-5: {GRAY}{', '.join(_short(i) for i in initial_ids)}{RESET}")
        print(f"  現在 TOP-5: {', '.join(_short(i) for i in current_ids)}")
        msg_color = GREEN if n_new > 0 else GRAY
        print(f"  {msg_color}入替: {n_new} 件が新規, {n_overlap} 件が継続{RESET}")
    print()


def print_obs() -> None:
    print(BOLD + "\n📋 観測ログ" + RESET)
    print(GRAY + "  ペルソナが「いいね」した商品の履歴" + RESET)
    print(GRAY + "─" * 80 + RESET)
    for p in PERSONAS:
        print(f"\n{p.color}{p.label}{RESET} ({len(p.obs_history)} 件):")
        for h in p.obs_history[-10:]:
            print(f"  #{h['n']:2d} {h['name']:25s} (t={h['thickness']})")
        if len(p.obs_history) > 10:
            print(f"  ... ほか {len(p.obs_history)-10} 件")
    print()


def _short(pid: str) -> str:
    return pid.replace("rmd_", "")[:18]


# ============ plot: ベイズ更新の統計的可視化 ============

def cmd_plot(n: int = 15) -> None:
    """各ペルソナに N 観測を逐次適用し、bayes_report.png を出力する。

    可視化は AR like で動く θ_thickness / θ_color に限定(θ_pref/θ_explore は不変)。
    計算は bayes_plot(bayesian/pair_compare 直叩き、API 不使用)で行う。
    """
    try:
        import bayes_plot
    except Exception as e:
        print(f"{RED}❌ bayes_plot の読み込み失敗: {e}{RESET}")
        return

    specs = bayes_plot.specs_from_personas(PERSONAS)
    if not specs:
        print(f"{RED}❌ matching_products が空。ペルソナフィルタを確認してください。{RESET}")
        return

    print(GRAY + f"📈 各ペルソナに {n} 観測を逐次適用して図を生成中…" + RESET)
    print(GRAY + "   (初回は matplotlib の読み込みに時間がかかる場合あり)" + RESET)
    try:
        out1, report1 = bayes_plot.generate_report(specs, n=n, out_path="bayes_report.png")
        # 図2: 収束速度(N をスイープ。最低でも 30 まで伸ばして収束を見せる)
        n_max = max(n, 30)
        out2, report2 = bayes_plot.generate_convergence_report(
            specs, n_max=n_max, out_path="bayes_convergence.png")
    except ImportError:
        print(f"{RED}❌ matplotlib が無い。`.venv/bin/pip install -r requirements-ui.txt`{RESET}")
        return
    except Exception as e:
        print(f"{RED}❌ 図生成エラー: {e}{RESET}")
        return

    # テキストレポート(色なしを色付けして表示)
    def _print_report(lines):
        for line in lines:
            if line.startswith("[") or line.startswith("==="):
                print(f"{BOLD}{line}{RESET}")
            elif "✓" in line:
                print(f"{GREEN}{line}{RESET}")
            elif "✗" in line:
                print(f"{RED}{line}{RESET}")
            else:
                print(line)

    print()
    _print_report(report1)
    print()
    _print_report(report2)
    print(f"\n{GREEN}✅ 図1(統計ビュー)を保存: {BOLD}{out1}{RESET}")
    print(f"{GREEN}✅ 図2(収束速度)を保存: {BOLD}{out2}{RESET}{GREEN} "
          f"(open bayes_report.png bayes_convergence.png){RESET}")


# ============ ヘルプ ============

INTRO = f"""
{BOLD}{PINK}╭──────────────────────────────────────────────────────────────────────╮{RESET}
{BOLD}{PINK}│  💄 Fibrous Lipstick — 3 ペルソナ並走シミュレータ                       │{RESET}
{BOLD}{PINK}╰──────────────────────────────────────────────────────────────────────╯{RESET}

{BOLD}このシミュレータは何?{RESET}
  3 人の異なる好みのペルソナを同じ初期状態から始めて、
  「いいね」観測を重ねるごとに違う方向に進化していく様子を観察する。
  裏では設計書 v1.3 のベイズ更新が動いている。

{BOLD}用語の凡例{RESET}
  {YELLOW}θ (シータ){RESET} ベイズ更新する 4 つの個人パラメータ
    - θ_color    : 似合う色の中心 Lab
    - θ_pref     : 20 次元好みベクトル(機能 15+ 世界観 5)
    - θ_thickness: 塗り方の好み(0=薄め 〜 1=濃いめ)
    - θ_explore  : 新しい発見への興味度
  {YELLOW}μ (ミュー){RESET} ベイズ事後の中心値 (=「だいたいこの値」と思ってる)
  {YELLOW}σ² (シグマ二乗){RESET} 事後分散 (=どれだけ確信あるか。小さいほど確信)
  {YELLOW}effective_Lab{RESET} μ_thickness で K-M 物理計算した「塗布後の見え方」
  {YELLOW}R_final{RESET} 各商品の最終スコア。大きいほど上位
"""

HELP = f"""
{BOLD}コマンド一覧{RESET} ({DIM}< > は引数、[ ] は省略可{RESET})

  {BOLD}step{RESET} [{DIM}<回数>{RESET}]    3 人全員にそれぞれ観測を流す
                  例: {GRAY}step{RESET} = 1 件、{GRAY}step 5{RESET} = 5 件まとめて
  {BOLD}top{RESET}  [{DIM}<件数>{RESET}]    各ペルソナの TOP-N を横並び表示 (省略=3)
  {BOLD}state{RESET}            θ パラメータ(μ・σ²)の現状を横並び
  {BOLD}formula{RESET}          直近のベイズ計算を式 + 値 + 一致確認 で表示
  {BOLD}plot{RESET} [{DIM}<観測数>{RESET}]   N 観測を適用しベイズ更新を統計的に可視化 → bayes_report.png
                  (省略=15。θ_thickness/θ_color の収束・信用楕円・情報利得[bit])
  {BOLD}diff{RESET}             初期 TOP-5 と現在 TOP-5 の差分(順位変動)
  {BOLD}obs{RESET}              各ペルソナの観測履歴
  {BOLD}reset{RESET}            3 人とも初期状態に戻す
  {BOLD}help{RESET}             このヘルプ
  {BOLD}quit{RESET} / {BOLD}q{RESET}         終了
"""


# ============ REPL ============

def repl() -> None:
    print(INTRO)
    print(GRAY + "🔧 初期化中…" + RESET)
    initialize_all()
    print(f"\n{BOLD}✅ 初期化完了。同じ事前分布(ブルベ夏 + 全員 left 選択)からスタート。{RESET}\n")
    print(f"{BOLD}3 ペルソナ:{RESET}")
    for p in PERSONAS:
        print(f"  {p.color}{p.label}{RESET}: {p.description}")
        print(f"    {GRAY}→ 好み: {p.matching_products[0]['color_name'] if p.matching_products else '?'} 系の商品で t={p.target_thickness}{RESET}")
    print(HELP)
    print_state_table()
    print_top_table(3)
    print(GRAY + f"💡 ヒント: まず {BOLD}step 5{RESET}{GRAY} で 5 観測ずつ流して、その後 {BOLD}diff{RESET}{GRAY} と {BOLD}formula{RESET}{GRAY} を試すと違いがよく分かる" + RESET)

    while True:
        try:
            cmd = input(f"\n{BOLD}(personas) ▸ {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nbye.")
            return
        if not cmd:
            continue
        parts = cmd.split()
        verb = parts[0].lower()

        if verb in ("q", "quit", "exit"):
            print("bye.")
            return
        elif verb == "help":
            print(HELP)
        elif verb == "step":
            n = 1
            if len(parts) > 1:
                try:
                    n = int(parts[1])
                except ValueError:
                    print(f"{RED}❌ '{parts[1]}' は半角整数で指定してください。例: {BOLD}step 5{RESET}")
                    continue
                if n < 1 or n > 100:
                    print(f"{RED}❌ 回数は 1〜100 の範囲で指定してください{RESET}")
                    continue
            step_all(n)
            print_state_table()
            print_top_table(3)
        elif verb == "top":
            n = 3
            if len(parts) > 1:
                try:
                    n = int(parts[1])
                except ValueError:
                    print(f"{RED}❌ '{parts[1]}' は半角整数で。例: {BOLD}top 5{RESET}")
                    continue
                n = max(1, min(10, n))
            print_top_table(n)
        elif verb == "plot":
            n = 15
            if len(parts) > 1:
                try:
                    n = int(parts[1])
                except ValueError:
                    print(f"{RED}❌ '{parts[1]}' は半角整数で。例: {BOLD}plot 20{RESET}")
                    continue
                if n < 1 or n > 100:
                    print(f"{RED}❌ 観測数は 1〜100 の範囲で{RESET}")
                    continue
            cmd_plot(n)
        elif verb == "state":
            print_state_table()
        elif verb == "formula":
            print_formula()
        elif verb == "diff":
            print_diff()
        elif verb == "obs":
            print_obs()
        elif verb == "reset":
            print(GRAY + "🔄 リセット中…" + RESET)
            initialize_all()
            print(f"{GREEN}✅ リセット完了{RESET}")
            print_state_table()
        else:
            print(f"{RED}❌ 不明なコマンド: '{verb}'{RESET}")
            print(f"{GRAY}   help を叩くとコマンド一覧が出ます{RESET}")


if __name__ == "__main__":
    try:
        repl()
    except Exception as e:
        print(f"{RED}エラー: {e}{RESET}", file=sys.stderr)
        raise
