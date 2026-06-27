"""A4: シーン事前 × 問数削減 + アルゴリズム・ブラッシュアップ検証(in silico)。

本番 pair_eig / scene_priors / bayesian / recommend_v2 を実際に呼ぶ。
分析スクリプト(テストではない)。**ローカルは skimage の Gatekeeper ハングで
動かない**ため CI(.github/workflows/a4.yml, clean Linux)で実行し、
標準出力のログから数値を読む。docs/figures/*.png は CI アーティファクト。

検証する問い(cc_prompts A4 + 厚め6項目。定数の変更自体は人間が判断する):
  1. 基本: scene事前 + 7-8問 ≈ flat事前 + 10問 の収束(θ_pref 事後分散 / hit率)。
  2. EIG均衡: 色ペア vs 世界観ペアの EIG スケール(σ²=20.83 で色KLが小さく出る件)。
  3. EIG vs ランダム vs 固定10 の収束カーブ(発表の主張=能動学習が効く の再確認)。
  4. ペルソナ別の収束差(個人差が出る=パーソナライズの実証)。
  5. familiarity 重み(w1/w2/w3)感度分析(アブレーション)。
  6. serendipity 定義検討: 現行(TOP-N 中央値)vs「上位軸は満たすが確信の低い軸で
     冒険」案の比較データ。
  +  KAPPA 感度 / is_系3軸アブレーション / 逐次EIG 序盤バイアス(C/D 確定材料)。

出力: 標準出力の数値表 + docs/figures/a4_validation.png / a4_curves.png。
要約と推奨(N_PAIRS / KAPPA / β_BT + 所見2-6)は LOG.md に別途追記。
"""

from __future__ import annotations

import csv
import os
import random
import statistics
import sys
from typing import Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import bayesian                          # noqa: E402
import km                                # noqa: E402
import pair_compare as pc                # noqa: E402
import pair_eig                          # noqa: E402
import recommend_v2 as rv2               # noqa: E402
import scene_priors                      # noqa: E402
from catalog_x20 import AXIS_NAMES, X20_COL_NAMES, load_x20_from_row  # noqa: E402
from constants import TAU2_PREF          # noqa: E402
from models_v13 import (                 # noqa: E402
    KMTableRow, LabValue, LabValue as LV, RecommendV2Request,
)
from recommend_v2 import delta_e_2000, effective_lab, recommend_v2  # noqa: E402

CATALOG_PATH = os.path.join(REPO_ROOT, "products_with_lab.csv")
LIP = LabValue(L=62.0, a=22.0, b=12.0)
IS_AXES_IDX = [AXIS_NAMES.index(a) for a in ("is_tint", "is_balm", "is_gloss")]

# ペルソナ: (key, line_categories, x20フィルタ条件, scenes)。matching は CATALOG から。
PERSONA_SPECS = [
    ("mina", ("tint",), [("x20_01_saturation", ">", 0.4), ("x20_19_korean", ">", 0.05)],
     ["school", "friends"]),
    ("aya", ("gloss", "tint"), [("x20_06_sheer", ">", 0.4), ("x20_02_brightness", ">", 0.5)],
     ["friends", "date"]),
    ("yuki", ("matte", "velvet"), [("x20_02_brightness", "<", 0.45), ("x20_07_velvet", ">", 0.25)],
     ["date", "special"]),
]


