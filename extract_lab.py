"""
Lab 抽出スクリプト(口紅推奨ロジック MVP)

入力: products.csv(id, image_url 列を含む CSV)
出力:
  - products_with_lab.csv: id, ..., L, a, b, status, notes,
                            spatial_spread, bg_adjacency, aspect, is_container
  - excluded_list.csv: 除外商品の一覧
  - thumbnails/{id}.png: 採用色 + 候補色チップを並べたサムネイル

依存:
  pip install requests pillow numpy scipy scikit-image scikit-learn

使い方:
  1. 同じディレクトリに products.csv を置く
  2. python extract_lab.py
"""

import os
import csv
import time
import requests
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw
from sklearn.cluster import KMeans
from skimage import feature
from scipy.ndimage import binary_dilation

from lab_utils import (
    rgb_to_lab,
    compute_saturation,
    compute_hue_deg,
    is_red_hue,
)


# ============ 設定 ============

INPUT_CSV = "products.csv"
OUTPUT_CSV = "products_with_lab.csv"
EXCLUDED_CSV = "excluded_list.csv"
THUMB_DIR = "thumbnails"
IMAGE_DIR = "images_cache"

# スウォッチ判定の閾値
EDGE_DENSITY_MAX = 0.10       # 中央領域のエッジ密度がこれ未満 → スウォッチあり寄り
MAX_CLUSTER_RATIO_MIN = 0.25  # 最大クラスタが全体の何%以上か(均一性)
SATURATION_MIN = 0.25         # 採用クラスタの最低彩度(灰色を弾く)
PACKAGE_SIZE_RATIO_MAX = 0.15 # 採用クラスタの size_ratio がこれ未満なら容器のみ画像とみなす

# bg_adjacency / 形状特徴
BG_ADJACENCY_NEIGHBORHOOD = 3 # 背景に近接とみなす画素距離(dilation iterations)
CONTAINER_ASPECT_MIN = 1.5    # この値以上で縦長と判定
CONTAINER_V_EXTENT_MIN = 0.7  # 画像縦に対するクラスタ縦比率がこれ以上で容器疑い
CONTAINER_H_EXTENT_MAX = 0.4  # 画像横に対するクラスタ横比率がこれ未満で容器疑い
CONTAINER_PENALTY = 0.3       # 容器形状と判定されたクラスタの score 倍率

# auto_high 判定の閾値
AUTO_HIGH_EDGE_MAX = 0.05
AUTO_HIGH_SIZE_MIN = 0.30
AUTO_HIGH_ADJ_MIN = 0.10

# 画像処理
N_CLUSTERS = 6                # K-means クラスタ数
WHITE_THRESHOLD = 230         # この値以上を白背景とみなす(全チャネル)
BLACK_THRESHOLD = 60          # この値以下を黒背景とみなす(全チャネル)
MIN_CENTER_VALUE = 30         # クラスタ中心の最大チャネル値がこれ未満なら採用しない(黒背景クラスタ除外)
SLEEP_BETWEEN_FETCH = 0.5     # マナーとして

# デバッグ: 指定 id では全クラスタの詳細を出力
DEBUG_IDS = {
    "rmd_juicy_lasting_17",
    "rmd_the_juicy_lasting_16",
    "rmd_the_juicy_lasting_28",
}


# ============ ユーティリティ ============

def download_image(url, save_path):
    """画像をキャッシュ付きでダウンロード"""
    if os.path.exists(save_path):
        return Image.open(save_path).convert("RGB")

    time.sleep(SLEEP_BETWEEN_FETCH)
    res = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (research; lipstick-mvp)"
    })
    res.raise_for_status()

    img = Image.open(BytesIO(res.content)).convert("RGB")
    img.save(save_path)
    return img


def remove_extreme_pixels(arr):
    """白背景・黒背景を除外した画素配列と、元画像 (H*W) 上の保持マスクを返す。"""
    pixels = arr.reshape(-1, 3)
    white_mask = ~np.all(pixels >= WHITE_THRESHOLD, axis=1)
    black_mask = ~np.all(pixels <= BLACK_THRESHOLD, axis=1)
    keep_mask = white_mask & black_mask
    return pixels[keep_mask], keep_mask


