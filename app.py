"""Fibrous Lipstick API (FastAPI)

エンドポイント:
  GET  /                       — サービス情報
  GET  /health                 — ヘルスチェック
  POST /extract_lab            — 単発: 画像URL → Lab
  POST /extract_lab_batch      — 一括: products 配列 → Lab 配列
  POST /estimate_s             — ライン S 逆推定(full+light Lab → S)
  POST /compute_km_table       — K-M 計算。2 モード:
                                   単品 (product_lab + line_category) /
                                   バッチ (products[+lines]) → 厚み21段の applied Lab
  POST /recommend              — 唇色(+PC) → 全商品 applied_lab → ΔE / PCスコアで推薦
  POST /evaluate               — PC連携の妥当性: 予測 TOP-N と カタログ PC タグの一致率

ローカル起動:
  uvicorn app:app --reload
"""

import csv
import ipaddress
import math
import os
import socket
from io import BytesIO
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse

import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator
from skimage import color as skcolor

import extract_lab as el
import estimate_s as es  # 雛形
import km  # 雛形

# ---- 設計書 v1.3 拡張 ----
import bayesian
import pair_compare as pc_mod
import recommend_v2 as rec_v2
from catalog_x20 import load_x20_from_row
from models_v13 import (
    KMTableRow,
    LabValue as LabValueV13,
    PairApplyRequest,
    PairApplyResponse,
    PairInitResponse,
    RecommendV2Request,
    RecommendV2Response,
    UpdateUserRequest,
    UpdateUserResponse,
)


# ============ 設定 ============

MAX_BATCH_SIZE = 50
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
REQUEST_TIMEOUT_SEC = 30

# /recommend 用の商品カタログ(Lab 抽出済み)
CATALOG_PATH = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")


def _parse_pc_tags(s: str) -> List[str]:
    """'イエベ春,ブルベ夏' のようなカンマ区切りタグを正規化リスト化。"""
    if not s:
        return []
    return [tok.strip() for tok in s.split(",") if tok.strip()]


