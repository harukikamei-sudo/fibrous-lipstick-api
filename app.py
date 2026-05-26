"""Fibrous Lipstick API (FastAPI)

エンドポイント:
  GET  /                       — サービス情報
  GET  /health                 — ヘルスチェック
  POST /extract_lab            — 単発: 画像URL → Lab
  POST /extract_lab_batch      — 一括: products 配列 → Lab 配列
  POST /estimate_s             — ライン S 推定(雛形、501)
  POST /compute_km_table       — K-M バッチ計算(雛形、501)

ローカル起動:
  uvicorn app:app --reload
"""

import ipaddress
import socket
from io import BytesIO
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

import extract_lab as el
import estimate_s as es  # 雛形
import km  # 雛形


# ============ 設定 ============

MAX_BATCH_SIZE = 50
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
REQUEST_TIMEOUT_SEC = 30


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
        ],
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


@app.post("/estimate_s")
def estimate_s_endpoint(req: dict):
    raise HTTPException(
        status_code=501,
        detail="Not implemented yet (phase: estimate_s)",
    )


@app.post("/compute_km_table")
def compute_km_table_endpoint(req: dict):
    raise HTTPException(
        status_code=501,
        detail="Not implemented yet (phase: compute_km_table)",
    )