def compute_edge_density(arr):
    """中央領域のエッジ密度を計算(0〜1)"""
    h, w = arr.shape[:2]
    cy0, cy1 = int(h * 0.3), int(h * 0.7)
    cx0, cx1 = int(w * 0.3), int(w * 0.7)
    center = arr[cy0:cy1, cx0:cx1]
    gray = np.mean(center, axis=2) / 255.0
    edges = feature.canny(gray, sigma=2.0)
    return edges.mean()


def compute_cluster_spreads(labels, keep_mask, h, w, n_clusters):
    """各クラスタの spatial_spread = sqrt(σx² + σy²) / sqrt(W² + H²)"""
    flat_indices = np.where(keep_mask)[0]
    ys = flat_indices // w
    xs = flat_indices % w
    diag = np.sqrt(w * w + h * h)
    spreads = np.zeros(n_clusters, dtype=float)
    for i in range(n_clusters):
        m = labels == i
        if m.sum() < 2:
            continue
        sigma_x = float(np.std(xs[m]))
        sigma_y = float(np.std(ys[m]))
        spreads[i] = float(np.sqrt(sigma_x ** 2 + sigma_y ** 2) / diag)
    return spreads


def compute_bg_adjacencies(arr, labels_2d, n_clusters, neighborhood=BG_ADJACENCY_NEIGHBORHOOD):
    """各クラスタの画素のうち、白 or 黒背景に neighborhood 画素以内で隣接する割合。

    A: 背景は白(>=WHITE_THRESHOLD)または黒(<=BLACK_THRESHOLD)
    C: morphological dilation で隣接判定を緩和(画素単位の厳密接触ではなく n 画素以内)
    """
    white_mask = np.all(arr >= WHITE_THRESHOLD, axis=2)
    black_mask = np.all(arr <= BLACK_THRESHOLD, axis=2)
    bg_mask = white_mask | black_mask
    bg_dilated = binary_dilation(bg_mask, iterations=neighborhood)

    adjs = np.zeros(n_clusters, dtype=float)
    for i in range(n_clusters):
        cluster_mask = (labels_2d == i)
        n = int(cluster_mask.sum())
        if n == 0:
            continue
        adjs[i] = float((cluster_mask & bg_dilated).sum()) / n
    return adjs


def compute_shape_features(labels_2d, n_clusters, h, w):
    """各クラスタの形状特徴: aspect, v_extent, h_extent, is_container を返す。

    縦長で画像縦をほぼ占有、横は狭い → リップ容器の典型形状
    """
    feats = []
    for i in range(n_clusters):
        m = (labels_2d == i)
        n = int(m.sum())
        if n < 2:
            feats.append({
                "aspect": 0.0, "v_extent": 0.0, "h_extent": 0.0,
                "is_container": False,
            })
            continue
        ys, xs = np.where(m)
        y_min, y_max = int(ys.min()), int(ys.max())
        x_min, x_max = int(xs.min()), int(xs.max())
        bbox_h = max(1, y_max - y_min)
        bbox_w = max(1, x_max - x_min)
        aspect = bbox_h / bbox_w
        v_extent = bbox_h / h
        h_extent = bbox_w / w
        is_container = (
            aspect > CONTAINER_ASPECT_MIN
            and v_extent > CONTAINER_V_EXTENT_MIN
            and h_extent < CONTAINER_H_EXTENT_MAX
        )
        feats.append({
            "aspect": float(aspect),
            "v_extent": float(v_extent),
            "h_extent": float(h_extent),
            "is_container": bool(is_container),
        })
    return feats


# ============ メイン処理 ============