def _load_catalog() -> List[Dict]:
    """products_with_lab.csv を読み、Lab 抽出済み(非 excluded)の商品リストを返す。"""
    items: List[Dict] = []
    if not os.path.exists(CATALOG_PATH):
        return items
    with open(CATALOG_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") == "excluded":
                continue
            try:
                lab = (float(row["L"]), float(row["a"]), float(row["b"]))
            except (KeyError, ValueError, TypeError):
                continue
            line_id = row.get("line_id", "")
            items.append({
                "id": row.get("id", ""),
                "name": row.get("color_name", ""),
                "line_id": line_id,
                "line_category": row.get("line_category")
                or km.classify_line_category(line_id),
                "lab": lab,
                # ★PC 連携用: カタログのタグは「答え合わせ用」として保持。
                # 推奨ロジックでは使わない(参考表示のみ)。
                "pc_tags": _parse_pc_tags(row.get("pc_season", "")),
                # v1.3: 20次元 pref ベクトル(機能15 + 世界観5)
                "x20": load_x20_from_row(row),
            })
    return items


CATALOG = _load_catalog()


app = FastAPI(title="Fibrous Lipstick API", version="0.1.0")

# CORS: MVP は全許可(ブラウザから Swagger UI 経由で叩けるように)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ============ Schemas ============

class ExtractLabRequest(BaseModel):
    image_url: str = Field(..., description="商品スウォッチ画像の URL")


class LabValue(BaseModel):
    L: float
    a: float
    b: float


class ExtractLabResponse(BaseModel):
    status: Literal["auto_high", "auto_low", "excluded"]
    lab: Optional[LabValue] = None
    notes: str


class BatchProduct(BaseModel):
    id: str
    image_url: str


class ExtractLabBatchRequest(BaseModel):
    products: List[BatchProduct] = Field(
        ...,
        max_length=MAX_BATCH_SIZE,
        description=f"最大{MAX_BATCH_SIZE}件",
    )


class ExtractLabBatchResponse(BaseModel):
    results: List[Dict]


# ---- K-M 系 ----

class EstimateSRequest(BaseModel):
    full_lab: LabValue = Field(..., description="フル発色の Lab(R∞ とみなす)")
    light_lab: LabValue = Field(..., description="t=t_light で観測した薄付き Lab")
    t_light: float = Field(0.3, gt=0.0, le=1.0, description="薄付きの厚み t")
    substrate_lab: Optional[LabValue] = Field(
        None, description="薄付き観測時の下地 Lab。省略時は白基板を仮定"
    )


class EstimateSResponse(BaseModel):
    s: List[float] = Field(..., description="ライン散乱係数 S(R,G,B チャネル)")
    k_s: List[float] = Field(..., description="商品 K/S 比(R,G,B チャネル)")


LineCategory = Literal["tint", "matte", "gloss", "velvet", "other"]


class KmBatchProduct(BaseModel):
    id: str
    L: Optional[float] = None
    a: Optional[float] = None
    b: Optional[float] = None
    k_s: Optional[List[float]] = Field(None, description="K/S 比。省略時は L/a/b から算出")
    line_id: Optional[str] = Field(None, description="lines の参照キー")
    line_category: Optional[LineCategory] = Field(None, description="S プリセット参照用")


class ComputeKmTableRequest(BaseModel):
    """単品モードとバッチモードの 2 通り。どちらか片方のみ指定する。

    - 単品モード: product_lab + line_category
    - バッチモード: products(+ 任意で lines)
    """
    lip_lab: LabValue = Field(..., description="唇地肌の Lab(下地)")

    # --- 単品モード ---
    product_lab: Optional[LabValue] = Field(None, description="商品フル発色 Lab(R∞)")
    line_category: Optional[LineCategory] = Field(None, description="仕上げタイプ")

    # --- バッチモード ---
    products: Optional[List[KmBatchProduct]] = Field(
        None, max_length=MAX_BATCH_SIZE, description=f"最大{MAX_BATCH_SIZE}件"
    )
    lines: Optional[Dict[str, List[float]]] = Field(
        None, description="{line_id: [S_R,S_G,S_B]}。省略時はプリセットにフォールバック"
    )

    t_steps: int = Field(21, ge=2, le=101, description="厚み段階数")

    @model_validator(mode="after")
    def _exactly_one_mode(self):
        single = self.product_lab is not None or self.line_category is not None
        batch = self.products is not None
        if single and batch:
            raise ValueError(
                "単品モード(product_lab/line_category)とバッチモード(products)は併用不可"
            )
        if not single and not batch:
            raise ValueError(
                "単品モード(product_lab+line_category)かバッチモード(products)のいずれかが必須"
            )
        if single and (self.product_lab is None or self.line_category is None):
            raise ValueError("単品モードでは product_lab と line_category の両方が必須")
        return self


class ComputeKmTableResponse(BaseModel):
    mode: str = Field(..., description="'single' か 'batch'")
    table: List[Dict] = Field(
        ...,
        description="各商品 {id, line_id, s, s_source, applied:[{t,L,a,b}, …]}",
    )


# ---- /recommend ----

PCSeasonLiteral = Literal["イエベ春", "イエベ秋", "ブルベ夏", "ブルベ冬"]


class RecommendRequest(BaseModel):
    lip_lab: LabValue = Field(..., description="唇地肌の Lab(下地)")
    t: float = Field(1.0, gt=0.0, le=5.0, description="塗り厚 t(塗り重ね量)")
    target_lab: Optional[LabValue] = Field(
        None, description="並べ替えの目標色。省略時は lip_lab(=最も自然/唇寄り)"
    )
    pc_season: Optional[PCSeasonLiteral] = Field(
        None,
        description="パーソナルカラー。指定時は applied_lab を PC 別 Lab 領域からの距離で"
                    "並べ替える(論文ベース)。カタログタグはロジックに使わず、参考表示のみ。"
    )
    line_category: Optional[LineCategory] = Field(
        None, description="仕上げタイプで絞り込み"
    )
    hue_min: Optional[float] = Field(None, description="applied の色相下限(0-360°)")
    hue_max: Optional[float] = Field(None, description="applied の色相上限(0-360°)")
    L_min: Optional[float] = Field(None, description="applied の明度下限")
    L_max: Optional[float] = Field(None, description="applied の明度上限")
    top_n: int = Field(5, ge=1, le=50, description="返す件数")


class RecommendItem(BaseModel):
    id: str
    name: str
    line_category: str
    original_lab: LabValue = Field(..., description="商品本来の発色 Lab")
    applied_lab: LabValue = Field(..., description="唇に厚み t で塗った後の Lab")
    applied_chroma: float = Field(..., description="applied_lab の彩度 C*=√(a²+b²)。清濁の判定軸")
    delta_e: float = Field(..., description="ソートに使った主スコア (PC指定時=pc_score 4D領域距離、それ以外=唇/目標色との ΔE2000)")
    pc_score: Optional[float] = Field(
        None, description="applied_lab と PC 別 Lab+C* 領域とのユークリッド距離(4軸)。指定時のみ"
    )
    delta_e_to_lip: float = Field(..., description="applied_lab と lip_lab の ΔE2000(CIEDE2000、参考)")
    catalog_pc_tags: List[str] = Field(
        default_factory=list,
        description="カタログ pc_season タグ(参考表示。推奨ロジックには未使用)"
    )


class RecommendResponse(BaseModel):
    count: int = Field(..., description="フィルタ後の候補数")
    catalog_size: int = Field(..., description="カタログ全体の件数")
    filter_method: str = Field(
        ..., description="'pc_season_target_region' / 'delta_e_to_target' / 'delta_e_to_lip'"
    )
    pc_season: Optional[str] = Field(None, description="指定された PC(あれば)")
    sort_target: LabValue = Field(..., description="並べ替えに使った目標色(PC指定時は領域中心の参考値)")
    results: List[RecommendItem]


# ---- /evaluate ----

class EvaluateRequest(BaseModel):
    lip_lab: LabValue
    expected_pc: PCSeasonLiteral
    t: float = Field(1.0, gt=0.0, le=5.0)
    top_n: int = Field(10, ge=1, le=50)


class EvaluateResponse(BaseModel):
    expected_pc: str
    top_n: int = Field(..., description="実際に評価できた件数(タグ付き商品で埋めた TOP_n)")
    matched_count: int = Field(..., description="catalog_pc_tags が expected_pc または "
                                                "'イエベ・ブルベ問わず' を含む件数")
    match_rate: float = Field(..., description="matched_count / top_n。タグ空商品は分母から除外済み")
    interpretation: str = Field(..., description="'good' (>=0.7) / 'acceptable' (>=0.5) / 'poor'")
    n_empty_tag_skipped: int = Field(
        0, description="TOP_n を埋めるために飛ばした「タグ空商品」の件数(透明性のため)"
    )
    details: List[Dict]


# ============ Helpers ============

def _validate_url(url: str) -> None:
    """URL の SSRF 検証。失敗時は HTTPException(400)。

    - scheme は http/https のみ
    - ホスト名を全 AAAA/A レコードに解決し、loopback / private /
      link-local / multicast / reserved のいずれかなら拒否
    """
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="URL 解析失敗")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL は http(s) のみ許可")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="ホスト名なし")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="ホスト名解決失敗")

    for af, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        # IPv6 の zone-id (例: fe80::1%eth0) を除去
        if "%" in ip_str:
            ip_str = ip_str.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(status_code=400, detail="内部 IP は許可されない")


