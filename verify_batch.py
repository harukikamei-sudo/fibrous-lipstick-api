"""145件を公開 API のバッチで処理 → CLI 版 products_with_lab.csv と比較。

products.csv を 50 件ずつ /extract_lab_batch に投げて、Lab と status を CSV と
照合する。許容誤差は L/a/b 各 0.5 (浮動小数 + 微小なクラスタ差を吸収)。
"""

import csv
import sys
import time

import requests

API_BASE = "https://tamable-fibrous-lipstick-api.hf.space"
# HF CPU basic は遅いので 50 件だと 5 分でも timeout 。小さめに刻む
BATCH_SIZE = 10
LAB_TOLERANCE = 0.5
REQUEST_TIMEOUT = 240


def call_batch(products):
    res = requests.post(
        API_BASE + "/extract_lab_batch",
        json={"products": products},
        timeout=REQUEST_TIMEOUT,
    )
    res.raise_for_status()
    return res.json()


def main():
    with open("products.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open("products_with_lab.csv", encoding="utf-8") as f:
        cli_rows = list(csv.DictReader(f))
    cli_by_id = {r["id"]: r for r in cli_rows}

    print(f"対象: {len(rows)} 件、バッチサイズ {BATCH_SIZE}")
    api_results = {}
    t0 = time.time()
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        products = [{"id": r["id"], "image_url": r["image_url"]} for r in chunk]
        t_chunk = time.time()
        data = call_batch(products)
        elapsed = time.time() - t_chunk
        print(
            f"  batch {start:>3}-{start+len(chunk)-1:>3} "
            f"({len(chunk)} 件) → {elapsed:.1f}s"
        )
        for r in data["results"]:
            api_results[r["id"]] = r

    total_elapsed = time.time() - t0
    print(f"\n合計時間: {total_elapsed:.1f}s ({total_elapsed/len(rows):.2f}s/件)")
    print(f"API 件数: {len(api_results)} / 期待 {len(rows)}")

    # 比較
    mismatches = []
    cli_status_counts = {}
    api_status_counts = {}
    for r in rows:
        pid = r["id"]
        cli = cli_by_id.get(pid, {})
        api = api_results.get(pid, {})

        cli_status = cli.get("status", "")
        api_status = api.get("status", "")
        cli_status_counts[cli_status] = cli_status_counts.get(cli_status, 0) + 1
        api_status_counts[api_status] = api_status_counts.get(api_status, 0) + 1

        if cli_status != api_status:
            mismatches.append((pid, "status", cli_status, api_status))
            continue

        # Lab 比較 (auto_high/auto_low のみ)
        if api_status in ("auto_high", "auto_low"):
            cli_lab = (cli.get("L"), cli.get("a"), cli.get("b"))
            api_lab_obj = api.get("lab") or {}
            api_lab = (
                api_lab_obj.get("L"),
                api_lab_obj.get("a"),
                api_lab_obj.get("b"),
            )
            for k, c, a in zip(("L", "a", "b"), cli_lab, api_lab):
                try:
                    c_f = float(c)
                    a_f = float(a)
                except (TypeError, ValueError):
                    mismatches.append((pid, f"lab.{k}", c, a))
                    continue
                if abs(c_f - a_f) > LAB_TOLERANCE:
                    mismatches.append((pid, f"lab.{k}", f"{c_f:.2f}", f"{a_f:.2f}"))

    print("\n=== status 件数 ===")
    print(f"  CLI: {cli_status_counts}")
    print(f"  API: {api_status_counts}")

    print(f"\n=== 不一致: {len(mismatches)} 件 ===")
    for m in mismatches[:50]:
        print(f"  {m[0]:<32} {m[1]:<10} CLI={m[2]:<15} API={m[3]}")
    if len(mismatches) > 50:
        print(f"  ...他 {len(mismatches) - 50} 件")

    if not mismatches:
        print("  → 完全一致 ✅")
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
