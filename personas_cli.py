"""対話型 CLI: 3 ペルソナを並走させて個人化を比較検証する。

使い方:
    .venv/bin/python personas_cli.py

3 人(ミナ・アヤ・ユウキ)を同じ初期状態から始める。
コマンドを 1 つずつ叩くと、各人が自分の好みに合う商品で AR 観測 1 件を流す。
毎ステップ後に 3 人の TOP-3 と θ 状態を横並びで表示するので、
「同じスタートから別々の推薦に進化していく様子」が逐次見える。

コマンド:
    step          全員に観測 1 件ずつ流す
    step N        全員に N 件ずつまとめて流す
    top           現在の TOP-3 を 3 人横並び表示
    state         現在の θ パラメータを 3 人横並び表示
    formula       直近の更新で起きたベイズ計算の途中過程を表示
    diff          初期 TOP-5 と現在 TOP-5 の差分(順位変動)
    obs           各人の観測履歴
    reset         3 人とも初期状態に戻す
    help          このヘルプ
    quit / q      終了
"""

from __future__ import annotations

import csv
import math
import readline  # noqa: F401  - readline は import すると input() に履歴/編集機能が付く
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
        """このペルソナが次に「いいね」する商品を順番に返す。"""
        if not self.matching_products:
            return None
        p = self.matching_products[self.matching_idx % len(self.matching_products)]
        self.matching_idx += 1
        return p


PERSONAS = [
    Persona(
        "mina", 0.9,
        lambda r: (
            r["line_category"] == "tint"
            and float(r.get("x20_18_korean", 0)) > 0.3
            and float(r.get("x20_11_warm_tone", 0)) > 0.5
        ),
        "高校生・濃いめ暖色 韓国っぽい派",
    ),
    Persona(
        "aya", 0.2,
        lambda r: (
            r["line_category"] in ("gloss", "tint")
            and float(r.get("x20_02_transparency", 0)) > 0.4
            and float(r.get("x20_12_light_color", 0)) > 0.4
        ),
        "OL・薄め寒色 ナチュラル派",
    ),
    Persona(
        "yuki", 0.95,
        lambda r: (
            r["line_category"] in ("matte", "velvet")
            and float(r.get("x20_13_deep_color", 0)) > 0.3
            and float(r.get("x20_19_mature", 0)) > 0.2
        ),
        "学生・マット深色 マチュア派",
    ),
]


# ============ 初期化(全員同じペア選択から開始) ============

def initialize_all() -> None:
    pairs = client.get("/v13/pair_compare/init").json()["pairs"]
    choices = [{"pair_id": p["pair_id"], "chose": "left"} for p in pairs]
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
        # 初期 TOP-5 を記録
        rec = client.post("/v13/recommend", json={
            "user": p.user, "top_n": 5,
        }).json()
        p.initial_top5 = [r["product_id"] for r in rec["results"]]
        p.obs_history = []
        p.matching_idx = 0
        p.last_update_detail = None


# ============ 観測流し ============

def step_once(p: Persona) -> str:
    if p.user is None:
        return "未初期化"
    prod = p.next_like_product()
    if prod is None:
        return f"{p.label}: 候補商品なし"

    # 観測 Lab を簡易計算(t=target_thickness の線形補間)
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
    return f"{p.label}: 👍 {prod['color_name']} (t={t})"


def step_all(n: int = 1) -> None:
    for _ in range(n):
        for p in PERSONAS:
            msg = step_once(p)
            print(f"  {msg}")
    print()


# ============ 表示 ============

def get_top_n(p: Persona, n: int = 3) -> List[Dict]:
    if p.user is None:
        return []
    rec = client.post("/v13/recommend", json={
        "user": p.user, "top_n": n,
    }).json()
    return rec["results"]


def print_state_table() -> None:
    print(BOLD + "─" * 90 + RESET)
    print(f"{'':18s} {'μ_thickness':>14s} {'σ²_t':>10s} {'μ_color (L,a,b)':>25s} {'σ²_L':>10s} {'N_obs':>7s}")
    print(BOLD + "─" * 90 + RESET)
    for p in PERSONAS:
        if p.user is None:
            continue
        u = p.user
        n_obs = len(p.obs_history)
        line = (
            f"{p.color}{p.label:18s}{RESET} "
            f"{u['theta_thickness']['mu']:>14.4f} "
            f"{u['theta_thickness']['var']:>10.5f} "
            f" ({u['theta_color']['mu']['L']:5.1f},{u['theta_color']['mu']['a']:5.1f},{u['theta_color']['mu']['b']:5.1f}) "
            f"{u['theta_color']['var']['L']:>10.5f} "
            f"{n_obs:>7d}"
        )
        print(line)
    print()


def print_top_table(n: int = 3) -> None:
    rows = []
    for p in PERSONAS:
        top = get_top_n(p, n)
        rows.append((p, top))

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
        # 1セルが3行構造になっているので、行ごとに展開
        max_lines = max(c.count("\n") + 1 for c in cells)
        for li in range(max_lines):
            parts = []
            for c in cells:
                lines = c.split("\n")
                parts.append(lines[li] if li < len(lines) else "")
            print("  ".join(f"{part:<30s}" for part in parts))
        print()