def _load_catalog() -> List[Dict]:
    rows = []
    with open(CATALOG_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "excluded":
                continue
            try:
                lab = (float(r["L"]), float(r["a"]), float(r["b"]))
            except (KeyError, ValueError, TypeError):
                continue
            r["_lab"] = lab
            r["_x20"] = load_x20_from_row(r)
            rows.append(r)
    return rows


def _km_table(catalog: List[Dict], mask_is: bool = False) -> List[KMTableRow]:
    """全カタログ × 21段の applied_Lab(_km_table_for_user 相当)。mask_is で is_系3軸を0に。"""
    lip = [LIP.L, LIP.a, LIP.b]
    rows: List[KMTableRow] = []
    for p in catalog:
        ks = km.ks_from_lab(list(p["_lab"]))
        s, _ = km.resolve_line_s(line_id=p.get("line_id"), line_category=p.get("line_category"))
        applied = []
        for i in range(21):
            a = km.compute_applied_lab(lip, ks, s, i / 20.0)
            applied.append(LV(L=float(a[0]), a=float(a[1]), b=float(a[2])))
        x20 = list(p["_x20"])
        if mask_is:
            for j in IS_AXES_IDX:
                x20[j] = 0.0
        rows.append(KMTableRow(product_id=p["id"], applied=applied, x20=x20,
                               name=p.get("color_name", ""),
                               line_category=p.get("line_category", "tint")))
    return rows


def _matching(catalog: List[Dict], spec) -> List[Dict]:
    _key, cats, conds, _scenes = spec
    out = []
    for r in catalog:
        if r.get("line_category") not in cats:
            continue
        ok = True
        for col, op, thr in conds:
            v = float(r.get(col) or 0.0)
            if (op == ">" and not v > thr) or (op == "<" and not v < thr):
                ok = False
                break
        if ok:
            out.append(r)
    return out


def _true_pref(matching: List[Dict], mask_is: bool) -> Tuple[LabValue, List[float]]:
    """matching 商品の平均 Lab / x20 を「真の好み」とする。"""
    labs = [m["_lab"] for m in matching]
    x20s = [list(m["_x20"]) for m in matching]
    tc = LabValue(L=statistics.mean(l[0] for l in labs),
                  a=statistics.mean(l[1] for l in labs),
                  b=statistics.mean(l[2] for l in labs))
    tx = [statistics.mean(x[j] for x in x20s) for j in range(20)]
    if mask_is:
        for j in IS_AXES_IDX:
            tx[j] = 0.0
    return tc, tx


def _oracle_choice(pair, true_color: LabValue, true_x20: List[float],
                   row_by_id, mu_t: float) -> str:
    """ペルソナの実際の選択(決定的): 真の好みに近い側を選ぶ。"""
    def fit(side):
        if pair.pair_type == "color":
            eff = pair_eig._eff_lab(side, row_by_id, mu_t)
            return -delta_e_2000(eff, true_color)
        return sum(t * x for t, x in zip(true_x20, side.x20))
    return "left" if fit(pair.left) >= fit(pair.right) else "right"


def _avg_pref_var(user) -> float:
    return statistics.mean(user.theta_pref.var)


def _recommend(user, km_table, top_n: int = 5, fam_weights: Optional[Sequence[float]] = None):
    kw: Dict = {}
    if fam_weights is not None:
        kw["familiarity_weights"] = list(fam_weights)
    return recommend_v2(RecommendV2Request(user=user, km_table=km_table, top_n=top_n, **kw))


def _hit_rate(user, km_table, matching_ids: set, top_n: int = 5,
              fam_weights=None) -> float:
    res = _recommend(user, km_table, top_n=top_n, fam_weights=fam_weights)
    if not res.results:
        return 0.0
    hit = sum(1 for it in res.results if it.product_id in matching_ids)
    return hit / len(res.results)


def _top5_ids(user, km_table, fam_weights=None) -> set:
    res = _recommend(user, km_table, top_n=5, fam_weights=fam_weights)
    return {it.product_id for it in res.results}


def _pick_next(strategy: str, user, asked: List[str], row_by_id, mu_t: float,
               rng_order: List) -> Optional[Tuple[object, float]]:
    """選択戦略に応じて次のペアを返す。eig=能動学習 / random / fixed=v13固定順。"""
    asked_set = set(asked)
    if strategy == "eig":
        return pair_eig.best_pair(user, pc.PAIR_BANK, asked, row_by_id, mu_t)
    pool = rng_order if strategy == "random" else pc.PAIR_BANK
    for p in pool:
        if p.pair_id not in asked_set:
            return p, 0.0
    return None


def run_arm(spec, catalog, km_table, row_by_id, n_pairs: int,
            use_scenes: bool, mask_is: bool, strategy: str = "eig",
            fam_weights=None, track_curve: bool = False) -> Dict:
    """1ペルソナ・1条件を逐次シミュレートして指標を返す。track_curve で各問後の hit/σ²。"""
    key, _cats, _conds, scenes = spec
    matching = _matching(catalog, spec)
    matching_ids = {m["id"] for m in matching}
    true_color, true_x20 = _true_pref(matching, mask_is)
    mu_t = 0.5
    user = pc.build_seed_user(
        LIP, pc_season="ブルベ夏",
        scenes=scenes if use_scenes else None, mu_thickness=mu_t,
    )
    if mask_is:  # アブレーション: θ_pref 事前の is_系軸も 0 固定
        mu = list(user.theta_pref.mu)
        for j in IS_AXES_IDX:
            mu[j] = 0.0
        user.theta_pref.mu = mu

    # random 戦略は決定的シャッフル順を1度だけ固定(seed=ペルソナ名)
    rng_order = list(pc.PAIR_BANK)
    random.Random(f"{key}|{strategy}|rnd").shuffle(rng_order)

    asked: List[str] = []
    type_counts = {"color": 0, "worldview": 0}
    early_is_split = 0  # 最初の3問で is_系が割れるペアを選んだ回数
    var_curve: List[float] = [_avg_pref_var(user)]   # step0 = 事前
    hit_curve: List[float] = (
        [_hit_rate(user, km_table, matching_ids, fam_weights=fam_weights)]
        if track_curve else []
    )
    for step in range(n_pairs):
        picked = _pick_next(strategy, user, asked, row_by_id, mu_t, rng_order)
        if picked is None:
            break
        pair, _eig = picked
        asked.append(pair.pair_id)
        type_counts[pair.pair_type] += 1
        if step < 3:
            li = {AXIS_NAMES[j]: pair.left.x20[j] for j in IS_AXES_IDX}
            ri = {AXIS_NAMES[j]: pair.right.x20[j] for j in IS_AXES_IDX}
            if any(abs(li[a] - ri[a]) > 0.5 for a in li):
                early_is_split += 1
        chose = _oracle_choice(pair, true_color, true_x20, row_by_id, mu_t)
        user = pair_eig.apply_v14_choice(user, pair, chose, row_by_id, mu_t)
        var_curve.append(_avg_pref_var(user))
        if track_curve:
            hit_curve.append(_hit_rate(user, km_table, matching_ids, fam_weights=fam_weights))

    return {
        "key": key,
        "user": user,
        "avg_var": _avg_pref_var(user),
        "hit": _hit_rate(user, km_table, matching_ids, fam_weights=fam_weights),
        "top5": _top5_ids(user, km_table, fam_weights=fam_weights),
        "type_counts": type_counts,
        "early_is_split": early_is_split,
        "n_matching": len(matching_ids),
        "var_curve": var_curve,
        "hit_curve": hit_curve,
    }


# ============ 6. serendipity 定義比較 ============

def _serendipity_compare(user, km_table, row_by_id, top_n: int = 10) -> Dict:
    """現行(TOP-N 中央値)vs 提案(上位軸満たす×低確信軸で冒険)の比較データ。"""
    res = _recommend(user, km_table, top_n=top_n)
    items = res.results
    if len(items) < 3:
        return {"n": len(items), "median": 0, "proposed": 0, "overlap": 0}
    mu_pref = user.theta_pref.mu
    pref_var = user.theta_pref.var
    x20_by_id = {r.product_id: list(r.x20) for r in km_table}
    thr_var = rv2.RHO_CONFIDENT * TAU2_PREF   # 確信閾値(=0.5)

    def proposed_flag(it) -> bool:
        x20 = x20_by_id[it.product_id]
        # (a) 確信ある上位軸を満たす: var≤閾値 かつ μ_pref·x20>0
        satisfy = any(pref_var[k] <= thr_var and mu_pref[k] * x20[k] > 0 for k in range(20))
        # (b) 低確信の軸で冒険: var>閾値 かつ x20 が高い(>0.5)
        adventure = any(pref_var[k] > thr_var and x20[k] > 0.5 for k in range(20))
        return satisfy and adventure

    median_ids = {it.product_id for it in items if it.is_serendipity}
    proposed_ids = {it.product_id for it in items if proposed_flag(it)}
    return {
        "n": len(items),
        "median": len(median_ids),
        "proposed": len(proposed_ids),
        "overlap": len(median_ids & proposed_ids),
        "median_ids": median_ids,
        "proposed_ids": proposed_ids,
    }


def main() -> None:
    print("=== A4 検証(シーン事前 × 問数削減 + ブラッシュアップ6項目)===")
    catalog = _load_catalog()
    km_table = _km_table(catalog, mask_is=False)
    row_by_id = {r.product_id: r for r in km_table}
    print(f"catalog={len(catalog)} / pairs={len(pc.PAIR_BANK)} / KAPPA={scene_priors.KAPPA} "
          f"/ β_BT={pair_eig.BETA_BT} / σ²_color={bayesian._PAIR_COLOR_SIGMA2:.3f}")

    # ===== 2. EIG 均衡: flat seed の step1 で 色ペア vs 世界観ペアの EIG =====
    print("\n## [2] EIG スケール均衡(flat seed, step1 の各タイプ EIG)")
    seed = pc.build_seed_user(LIP, pc_season="ブルベ夏", scenes=None, mu_thickness=0.5)
    by_type = {"color": [], "worldview": []}
    for p in pc.PAIR_BANK:
        by_type[p.pair_type].append((pair_eig.eig_pair(seed, p, row_by_id, 0.5), p.pair_id))
    for t in ("color", "worldview"):
        vals = sorted(by_type[t], reverse=True)
        mx = vals[0][0] if vals else 0.0
        mn = statistics.mean(v for v, _ in vals) if vals else 0.0
        print(f"  {t:>9}: max EIG={mx:.4f} bit, mean={mn:.4f} (n={len(vals)})")
    ratio = (max(v for v, _ in by_type['color']) /
             max(v for v, _ in by_type['worldview'])) if by_type['worldview'] else float('inf')
    print(f"  → color/worldview max EIG 比 = {ratio:.2f}(1付近=均衡 / 極端だと一方に偏る)")

    # ===== 1+4. 収束 + ペルソナ別差: scene+n(6,7,8) vs flat+10 =====
    print("\n## [1] 収束: scene事前+n問 vs flat+10問(ペルソナ平均)")
    print(f"{'条件':>14}{'avg σ²(↓)':>11}{'hit率(↑)':>9}{'色/世':>8}{'序盤is':>7}")
    arms = [("flat+10", False, 10)] + [(f"scene+{n}", True, n) for n in (6, 7, 8)]
    arm_results: Dict[str, List[Dict]] = {}
    for label, use_scenes, n in arms:
        res = [run_arm(s, catalog, km_table, row_by_id, n, use_scenes, mask_is=False)
               for s in PERSONA_SPECS]
        arm_results[label] = res
        avg_var = statistics.mean(r["avg_var"] for r in res)
        hit = statistics.mean(r["hit"] for r in res)
        cc = sum(r["type_counts"]["color"] for r in res)
        wv = sum(r["type_counts"]["worldview"] for r in res)
        eis = sum(r["early_is_split"] for r in res)
        print(f"{label:>14}{avg_var:>11.3f}{hit:>9.2f}{f'{cc}/{wv}':>8}{eis:>7}")

    print("\n## [4] ペルソナ別の収束差(scene+8。個人差=パーソナライズの実証)")
    r8 = arm_results["scene+8"]
    print(f"{'ペルソナ':>8}{'avg σ²':>9}{'hit率':>8}{'matching数':>11}")
    for r in r8:
        print(f"{r['key']:>8}{r['avg_var']:>9.3f}{r['hit']:>8.2f}{r['n_matching']:>11}")
    var_spread = max(r["avg_var"] for r in r8) - min(r["avg_var"] for r in r8)
    hit_spread = max(r["hit"] for r in r8) - min(r["hit"] for r in r8)
    print(f"  σ²スプレッド={var_spread:.3f} / hitスプレッド={hit_spread:.2f}")
    print("  top5 ペア重複率(Jaccard。低い=個人差維持):")
    for i in range(len(r8)):
        for j in range(i + 1, len(r8)):
            a, b = r8[i]["top5"], r8[j]["top5"]
            jac = len(a & b) / len(a | b) if (a | b) else 0.0
            print(f"    {r8[i]['key']} vs {r8[j]['key']}: Jaccard={jac:.2f}")

    # ===== 3. EIG vs random vs fixed-10 収束カーブ(flat seed で戦略のみ比較)=====
    print("\n## [3] EIG vs ランダム vs 固定10 の収束カーブ(flat seed・ペルソナ平均)")
    strat_curves: Dict[str, Dict[str, List[float]]] = {}
    for strat in ("eig", "random", "fixed"):
        res = [run_arm(s, catalog, km_table, row_by_id, 10, use_scenes=False,
                       mask_is=False, strategy=strat, track_curve=True)
               for s in PERSONA_SPECS]
        # 各 step のペルソナ平均(全ペルソナ同 step 数=10)
        steps = len(res[0]["hit_curve"])
        hit_avg = [statistics.mean(r["hit_curve"][k] for r in res) for k in range(steps)]
        var_avg = [statistics.mean(r["var_curve"][k] for r in res) for k in range(steps)]
        strat_curves[strat] = {"hit": hit_avg, "var": var_avg}
        # 主要 step だけ表示(0,2,4,6,8,最終)
        marks = [0, 2, 4, 6, 8, steps - 1]
        hit_s = " ".join(f"{hit_avg[k]:.2f}" for k in marks)
        var_s = " ".join(f"{var_avg[k]:.2f}" for k in marks)
        print(f"  {strat:>7} step{marks}: hit={hit_s}")
        print(f"  {strat:>7} {' ' * (5 + len(str(marks)))}σ²={var_s}")
    # 早期(4問時点)の EIG 優位を数値化
    for k in (4, 6):
        e, rnd, fx = (strat_curves[s]["hit"][k] for s in ("eig", "random", "fixed"))
        print(f"  → {k}問時点 hit: eig={e:.2f} / random={rnd:.2f} / fixed={fx:.2f} "
              f"(eig−random={e - rnd:+.2f})")

    # ===== 5. familiarity 重み(w1/w2/w3)感度分析 =====
    print("\n## [5] familiarity 重み感度(scene+8、既定[4,3,2]からの変化)")
    base_w = [4.0, 3.0, 2.0]
    base_res = [run_arm(s, catalog, km_table, row_by_id, 8, True, mask_is=False,
                        fam_weights=base_w) for s in PERSONA_SPECS]
    base_hit = statistics.mean(r["hit"] for r in base_res)
    base_top5 = {r["key"]: r["top5"] for r in base_res}
    print(f"  既定[4,3,2]: hit={base_hit:.2f}")
    sweeps = [
        ("w1=0 (対話項オフ)", [0.0, 3.0, 2.0]),
        ("w2=0 (cos項オフ)", [4.0, 0.0, 2.0]),
        ("w3=0 (ΔE_inv項オフ)", [4.0, 3.0, 0.0]),
        ("均等[3,3,3]", [3.0, 3.0, 3.0]),
        ("cos重視[2,6,2]", [2.0, 6.0, 2.0]),
    ]
    for label, w in sweeps:
        res = [run_arm(s, catalog, km_table, row_by_id, 8, True, mask_is=False,
                       fam_weights=w) for s in PERSONA_SPECS]
        hit = statistics.mean(r["hit"] for r in res)
        # 既定からの top5 安定性(Jaccard 平均)
        jacs = []
        for r in res:
            a, b = r["top5"], base_top5[r["key"]]
            jacs.append(len(a & b) / len(a | b) if (a | b) else 1.0)
        print(f"  {label:>22}: hit={hit:.2f} (Δ{hit - base_hit:+.2f}) / "
              f"top5安定 Jaccard={statistics.mean(jacs):.2f}")

    # ===== 6. serendipity 定義比較 =====
    print("\n## [6] serendipity 定義比較(scene+8 後の TOP-10。現行 vs 提案)")
    print("  現行=ΔE>median ∧ fam<median / 提案=確信上位軸満たす ∧ 低確信軸(var>0.5)で x20>0.5")
    tot = {"median": 0, "proposed": 0, "overlap": 0}
    for r in r8:
        cmp = _serendipity_compare(r["user"], km_table, row_by_id, top_n=10)
        tot["median"] += cmp["median"]
        tot["proposed"] += cmp["proposed"]
        tot["overlap"] += cmp["overlap"]
        print(f"  {r['key']:>6}: 現行={cmp['median']} / 提案={cmp['proposed']} / "
              f"重複={cmp['overlap']} (of {cmp['n']})")
    print(f"  合計: 現行={tot['median']} / 提案={tot['proposed']} / 重複={tot['overlap']} "
          f"(3ペルソナ × TOP-10)")

    # ===== KAPPA 感度 =====
    print("\n## [+] KAPPA 感度(scene+8、avg σ² / hit)")
    orig_kappa = scene_priors.KAPPA
    for kappa in (0.5, 0.65, 0.8):
        scene_priors.KAPPA = kappa
        res = [run_arm(s, catalog, km_table, row_by_id, 8, True, mask_is=False)
               for s in PERSONA_SPECS]
        print(f"  KAPPA={kappa}: avg σ²={statistics.mean(r['avg_var'] for r in res):.3f}, "
              f"hit={statistics.mean(r['hit'] for r in res):.2f}")
    scene_priors.KAPPA = orig_kappa

    # ===== is_系 アブレーション(20軸 vs 17軸)=====
    print("\n## [+] is_系3軸アブレーション(scene+8)")
    km_masked = _km_table(catalog, mask_is=True)
    rowmask = {r.product_id: r for r in km_masked}
    for label, mask, table, rb in (("20軸(現行)", False, km_table, row_by_id),
                                    ("17軸(is_系mask)", True, km_masked, rowmask)):
        res = [run_arm(s, catalog, table, rb, 8, True, mask_is=mask) for s in PERSONA_SPECS]
        print(f"  {label}: avg σ²={statistics.mean(r['avg_var'] for r in res):.3f}, "
              f"hit={statistics.mean(r['hit'] for r in res):.2f}")

    _draw(arm_results, strat_curves)
    print("\n✅ A4 検証完了。要約と推奨を LOG.md に追記する。")


def _setup_jp_font(matplotlib):
    from matplotlib import font_manager as fm
    names = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Hiragino Sans", "YuGothic", "Noto Sans CJK JP", "Arial Unicode MS"):
        if cand in names:
            matplotlib.rcParams["font.family"] = cand
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


def _draw(arm_results: Dict[str, List[Dict]], strat_curves: Dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    _setup_jp_font(matplotlib)
    import matplotlib.pyplot as plt

    labels = list(arm_results.keys())
    avg_var = [statistics.mean(r["avg_var"] for r in arm_results[k]) for k in labels]
    hit = [statistics.mean(r["hit"] for r in arm_results[k]) for k in labels]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    ax1.bar(labels, avg_var, color="#3b7fd0")
    ax1.set_title("theta_pref avg posterior var (lower=confident)")
    ax1.set_ylabel("avg sigma^2")
    ax1.tick_params(axis="x", rotation=20)
    ax2.bar(labels, hit, color="#e75480")
    ax2.set_title("hit rate (TOP-5 cap matching / higher=better)")
    ax2.set_ylabel("hit rate")
    ax2.tick_params(axis="x", rotation=20)
    fig.suptitle("A4: scene-prior + n pairs vs flat + 10 (persona mean, in silico)",
                 fontweight="bold")
    fig.tight_layout()
    out = os.path.join(REPO_ROOT, "docs", "figures", "a4_validation.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"✅ 図: {out}")

    # 収束カーブ(EIG vs random vs fixed)
    fig2, (cx1, cx2) = plt.subplots(1, 2, figsize=(11, 4.5))
    styles = {"eig": ("#2a9d8f", "o-"), "random": ("#e9c46a", "s--"), "fixed": ("#bbbbbb", "^:")}
    for strat, cur in strat_curves.items():
        col, st = styles[strat]
        xs = list(range(len(cur["hit"])))
        cx1.plot(xs, cur["hit"], st, color=col, label=strat)
        cx2.plot(xs, cur["var"], st, color=col, label=strat)
    cx1.set_title("hit rate vs #questions"); cx1.set_xlabel("# pairs answered")
    cx1.set_ylabel("hit rate"); cx1.legend()
    cx2.set_title("avg sigma^2 vs #questions"); cx2.set_xlabel("# pairs answered")
    cx2.set_ylabel("avg sigma^2"); cx2.legend()
    fig2.suptitle("A4-[3]: active EIG vs random vs fixed-10 (persona mean)", fontweight="bold")
    fig2.tight_layout()
    out2 = os.path.join(REPO_ROOT, "docs", "figures", "a4_curves.png")
    fig2.savefig(out2, dpi=130)
    plt.close(fig2)
    print(f"✅ 図: {out2}")


if __name__ == "__main__":
    main()
