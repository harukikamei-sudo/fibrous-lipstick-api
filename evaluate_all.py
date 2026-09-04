"""PC 連携の妥当性をバッチ評価。

5 つの唇プリセット × 4 つの PC = 20 組み合わせを /evaluate に流し、
「論文ベース予測 TOP-N」と「カタログ pc_season タグ」の一致率を集計する。

使い方:
  python evaluate_all.py                # ローカル(TestClient)で実行
  python evaluate_all.py --api <URL>    # 公開 API を叩く

MVP の合格ラインは平均一致率 70%。
"""

import argparse
import json
from itertools import product as iproduct

import km


PRESETS = list(km.LIP_PRESETS)          # 5
PCS = list(km.PC_SEASONS)               # 4


def _local_post(lip_lab, expected_pc, top_n):
    from fastapi.testclient import TestClient
    import app as appmod
    c = TestClient(appmod.app)
    r = c.post("/evaluate", json={
        "lip_lab": {"L": lip_lab[0], "a": lip_lab[1], "b": lip_lab[2]},
        "expected_pc": expected_pc,
        "top_n": top_n,
    })
    r.raise_for_status()
    return r.json()


def _remote_post(base, lip_lab, expected_pc, top_n):
    import requests
    r = requests.post(f"{base.rstrip('/')}/evaluate", json={
        "lip_lab": {"L": lip_lab[0], "a": lip_lab[1], "b": lip_lab[2]},
        "expected_pc": expected_pc,
        "top_n": top_n,
    }, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", help="公開 API ベースURL(未指定はローカル TestClient)")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--json", action="store_true", help="JSON で全結果出力")
    args = ap.parse_args()

    rows = []
    print(f"{'唇プリセット':<14} {'PC':<10} {'matched/N':<11} {'rate':<6} "
          f"{'空skip':<7} {'interp'}")
    print("-" * 70)
    for preset, pc in iproduct(PRESETS, PCS):
        lab = km.LIP_PRESETS[preset]
        if args.api:
            res = _remote_post(args.api, lab, pc, args.top_n)
        else:
            res = _local_post(lab, pc, args.top_n)
        rows.append({"preset": preset, "pc": pc, **res})
        print(f"{preset:<14} {pc:<10} {res['matched_count']}/{res['top_n']:<8} "
              f"{res['match_rate']:<6.2f} {res.get('n_empty_tag_skipped',0):<7} "
              f"{res['interpretation']}")

    rates = [r["match_rate"] for r in rows]
    avg = sum(rates) / len(rates) if rates else 0.0
    print("-" * 70)
    print(f"全平均 一致率 = {avg:.3f}  ({_label(avg)})")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))


def _label(r):
    return "good (>=0.7)" if r >= 0.7 else ("acceptable (>=0.5)" if r >= 0.5 else "poor (<0.5)")


if __name__ == "__main__":
    main()