def extract_lab(img, debug=False):
    """画像から Lab を抽出。戻り値は dict。"""
    arr = np.array(img)
    h, w = arr.shape[:2]

    edge_density = float(compute_edge_density(arr))

    pixels, keep_mask = remove_extreme_pixels(arr)
    if len(pixels) < 100:
        return {
            "status": "excluded",
            "L": None, "a": None, "b": None,
            "swatch_rgb": None,
            "sat": None, "hue": None, "size_ratio": None,
            "spread": None, "adj": None,
            "aspect": None, "v_extent": None, "h_extent": None, "is_container": None,
            "edge_density": edge_density,
            "notes": "ほぼ全画素が白or黒(取得失敗?)",
            "candidates": [],
            "all_clusters": [],
        }

    n_clusters = min(N_CLUSTERS, len(pixels))
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    km.fit(pixels)

    labels = km.labels_
    sizes = np.bincount(labels, minlength=n_clusters)
    total = int(sizes.sum())
    max_ratio = sizes.max() / total

    # 元画像 (H, W) スケールの labels (背景画素は -1)
    labels_full = np.full(h * w, -1, dtype=int)
    labels_full[keep_mask] = labels
    labels_2d = labels_full.reshape(h, w)

    spreads = compute_cluster_spreads(labels, keep_mask, h, w, n_clusters)
    adjs = compute_bg_adjacencies(arr, labels_2d, n_clusters)
    shapes = compute_shape_features(labels_2d, n_clusters, h, w)
    centers = km.cluster_centers_

    all_clusters = []
    for i, center in enumerate(centers):
        all_clusters.append({
            "cluster_id": int(i),
            "center": center,
            "rgb": tuple(int(v) for v in center),
            "sat": float(compute_saturation(center)),
            "hue": float(compute_hue_deg(center)),
            "size_ratio": float(sizes[i] / total),
            "spread": float(spreads[i]),
            "adj": float(adjs[i]),
            "aspect": shapes[i]["aspect"],
            "v_extent": shapes[i]["v_extent"],
            "h_extent": shapes[i]["h_extent"],
            "is_container": shapes[i]["is_container"],
            "score": None,
            "rejected_reason": None,
        })

    candidates = []
    for c in all_clusters:
        if c["center"].max() < MIN_CENTER_VALUE:
            c["rejected_reason"] = "黒系クラスタ"
            continue
        if c["sat"] < SATURATION_MIN:
            c["rejected_reason"] = f"sat<{SATURATION_MIN}"
            continue
        if not is_red_hue(c["hue"]):
            c["rejected_reason"] = "非赤系"
            continue
        if c["size_ratio"] < 0.05:
            c["rejected_reason"] = "size<0.05"
            continue
        penalty = CONTAINER_PENALTY if c["is_container"] else 1.0
        c["score"] = c["sat"] * c["size_ratio"] * (1.0 + c["adj"]) * penalty
        candidates.append(c)

    if debug:
        print(f"\n[DEBUG] clusters (全 {n_clusters} 個, edge={edge_density:.3f}):")
        for c in sorted(all_clusters, key=lambda x: -x["size_ratio"]):
            score_str = f"{c['score']:.3f}" if c["score"] is not None else "  -  "
            rej = c["rejected_reason"] or ""
            cflag = "C" if c["is_container"] else "."
            print(
                f"  cid={c['cluster_id']} RGB={c['rgb']} "
                f"sat={c['sat']:.2f} hue={c['hue']:>5.0f} "
                f"size={c['size_ratio']:.2f} spread={c['spread']:.3f} adj={c['adj']:.2f} "
                f"asp={c['aspect']:.2f} v={c['v_extent']:.2f} h={c['h_extent']:.2f} [{cflag}] "
                f"score={score_str} {rej}"
            )

    if not candidates:
        return {
            "status": "excluded",
            "L": None, "a": None, "b": None,
            "swatch_rgb": None,
            "sat": None, "hue": None, "size_ratio": None,
            "spread": None, "adj": None,
            "aspect": None, "v_extent": None, "h_extent": None, "is_container": None,
            "edge_density": edge_density,
            "notes": f"赤系の支配色なし(edge={edge_density:.2f}, max_ratio={max_ratio:.2f})",
            "candidates": [],
            "all_clusters": all_clusters,
        }

    candidates.sort(key=lambda c: -c["score"])
    chosen = candidates[0]

    if chosen["size_ratio"] < PACKAGE_SIZE_RATIO_MAX:
        return {
            "status": "excluded",
            "L": None, "a": None, "b": None,
            "swatch_rgb": chosen["center"],
            "sat": chosen["sat"], "hue": chosen["hue"],
            "size_ratio": chosen["size_ratio"],
            "spread": chosen["spread"], "adj": chosen["adj"],
            "aspect": chosen["aspect"], "v_extent": chosen["v_extent"],
            "h_extent": chosen["h_extent"], "is_container": chosen["is_container"],
            "edge_density": edge_density,
            "notes": (
                f"スウォッチ小(size={chosen['size_ratio']:.2f}, edge={edge_density:.2f}, "
                f"adj={chosen['adj']:.2f}): 容器のみ画像の疑い"
            ),
            "candidates": candidates[:3],
            "all_clusters": all_clusters,
        }

    lab = rgb_to_lab(chosen["center"])
    notes = (
        f"sat={chosen['sat']:.2f}, hue={chosen['hue']:.0f}°, "
        f"size={chosen['size_ratio']:.2f}, edge={edge_density:.2f}, "
        f"spread={chosen['spread']:.3f}, adj={chosen['adj']:.2f}, "
        f"aspect={chosen['aspect']:.2f}, container={chosen['is_container']}"
    )
    return {
        "status": "auto",
        "L": float(lab[0]), "a": float(lab[1]), "b": float(lab[2]),
        "swatch_rgb": chosen["center"],
        "sat": chosen["sat"], "hue": chosen["hue"],
        "size_ratio": chosen["size_ratio"],
        "spread": chosen["spread"], "adj": chosen["adj"],
        "aspect": chosen["aspect"], "v_extent": chosen["v_extent"],
        "h_extent": chosen["h_extent"], "is_container": chosen["is_container"],
        "edge_density": edge_density,
        "notes": notes,
        "candidates": candidates[:3],
        "all_clusters": all_clusters,
    }