def _fetch_image(url: str) -> Image.Image:
    """URL から画像を取得して PIL Image を返す。

    - SSRF 検証
    - stream で取得して MAX_IMAGE_BYTES を超えたら 413 で打ち切り
    - 失敗時は 400 / 413 / 408
    """
    _validate_url(url)

    try:
        res = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SEC,
            stream=True,
            headers={"User-Agent": "fibrous-lipstick-api"},
        )
        res.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"画像取得失敗: {e}")

    # Content-Length が宣言されていれば事前チェック
    content_length = res.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"画像サイズ超過(最大 {MAX_IMAGE_BYTES // (1024*1024)}MB)",
                )
        except ValueError:
            pass

    # ストリーミング読み込み(超えたら打ち切り)
    chunks = []
    total = 0
    try:
        for chunk in res.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"画像サイズ超過(最大 {MAX_IMAGE_BYTES // (1024*1024)}MB)",
                )
            chunks.append(chunk)
    finally:
        res.close()

    content = b"".join(chunks)

    try:
        return Image.open(BytesIO(content)).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"画像デコード失敗: {e}")


def _result_to_response(res: dict) -> ExtractLabResponse:
    status = el.classify_status(res)
    lab = None
    if res.get("L") is not None:
        lab = LabValue(L=res["L"], a=res["a"], b=res["b"])
    return ExtractLabResponse(status=status, lab=lab, notes=res["notes"])


