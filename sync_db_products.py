"""DB の products シートに流し込む CSV を生成する。

lip API 側の products_with_lab.csv(Lab 抽出済み)+ catalog_x20.derive_x20 の
派生値から、DB products シートの列構成(A〜W)に合わせた CSV を出力する。

DB products の列(色ごとの 9 軸を保持。11 のライン軸は lines シート側):
  A id, B brand, C line_id, D color_no, E color_name, F image_url,
  G pattern_id, H pattern_url, I pc_season, J review_count,
  K L, L a, M b,                         ← Lab(CSV から)
  N hue, O saturation, P brightness, Q pigmentation,  ← 派生(derive_x20[0..3])
  R girly, S makeup_intensity, T konare, U sweetness, V korean,  ← 派生(derive_x20[15..19])
  W notes

使い方:
  .venv/bin/python sync_db_products.py
  → db_products_filled.csv が出力される
  → Google Sheets の products シート(2行目以降)に貼り付け
"""

from __future__ import annotations

import csv
import os

from catalog_x20 import derive_x20

SRC = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")
OUT = os.path.join(os.path.dirname(__file__), "db_products_filled.csv")

# DB products シートのヘッダー(A〜W、正確な順序)
DB_HEADER = [
    "id", "brand", "line_id", "color_no", "color_name", "image_url",
    "pattern_id", "pattern_url", "pc_season", "review_count",
    "L", "a", "b",
    "hue", "saturation", "brightness", "pigmentation",
    "girly", "makeup_intensity", "konare", "sweetness", "korean",
    "notes",
]

# derive_x20 の出力(20軸)のうち、products に入る 9 軸のインデックス
# [hue=0, saturation=1, brightness=2, pigmentation=3, girly=15,
#  makeup_intensity=16, konare=17, sweetness=18, korean=19]
PER_COLOR_IDX = {
    "hue": 0, "saturation": 1, "brightness": 2, "pigmentation": 3,
    "girly": 15, "makeup_intensity": 16, "konare": 17, "sweetness": 18, "korean": 19,
}


def main() -> None:
    with open(SRC, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    skipped = 0
    for r in rows:
        if r.get("status") == "excluded":
            skipped += 1
            continue
        try:
            L = float(r["L"]); a = float(r["a"]); b = float(r["b"])
        except (KeyError, ValueError, TypeError):
            skipped += 1
            continue

        x20 = derive_x20(r)

        def ax(name: str) -> str:
            return f"{x20[PER_COLOR_IDX[name]]:.4f}"

        out_rows.append({
            "id": r.get("id", ""),
            "brand": r.get("brand", "rom&nd"),
            "line_id": r.get("line_id", ""),
            "color_no": r.get("color_no", ""),
            "color_name": r.get("color_name", ""),
            "image_url": r.get("image_url", ""),
            "pattern_id": r.get("pattern_id", ""),
            "pattern_url": r.get("pattern_url", ""),
            "pc_season": r.get("pc_season", ""),
            "review_count": r.get("review_count", ""),
            "L": f"{L:.2f}", "a": f"{a:.2f}", "b": f"{b:.2f}",
            "hue": ax("hue"), "saturation": ax("saturation"),
            "brightness": ax("brightness"), "pigmentation": ax("pigmentation"),
            "girly": ax("girly"), "makeup_intensity": ax("makeup_intensity"),
            "konare": ax("konare"), "sweetness": ax("sweetness"),
            "korean": ax("korean"),
            "notes": r.get("notes", ""),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_HEADER)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"✅ DB products 形式で {len(out_rows)} 商品を出力: {OUT}")
    print(f"   (excluded/Lab欠損 {skipped} 件はスキップ)")
    print("   → Google Sheets の products シート 2 行目以降に貼り付け")
    print("   ※ 11 のライン軸(glossy 等)は lines シート側、ここには含めない")


if __name__ == "__main__":
    main()
