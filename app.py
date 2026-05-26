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

from io import BytesIO
from typing import Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

import extract_lab as el
import estimate_s as es  # 雛形
import km  # 雛形


app = FastAPI(title="Fibrous Lipstick API", version="0.1.0")


# ============ Schemas ============

class ExtractLabRequest(BaseModel):
    image_url: str = Field(..., description="商品スウォッチ画像の URL")


class LabValue(BaseModel):
    L: float
    a: float
    b: float


class ExtractLabResponse(BaseModel):
    status: str  # "auto" | "excluded"
    lab: Optional[LabValue] = None
    notes: str


class BatchProduct(BaseModel):
    id: str
    image_url: str


class ExtractLabBatchRequest(BaseModel):
    products: List[BatchProduct]


class ExtractLabBatchResponse(BaseModel):
    results: List[Dict]


# ============ Helpers ============

def _fetch_image(url: str) -> Image.Image:
    """URL から画像を取得して PIL Image を返す。失敗時は HTTPException。"""
    try:
        res = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "fibrous-lipstick-api"},
        )
        res.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"画像取得失敗: {e}")
    try:
        return Image.open(BytesIO(res.content)).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"画像デコード失敗: {e}")


def _result_to_response(res: dict) -> ExtractLabResponse:
    lab = None
    if res["status"] == "auto" and res.get("L") is not None:
        lab = LabValue(L=res["L"], a=res["a"], b=res["b"])
    return ExtractLabResponse(status=res["status"], lab=lab, notes=res["notes"])


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
            results.append({
                "id": p.id,
                "status": res["status"],
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