# ============ Endpoints ============

@app.get("/")
def root():
    return {
        "service": "Fibrous Lipstick API",
        "version": "0.1.0",
        "endpoints": [
            "/extract_lab",
            "/extract_lab_batch",
            "/estimate_s",
            "/compute_km_table",
            "/recommend",
            "/evaluate",
            # v1.3 (Kawanoさん interface 提案・仮)
            "/v13/pair_compare/init",
            "/v13/pair_compare/apply",
            "/v13/update_user",
            "/v13/recommend",
        ],
        "catalog_size": len(CATALOG),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract_lab", response_model=ExtractLabResponse)
def extract_lab_endpoint(req: ExtractLabRequest):
    img = _fetch_image(req.image_url)
    res = el.extract_lab(img)
    return _result_to_response(res)


@app.post("/extract_lab_batch", response_model=ExtractLabBatchResponse)
def extract_lab_batch_endpoint(req: ExtractLabBatchRequest):
    results = []
    for p in req.products:
        try:
            img = _fetch_image(p.image_url)
            res = el.extract_lab(img)
            status = el.classify_status(res)
            results.append({
                "id": p.id,
                "status": status,
                "lab": (
                    {"L": res["L"], "a": res["a"], "b": res["b"]}
                    if res.get("L") is not None
                    else None
                ),
                "notes": res["notes"],
            })
        except HTTPException as e:
            results.append({
                "id": p.id,
                "status": "excluded",
                "lab": None,
                "notes": str(e.detail),
            })
        except Exception as e:
            results.append({
                "id": p.id,
                "status": "excluded",
                "lab": None,
                "notes": f"処理エラー: {e}",
            })
    return ExtractLabBatchResponse(results=results)


@app.post("/estimate_s", response_model=EstimateSResponse)
def estimate_s_endpoint(req: EstimateSRequest):
    full = [req.full_lab.L, req.full_lab.a, req.full_lab.b]
    light = [req.light_lab.L, req.light_lab.a, req.light_lab.b]
    substrate = (
        [req.substrate_lab.L, req.substrate_lab.a, req.substrate_lab.b]
        if req.substrate_lab is not None
        else None
    )
    s = es.estimate_s(full, light, t_light=req.t_light, substrate_lab=substrate)
    k_s = km.ks_from_lab(full)
    return EstimateSResponse(s=s.tolist(), k_s=k_s.tolist())


@app.post("/compute_km_table", response_model=ComputeKmTableResponse)
def compute_km_table_endpoint(req: ComputeKmTableRequest):
    lip_lab = [req.lip_lab.L, req.lip_lab.a, req.lip_lab.b]

    if req.products is not None:
        mode = "batch"
        products = [p.model_dump(exclude_none=True) for p in req.products]
    else:
        mode = "single"
        products = [{
            "id": "product",
            "L": req.product_lab.L,
            "a": req.product_lab.a,
            "b": req.product_lab.b,
            "line_category": req.line_category,
        }]

    try:
        table = km.compute_km_table(
            lip_lab, products, req.lines, t_steps=req.t_steps
        )
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"K-M 計算エラー: {e}")
    return ComputeKmTableResponse(mode=mode, table=table)


