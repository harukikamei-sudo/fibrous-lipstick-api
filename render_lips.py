"""口紅を顔写真に合成して PNG 出力する(streamlit 不要)。

使い方:
  .venv/bin/python render_lips.py [顔写真パス]
  省略時は assets/lips/model.png を使う。

本番 API で TOP-N を取得し、各商品の effective_lab を唇に合成。
結果は ~/Desktop/lip_render/ に PNG 保存 + 一覧 HTML も作る。
"""
import os
import sys
import numpy as np
from PIL import Image
import requests

from ui_app import composite_lip, extract_lip_mask, measure_lip_lab, TEXTURE_BY_CATEGORY

API = "https://tamable-fibrous-lipstick-api.hf.space"
OUT = os.path.expanduser("~/Desktop/lip_render")
os.makedirs(OUT, exist_ok=True)


def main():
    photo = sys.argv[1] if len(sys.argv) > 1 else "assets/lips/model.png"
    photo = os.path.expanduser(photo)
    print(f"顔写真: {photo}", flush=True)

    rgb = np.asarray(Image.open(photo).convert("RGB"))
    if max(rgb.shape[:2]) > 800:
        im = Image.fromarray(rgb)
        r = 800 / max(im.size)
        im = im.resize((int(im.size[0]*r), int(im.size[1]*r)))
        rgb = np.asarray(im)

    print("唇マスク抽出中...", flush=True)
    alpha = extract_lip_mask(rgb)
    lip = measure_lip_lab(rgb, alpha)
    if lip is None:
        lip = (62.0, 22.0, 12.0)
    print(f"唇 Lab = L{lip[0]:.0f} a{lip[1]:.0f} b{lip[2]:.0f}", flush=True)

    # 元画像保存
    Image.fromarray(rgb).save(f"{OUT}/00_original.png")

    print("API で TOP-5 取得中...", flush=True)
    rec = requests.post(f"{API}/recommend", json={
        "lip_lab": {"L": lip[0], "a": lip[1], "b": lip[2]},
        "pc_season": "ブルベ夏",
        "t": 1.0,
        "top_n": 5,
    }, timeout=60).json()

    results = rec.get("results", [])
    print(f"TOP-{len(results)} 取得。合成中...", flush=True)

    cards = []
    for i, it in enumerate(results, 1):
        ap = it["applied_lab"]
        cat = it.get("line_category", "other")
        ts = TEXTURE_BY_CATEGORY.get(cat, 1.0)
        comp = composite_lip(rgb, alpha, (ap["L"], ap["a"], ap["b"]), texture_strength=ts)
        name = it.get("name", it["id"])
        fname = f"{i:02d}_{it['id']}.png"
        Image.fromarray(comp).save(f"{OUT}/{fname}")
        print(f"  #{i} {name} ({cat}) -> {fname}", flush=True)
        cards.append((i, name, it["id"], cat, fname))

    # 一覧 HTML
    html = ["<html><head><meta charset='utf-8'><style>",
            "body{font-family:sans-serif;background:#faf8f6;padding:20px}",
            ".grid{display:flex;flex-wrap:wrap;gap:16px}",
            ".card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px;width:240px}",
            ".card img{width:100%;border-radius:4px}",
            "</style></head><body><h2>口紅合成 TOP-5</h2>",
            "<div class='grid'>",
            "<div class='card'><img src='00_original.png'><div>元画像</div></div>"]
    for i, name, pid, cat, fname in cards:
        html.append(f"<div class='card'><img src='{fname}'>"
                     f"<div><b>#{i} {name}</b><br>{cat}</div></div>")
    html.append("</div></body></html>")
    with open(f"{OUT}/index.html", "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"\n✅ 完了: {OUT}/index.html をブラウザで開く", flush=True)
    print(f"   (個別PNG も {OUT}/ に保存済み)", flush=True)


if __name__ == "__main__":
    main()