def classify_status(res):
    """extract_lab() の結果を auto_high / auto_low / excluded に分類。

    CLI(main)と API(app.py)で同じロジックを使うため、ここに集約する。
    AUTO_HIGH_* 閾値は固定値(中央値計算なし)。
    """
    status = res.get("status")
    if status != "auto":
        return status

    edge_density = res.get("edge_density")
    if edge_density is None:
        return "auto_low"
    if not (edge_density < AUTO_HIGH_EDGE_MAX):
        return "auto_low"

    size_ratio = res.get("size_ratio")
    if size_ratio is None:
        return "auto_low"
    if not (size_ratio > AUTO_HIGH_SIZE_MIN):
        return "auto_low"

    adj = res.get("adj")
    if adj is None:
        return "auto_low"

    is_container = res.get("is_container", False)
    if not is_container:
        return "auto_high"

    if not (adj > AUTO_HIGH_ADJ_MIN):
        return "auto_low"

    return "auto_high"


def make_thumbnail(img, product_id, status, result):
    """元画像 + 採用色 + 候補2,3色チップを並べたサムネイル。"""
    thumb = img.copy()
    thumb.thumbnail((400, 400))

    right_w = 170
    canvas = Image.new("RGB", (thumb.width + right_w, max(thumb.height, 260)), "white")
    canvas.paste(thumb, (0, 0))
    draw = ImageDraw.Draw(canvas)

    x0 = thumb.width + 10
    cand = result.get("candidates") or []
    L, a, b = result.get("L"), result.get("a"), result.get("b")

    chosen_rgb = result.get("swatch_rgb")
    if chosen_rgb is not None:
        chip = tuple(int(c) for c in chosen_rgb)
        draw.rectangle([x0, 10, x0 + 80, 90], fill=chip, outline="black")

    for idx, c in enumerate(cand[1:3]):
        rgb = tuple(int(v) for v in c["center"])
        y = 10 + idx * 45
        draw.rectangle([x0 + 90, y, x0 + 130, y + 40], fill=rgb, outline="gray")

    text_y = 100
    if L is not None:
        draw.text((x0, text_y), f"L={L:.0f}\na={a:.0f}\nb={b:.0f}", fill="black")
        text_y += 50
    spread = result.get("spread")
    adj = result.get("adj")
    size_ratio = result.get("size_ratio")
    sat = result.get("sat")
    aspect = result.get("aspect")
    is_cont = result.get("is_container")
    if size_ratio is not None:
        draw.text(
            (x0, text_y),
            f"sat={sat:.2f}\nsize={size_ratio:.2f}\nspread={spread:.3f}\n"
            f"adj={adj:.2f}\nasp={aspect:.2f} {'C' if is_cont else '.'}",
            fill="dimgray",
        )

    color = {
        "auto_high": "darkgreen",
        "auto_low": "orange",
        "auto": "green",
        "excluded": "red",
    }.get(status, "black")
    draw.text((5, thumb.height - 18), status, fill=color)

    save_path = os.path.join(THUMB_DIR, f"{product_id}.png")
    canvas.save(save_path)


