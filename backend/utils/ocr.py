import base64
import json

import httpx

from config import settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

EXTRACTION_PROMPT = """你是台灣地政士助理。請閱讀這張土地登記謄本(所有權個人全部)圖片,只擷取「土地標示部」與「土地所有權部」中\
第一位所有權人(自然人)的資料,不要讀取「土地他項權利部」的抵押權人/金融機構資料。

依照提供的 JSON schema 回傳結果:
- name:所有權人姓名
- id_number:所有權人的統一編號(身分證字號)
- address:所有權人的住址
- parcel_number:地號(例如 1099-0000)
- section:段名,不含行政區前綴(例如「民族段」而非「板橋區民族段」)
- total_area_sqm:土地標示部的面積(平方公尺),純數字
- ownership_numerator:權利範圍的分子(例如「10000000分之10364」中的 10364)
- ownership_denominator:權利範圍的分母(例如「10000000分之10364」中的 10000000)
- raw_text:整份文件辨識出的完整文字,供人工複核使用

找不到或看不清楚的欄位請填 null,不要用臆測值填補。"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING", "nullable": True},
        "id_number": {"type": "STRING", "nullable": True},
        "address": {"type": "STRING", "nullable": True},
        "parcel_number": {"type": "STRING", "nullable": True},
        "section": {"type": "STRING", "nullable": True},
        "total_area_sqm": {"type": "NUMBER", "nullable": True},
        "ownership_numerator": {"type": "INTEGER", "nullable": True},
        "ownership_denominator": {"type": "INTEGER", "nullable": True},
        "raw_text": {"type": "STRING", "nullable": True},
    },
    "required": [
        "name", "id_number", "address", "parcel_number", "section",
        "total_area_sqm", "ownership_numerator", "ownership_denominator", "raw_text",
    ],
}


class OcrError(Exception):
    """Raised when the OCR/extraction provider cannot be reached or returns an error."""


def extract_land_title_fields(image_bytes: bytes, mime_type: str | None) -> dict:
    """Sends the scanned 土地登記謄本 image to Gemini (Google AI Studio) and asks it to
    return the fields needed to pre-fill the 新增地主 form directly as JSON, so no
    separate regex parsing step is needed. Every field is a suggestion for the user
    to review before saving, not an authoritative value."""
    if not settings.GEMINI_API_KEY:
        raise OcrError("尚未設定 GEMINI_API_KEY,請聯絡系統管理員設定 OCR 金鑰後再試")

    url = GEMINI_ENDPOINT.format(model=settings.GEMINI_MODEL)
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": EXTRACTION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type or "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }

    try:
        resp = httpx.post(url, params={"key": settings.GEMINI_API_KEY}, json=payload, timeout=60.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        try:
            detail = exc.response.json().get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise OcrError(f"呼叫 Gemini 服務失敗:{detail}") from exc
    except httpx.HTTPError as exc:
        raise OcrError(f"呼叫 Gemini 服務失敗:{exc}") from exc

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise OcrError(f"Gemini 未回傳結果{'(原因:' + block_reason + ')' if block_reason else ''}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise OcrError("Gemini 回傳內容為空")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OcrError(f"無法解析 Gemini 回傳的 JSON:{exc}") from exc

    return {
        "name": parsed.get("name") or None,
        "id_number": parsed.get("id_number") or None,
        "address": parsed.get("address") or None,
        "parcel_number": parsed.get("parcel_number") or None,
        "section": parsed.get("section") or None,
        "total_area_sqm": parsed.get("total_area_sqm"),
        "ownership_numerator": parsed.get("ownership_numerator"),
        "ownership_denominator": parsed.get("ownership_denominator"),
        "raw_text": parsed.get("raw_text") or None,
    }