def print_formula() -> None:
    print(BOLD + "📐 直近の更新で動いたベイズ式" + RESET)
    print(GRAY + "─" * 80 + RESET)
    for p in PERSONAS:
        d = p.last_update_detail
        if d is None:
            print(f"{p.color}{p.label}{RESET}: まだ観測なし")
            continue
        obs = d["obs"]
        bef = d["before"]
        aft = d["after"]
        sigma_obs_t = 0.05
        sigma_obs_ar = 1.0
        # σ²_thickness の計算過程
        precision_before = 1.0 / bef["var_t"]
        precision_added = 1.0 / sigma_obs_t
        new_var_t = 1.0 / (precision_before + precision_added)
        new_mu_t = new_var_t * (bef["mu_t"] / bef["var_t"] + obs["thickness"] / sigma_obs_t)

        print(f"\n{p.color}{BOLD}{p.label}{RESET} (target_thickness={p.target_thickness}):")
        print(f"  obs: t={obs['thickness']}, observed_lab=L{obs['observed_lab']['L']:.1f}")
        print(f"  {YELLOW}θ_thickness 更新 §7.5{RESET}")
        print(f"    σ²_N = 1/(1/{bef['var_t']:.5f} + 1/{sigma_obs_t}) = {new_var_t:.5f}")
        print(f"         actual: {aft['var_t']:.5f}  {'✓' if abs(new_var_t-aft['var_t'])<1e-4 else '✗'}")
        print(f"    μ_N = {new_var_t:.5f} × ({bef['mu_t']:.3f}/{bef['var_t']:.5f} + {obs['thickness']}/{sigma_obs_t})")
        print(f"        = {new_mu_t:.4f}")
        print(f"         actual: {aft['mu_t']:.4f}  {'✓' if abs(new_mu_t-aft['mu_t'])<1e-3 else '✗'}")

        # σ²_color_L の計算過程
        y = obs["y"]
        obs_L = obs["observed_lab"]["L"]
        precision_added_L = (y * y) / sigma_obs_ar
        new_var_L = 1.0 / (1.0 / bef["var_L"] + precision_added_L)
        new_mu_L = new_var_L * (bef["mu_L"] / bef["var_L"] + (y * obs_L) / sigma_obs_ar)
        print(f"  {YELLOW}θ_color L 更新 §7.2{RESET}")
        print(f"    σ²_N = 1/(1/{bef['var_L']:.5f} + 1/{sigma_obs_ar}) = {new_var_L:.5f}")
        print(f"         actual: {aft['var_L']:.5f}  {'✓' if abs(new_var_L-aft['var_L'])<1e-4 else '✗'}")
        print(f"    μ_N = {new_var_L:.5f} × ({bef['mu_L']:.2f}/{bef['var_L']:.5f} + {y}×{obs_L:.2f}/{sigma_obs_ar})")
        print(f"        = {new_mu_L:.4f}  → actual: {aft['mu_L']:.4f}")
    print()


def print_diff() -> None:
    print(BOLD + "📊 初期 TOP-5 vs 現在 TOP-5 の比較" + RESET)
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
        print(f"  入替: {GREEN if n_new > 0 else GRAY}{n_new} 件が新規{RESET}, {n_overlap} 件が継続")
    print()


def print_obs() -> None:
    print(BOLD + "📋 観測ログ" + RESET)
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


# ============ REPL ============

HELP = """
コマンド:
  step         全員に観測 1 件流す
  step N       全員に N 件流す
  top [n]      TOP-N 横並び (default 3)
  state        θ 横並び
  formula      直近のベイズ式 + 計算値 + 一致確認
  diff         初期 TOP-5 と現在 TOP-5 の差分
  obs          観測履歴
  reset        全リセット
  help         ヘルプ
  quit / q     終了
"""


def repl() -> None:
    print(BOLD + "💄 Fibrous Lipstick — 3 ペルソナ並走検証 CLI" + RESET)
    print(GRAY + "初期化中..." + RESET)
    initialize_all()
    print(f"初期化完了。3 ペルソナ(ブルベ夏 + 同じペア選択)で開始。")
    for p in PERSONAS:
        print(f"  {p.color}{p.label}{RESET}: {p.description}")
    print(HELP)
    print_state_table()
    print_top_table(3)

    while True:
        try:
            cmd = input(BOLD + "(personas) > " + RESET).strip()
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
            n = int(parts[1]) if len(parts) > 1 else 1
            step_all(n)
            print_state_table()
            print_top_table(3)
        elif verb == "top":
            n = int(parts[1]) if len(parts) > 1 else 3
            print_top_table(n)
        elif verb == "state":
            print_state_table()
        elif verb == "formula":
            print_formula()
        elif verb == "diff":
            print_diff()
        elif verb == "obs":
            print_obs()
        elif verb == "reset":
            initialize_all()
            print("✅ リセット完了")
            print_state_table()
        else:
            print(f"{RED}不明なコマンド: {verb}{RESET}")
            print(HELP)


if __name__ == "__main__":
    try:
        repl()
    except Exception as e:
        print(f"{RED}エラー: {e}{RESET}", file=sys.stderr)
        raise