def _hue_deg(a: float, b: float) -> float:
    return math.degrees(math.atan2(b, a)) % 360.0


def _delta_e_ciede2000(lab1, lab2) -> float:
    """2 点の Lab 間の色差 ΔE(CIEDE2000)。

    CIEDE2000 は明度/彩度/色相の非線形重み付けを入れた perceptually-uniform な
    色差。ΔE76(単純ユークリッド)より人間の知覚に近く、化粧品/印刷の業界標準。
    skimage 実装に委譲。
    """
    a = np.asarray(lab1, dtype=float).reshape(1, 1, 3)
    b = np.asarray(lab2, dtype=float).reshape(1, 1, 3)
    return float(skcolor.deltaE_ciede2000(a, b)[0, 0])


def _hue_in_range(h: float, lo: Optional[float], hi: Optional[float]) -> bool:
    if lo is None and hi is None:
        return True
    lo = 0.0 if lo is None else lo
    hi = 360.0 if hi is None else hi
    if lo <= hi:
        return lo <= h <= hi
    return h >= lo or h <= hi  # 0°をまたぐ範囲(例 330〜30)


def _pc_region_center(pc_season: str) -> List[float]:
    """PC 領域の参考中心(L,a,b 範囲の中央)。sort_target 用の表示値。"""
    t = km.PC_LIPSTICK_TARGETS[pc_season]
    return [(t["L_range"][0] + t["L_range"][1]) / 2,
            (t["a_range"][0] + t["a_range"][1]) / 2,
            (t["b_range"][0] + t["b_range"][1]) / 2]


@app.post("/recommend", response_model=RecommendResponse)
def recommend_endpoint(req: RecommendRequest):
    if not CATALOG:
        raise HTTPException(status_code=503, detail="商品カタログが未ロード")

    lip = [req.lip_lab.L, req.lip_lab.a, req.lip_lab.b]
    has_pc = req.pc_season is not None
    has_target = req.target_lab is not None
    target = (
        [req.target_lab.L, req.target_lab.a, req.target_lab.b] if has_target
        else (_pc_region_center(req.pc_season) if has_pc else lip)
    )

    # ソートキー方式の決定: PC > 明示 target > 既定(唇に近い)
    if has_pc:
        filter_method = "pc_season_target_region"
    elif has_target:
        filter_method = "delta_e_to_target"
    else:
        filter_method = "delta_e_to_lip"

    scored = []
    for p in CATALOG:
        if req.line_category and p["line_category"] != req.line_category:
            continue
        ks = km.ks_from_lab(p["lab"])
        s, _ = km.resolve_line_s(line_id=p["line_id"],
                                 line_category=p["line_category"])
        applied = km.compute_applied_lab(lip, ks, s, req.t)
        aL, aa, ab = float(applied[0]), float(applied[1]), float(applied[2])

        # applied への色相 / 明度フィルタ
        if not _hue_in_range(_hue_deg(aa, ab), req.hue_min, req.hue_max):
            continue
        if req.L_min is not None and aL < req.L_min:
            continue
        if req.L_max is not None and aL > req.L_max:
            continue

        dE_lip = _delta_e_ciede2000([aL, aa, ab], lip)
        if has_pc:
            pc_score = km.compute_pc_score({"L": aL, "a": aa, "b": ab},
                                           req.pc_season)
            primary = pc_score
        else:
            pc_score = None
            primary = _delta_e_ciede2000([aL, aa, ab], target)
        scored.append((primary, pc_score, dE_lip, p, (aL, aa, ab)))

    scored.sort(key=lambda x: x[0])
    results = [
        RecommendItem(
            id=p["id"], name=p["name"], line_category=p["line_category"],
            original_lab=LabValue(L=p["lab"][0], a=p["lab"][1], b=p["lab"][2]),
            applied_lab=LabValue(L=round(aL, 2), a=round(aa, 2), b=round(ab, 2)),
            applied_chroma=round(km.compute_chroma({"L": aL, "a": aa, "b": ab}), 2),
            delta_e=round(primary, 2),
            pc_score=(round(pc_score, 2) if pc_score is not None else None),
            delta_e_to_lip=round(dE_lip, 2),
            catalog_pc_tags=list(p.get("pc_tags", [])),
        )
        for primary, pc_score, dE_lip, p, (aL, aa, ab) in scored[:req.top_n]
    ]
    return RecommendResponse(
        count=len(scored),
        catalog_size=len(CATALOG),
        filter_method=filter_method,
        pc_season=req.pc_season,
        sort_target=LabValue(L=target[0], a=target[1], b=target[2]),
        results=results,
    )