# ============ 実行 ============

def main():
    os.makedirs(THUMB_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)

    with open(INPUT_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"処理開始: {len(rows)} 件")

    results = []
    metas = []

    for i, row in enumerate(rows, 1):
        product_id = row["id"]
        image_url = row.get("image_url", "")

        if not image_url:
            results.append({**row, "L": "", "a": "", "b": "",
                            "status": "excluded", "notes": "image_url なし",
                            "spatial_spread": "", "bg_adjacency": "",
                            "aspect": "", "is_container": ""})
            metas.append(None)
            continue

        img_path = os.path.join(IMAGE_DIR, f"{product_id}.png")
        try:
            img = download_image(image_url, img_path)
        except Exception as e:
            print(f"[{i}/{len(rows)}] {product_id}: ダウンロード失敗 {e}")
            results.append({**row, "L": "", "a": "", "b": "",
                            "status": "excluded", "notes": f"DLエラー: {e}",
                            "spatial_spread": "", "bg_adjacency": "",
                            "aspect": "", "is_container": ""})
            metas.append(None)
            continue

        is_debug = product_id in DEBUG_IDS
        if is_debug:
            print(f"\n===== [DEBUG] {product_id} =====")
        try:
            res = extract_lab(img, debug=is_debug)
            make_thumbnail(img, product_id, res["status"], res)
        except Exception as e:
            res = {
                "status": "excluded",
                "L": None, "a": None, "b": None,
                "notes": f"処理エラー: {e}",
                "spread": None, "adj": None, "size_ratio": None,
                "aspect": None, "is_container": None, "edge_density": None,
            }

        L, a, b = res.get("L"), res.get("a"), res.get("b")
        spread = res.get("spread")
        adj = res.get("adj")
        aspect = res.get("aspect")
        is_cont = res.get("is_container")
        results.append({
            **row,
            "L": f"{L:.2f}" if L is not None else "",
            "a": f"{a:.2f}" if a is not None else "",
            "b": f"{b:.2f}" if b is not None else "",
            "status": res["status"],
            "notes": res["notes"],
            "spatial_spread": f"{spread:.4f}" if spread is not None else "",
            "bg_adjacency": f"{adj:.4f}" if adj is not None else "",
            "aspect": f"{aspect:.3f}" if aspect is not None else "",
            "is_container": "True" if is_cont else ("False" if is_cont is False else ""),
        })
        metas.append(res)

        if is_debug:
            print(f"[DEBUG] {product_id} 結果: status={res['status']} L={L} adj={adj} container={is_cont}")

        if i % 10 == 0 or i == len(rows):
            print(f"[{i}/{len(rows)}] {product_id}: {res['status']} - {res['notes']}")

    # auto_high / auto_low 判定 (classify_status を CLI/API で共有)
    for r, m in zip(results, metas):
        if r["status"] != "auto" or m is None:
            continue
        r["status"] = classify_status(m)

    # サムネイルを新 status で再描画
    for r, m in zip(results, metas):
        if m is None or r["status"] not in ("auto_high", "auto_low", "excluded"):
            continue
        try:
            img_path = os.path.join(IMAGE_DIR, f"{r['id']}.png")
            if os.path.exists(img_path):
                img = Image.open(img_path).convert("RGB")
                make_thumbnail(img, r["id"], r["status"], m)
        except Exception:
            pass

    excluded = [
        {"id": r["id"], "reason": r["notes"]}
        for r in results if r["status"] == "excluded"
    ]

    if results:
        keys = list(results[0].keys())
        with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)

    with open(EXCLUDED_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "reason"])
        writer.writeheader()
        writer.writerows(excluded)

    cnt = {"auto_high": 0, "auto_low": 0, "excluded": 0}
    for r in results:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    total = len(results)
    print("\n=== 完了 ===")
    print(f"auto_high : {cnt['auto_high']:>3} / {total} ({cnt['auto_high']*100/total:.1f}%)")
    print(f"auto_low  : {cnt['auto_low']:>3} / {total} ({cnt['auto_low']*100/total:.1f}%)")
    print(f"excluded  : {cnt['excluded']:>3} / {total} ({cnt['excluded']*100/total:.1f}%)")
    print(f"出力: {OUTPUT_CSV}, {EXCLUDED_CSV}, {THUMB_DIR}/")

    # 検証6件
    targets = [
        ("rmd_juicy_lasting_17", "誤抽出 → 期待: L≈30 or auto_low"),
        ("rmd_the_juicy_lasting_16", "誤抽出 → 期待: L≈40 or auto_low"),
        ("rmd_the_juicy_lasting_28", "誤抽出 → 期待: L≈70"),
        ("rmd_milktea_velvet_09", "ダーク赤 維持"),
        ("rmd_zero_velvet_01", "典型 維持"),
        ("rmd_glasting_water_09", "excluded 維持"),
    ]
    by_id = {r["id"]: r for r in results}
    print("\n=== 検証6件 ===")
    print(
        f"{'id':<32} {'status':<10} {'L':>6} {'a':>6} {'b':>6} "
        f"{'bg_adj':>6} {'asp':>5} {'cont':>5}  メモ"
    )
    for pid, note in targets:
        r = by_id.get(pid, {})
        print(
            f"{pid:<32} {r.get('status',''):<10} "
            f"{r.get('L',''):>6} {r.get('a',''):>6} {r.get('b',''):>6} "
            f"{r.get('bg_adjacency',''):>6} {r.get('aspect',''):>5} "
            f"{r.get('is_container',''):>5}  {note}"
        )

    # milktea_velvet_04 が excluded のまま維持されているか
    mt04 = by_id.get("rmd_milktea_velvet_04", {})
    print(f"\nrmd_milktea_velvet_04 (透明容器液体): status={mt04.get('status')} notes={mt04.get('notes')}")
    print(f"auto_high≥5 チェック: {cnt['auto_high']} 件 ({'OK' if cnt['auto_high']>=5 else 'NG'})")

    # ============ 追加サマリ ============
    print("\n=== status 別件数 ===")
    for k in ("auto_high", "auto_low", "excluded"):
        print(f"  {k:<10}: {cnt.get(k, 0):>3} / {total}")

    def _to_float(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    low_L = []
    high_L = []
    for r in results:
        Lv = _to_float(r.get("L", ""))
        if Lv is None:
            continue
        if Lv < 20:
            low_L.append((r["id"], Lv, r["status"]))
        elif Lv > 75:
            high_L.append((r["id"], Lv, r["status"]))

    print(f"\n=== L < 20 ({len(low_L)} 件) ===")
    for pid, Lv, st in sorted(low_L, key=lambda x: x[1]):
        print(f"  {pid:<32} L={Lv:>6.2f}  status={st}")

    print(f"\n=== L > 75 ({len(high_L)} 件) ===")
    for pid, Lv, st in sorted(high_L, key=lambda x: -x[1]):
        print(f"  {pid:<32} L={Lv:>6.2f}  status={st}")

    print("\n=== line_id 別 auto_high 通過率 ===")
    line_stats = {}
    for r in results:
        lid = r.get("line_id", "")
        line_stats.setdefault(lid, {"auto_high": 0, "auto_low": 0, "excluded": 0, "total": 0})
        line_stats[lid][r["status"]] = line_stats[lid].get(r["status"], 0) + 1
        line_stats[lid]["total"] += 1
    print(f"  {'line_id':<22} {'high':>5} {'low':>5} {'excl':>5} {'total':>5} {'high率':>7}")
    for lid in sorted(line_stats.keys()):
        s = line_stats[lid]
        rate = s["auto_high"] * 100 / s["total"] if s["total"] else 0
        print(
            f"  {lid:<22} {s['auto_high']:>5} {s['auto_low']:>5} "
            f"{s['excluded']:>5} {s['total']:>5} {rate:>6.1f}%"
        )


if __name__ == "__main__":
    main()