# ============ 設計書 v1.3 エンドポイント群 ============
# 設計方針:
#   - すべてステートレス。caller(Kawanoさん AR / GAS / 他バックエンド)が
#     UserState を保持し、リクエスト毎に丸ごと渡す。
#   - 永続化先(GAS/Spreadsheet/Firebase/SQLite 等)は caller の自由。
#   - データ形式は議論段階。Kawanoさん と相談して固める想定。

def _km_table_for_user(
    lip: List[float],
    line_category_filter: Optional[str],
) -> List[KMTableRow]:
    """全カタログ × 21 段(t=0.00 .. 1.00)の applied_Lab テーブル。

    in-memory ループ計算で十分高速(145 × 21 ≈ 3000 行)。
    caller が毎回送るより API 内部で生成する方が線が細い → 主軸。
    """
    rows: List[KMTableRow] = []
    for p in CATALOG:
        if line_category_filter and p["line_category"] != line_category_filter:
            continue
        ks = km.ks_from_lab(p["lab"])
        s, _ = km.resolve_line_s(line_id=p["line_id"],
                                 line_category=p["line_category"])
        applied: List[LabValueV13] = []
        for i in range(21):
            t = i / 20.0
            a = km.compute_applied_lab(lip, ks, s, t)
            applied.append(LabValueV13(
                L=float(a[0]), a=float(a[1]), b=float(a[2])
            ))
        rows.append(KMTableRow(
            product_id=p["id"],
            applied=applied,
            x20=list(p.get("x20", [0.0] * 20)),
            pc_tags=list(p.get("pc_tags", [])),
            name=p.get("name", ""),
            line_category=p.get("line_category", ""),
        ))
    return rows


@app.get("/v13/pair_compare/init", response_model=PairInitResponse)
def v13_pair_compare_init():
    """Part II 強制ペア比較の 10 ペアを返す。

    caller(Kawanoさん)はユーザーに各ペアの left/right を提示し、選択を集めて
    `/v13/pair_compare/apply` に送る。ペアの中身は MVP では仮データ。
    """
    return pc_mod.get_pair_bank()


@app.post("/v13/pair_compare/apply", response_model=PairApplyResponse)
def v13_pair_compare_apply(req: PairApplyRequest):
    """ペア選択 → θ_color/θ_pref/θ_explore/θ_thickness の初期事前分布。

    caller は返り値の 4 つの分布をそのまま users スプレッドシート等に保存し、
    以後のリクエストでは UserState の中に詰めて送る。
    """
    return pc_mod.apply_pair_choices(req)


@app.post("/v13/update_user", response_model=UpdateUserResponse)
def v13_update_user(req: UpdateUserRequest):
    """既存 user state + 新観測 → 更新後の user state を返す。

    観測ソース: pair_color / pair_worldview / dialog / behavior /
                ar_view_like / ar_view_dislike(設計書 §7.1)。
    caller は返り値の UserState で自前ストレージを上書き保存する。
    """
    new_user, n_applied = bayesian.apply_observations(req.user, req.observations)
    return UpdateUserResponse(user=new_user, n_applied=n_applied)


@app.post("/v13/recommend", response_model=RecommendV2Response)
def v13_recommend(req: RecommendV2Request):
    """設計書 Part IV/VI 統合スコアで TOP-N。

    入力: UserState のみで OK(km_table は省略可、内部で生成)。
    出力: 各商品の effective_Lab / f / familiarity / R_final 含む TOP-N。
    """
    if req.km_table is None:
        if not CATALOG:
            raise HTTPException(status_code=503, detail="商品カタログが未ロード")
        lip = [req.user.lip_lab.L, req.user.lip_lab.a, req.user.lip_lab.b]
        km_table = _km_table_for_user(lip, req.line_category)
    else:
        km_table = req.km_table

    # km_table をリクエストに詰め直して recommend_v2 を呼ぶ
    full_req = RecommendV2Request(
        user=req.user,
        km_table=km_table,
        line_category=req.line_category,
        top_n=req.top_n,
        alpha=req.alpha,
        beta_max=req.beta_max,
        familiarity_weights=req.familiarity_weights,
    )
    return rec_v2.recommend_v2(full_req)


def _interpret_match_rate(r: float) -> str:
    if r >= 0.7:
        return "good"
    if r >= 0.5:
        return "acceptable"
    return "poor"


@app.post("/evaluate", response_model=EvaluateResponse)
def evaluate_endpoint(req: EvaluateRequest):
    """予測(論文ベース)と カタログ PC タグの一致率を測る。

    pc_season=expected_pc で内部 /recommend → **タグ付き商品だけで TOP_n を埋める**
    (タグ空はスキップ。順位は下の商品で繰り上げ=バックフィル) → match_rate =
    matched / TOP_n。「サイト編集者がそもそも判定していない商品」を分母に含めない
    純粋精度。MVP 合格ライン 0.70。
    """
    # バッファ多めに取って空タグをスキップしつつ TOP_n を確保
    buffer_n = max(req.top_n * 4, 40)
    rec = recommend_endpoint(RecommendRequest(
        lip_lab=req.lip_lab,
        pc_season=req.expected_pc,
        t=req.t,
        top_n=buffer_n,
    ))
    tagged = [r for r in rec.results if r.catalog_pc_tags]
    selected = tagged[:req.top_n]

    # 飛ばした空タグ件数 = TOP_n を埋めるのに消費した位置 - len(selected)
    if selected:
        last_id = selected[-1].id
        last_pos = next(i for i, r in enumerate(rec.results) if r.id == last_id)
        n_skipped = (last_pos + 1) - len(selected)
    else:
        n_skipped = 0

    universal = "イエベ・ブルベ問わず"
    matched = 0
    details = []
    for r in selected:
        tags = r.catalog_pc_tags
        is_match = (req.expected_pc in tags) or (universal in tags)
        if is_match:
            matched += 1
        details.append({
            "id": r.id,
            "name": r.name,
            "line_category": r.line_category,
            "applied_lab": r.applied_lab.model_dump(),
            "applied_chroma": r.applied_chroma,
            "pc_score": r.pc_score,
            "catalog_pc_tags": tags,
            "match": is_match,
        })
    n = len(selected)
    rate = (matched / n) if n else 0.0
    return EvaluateResponse(
        expected_pc=req.expected_pc,
        top_n=n,
        matched_count=matched,
        match_rate=round(rate, 3),
        interpretation=_interpret_match_rate(rate),
        n_empty_tag_skipped=n_skipped,
        details=details,
    )
