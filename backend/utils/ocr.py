import base64
import json

import fitz
import httpx

from config import settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OLLAMA_CHAT_ENDPOINT = "{base_url}/api/chat"

EXTRACTION_PROMPT = """你是台灣地政士助理。使用者會依序提供 1 到多張圖片或 PDF,這些是同一份謄本文件的連續頁面。\
這份文件可能是「單一地號/建號」的謄本,也可能是「批次謄本」——同一份文件裡連續印著好幾筆不同地號、好幾筆不同建號\
(例如信義區祥和段三小段0242-0000、0250-0000...等多筆地號依序印在同一份 PDF 裡),每筆地號/建號底下又可能有一長串\
繼承共有人(常見一筆地號有 10 位以上所有權人,分散在好幾頁)。請通盤閱讀所有頁面後,依照提供的 JSON schema 回傳結構化\
結果。

重要規則:
- 文件中每出現一次新的地號標題(例如「XX段XX小段0242-0000地號」),就代表開始一筆新的土地資料,請在 land_parcels \
陣列中新增一個項目,不要把不同地號的欄位混在一起。同一地號底下不論分幾頁列出多少位共有人,都要收進同一筆地號項目的 \
owners 陣列裡,不可遺漏任何一位。
- 同樣地,每出現一次新的建號標題,就在 buildings 陣列中新增一個項目,建物所有權人的收錄規則同上。
- 登記次序請填「登記次序:」後面的實際值(例如「0002」),不要填每筆記錄前面括號內的流水編號(例如「(0001)」),\
這兩者不是同一個東西。
- 面積、地價、權利範圍等數字或分數欄位前後常有 * 字元作為版面對齊填充(例如「****134.00平方公尺」、\
「**********4分之1**********」),這些 * 不是資料的一部分,請忽略,只填實際的數字/文字內容。
- 他項權利部(抵押權等)不分屬哪個地號/建號,一律收錄進最外層的 encumbrances 陣列,並在 applies_to_parcels \
欄位依原文寫出對應的地號/建號(可能是單一筆、多筆、或「全部」)。

1. land_parcels(土地標示部+所有權部,陣列,一筆地號一個項目;若整份文件完全沒有土地部分則回傳空陣列 []):
   - township:鄉鎮市區(例如「板橋區」)
   - section:地段名稱,不含行政區前綴(例如「民族段」而非「板橋區民族段」)
   - subsection:小段名稱(若有才填,很多謄本沒有小段)
   - parcel_number:地號(例如「1099-0000」)
   - area_sqm:土地標示部登載的面積(平方公尺),純數字
   - owners(陣列,**列出這筆地號底下所有登記次序/所有權人,不要只列第一位**):
     - registration_order:登記次序(例如「0157」)
     - owner_name:所有權人姓名
     - id_number:所有權人統一編號(身分證字號)
     - ownership_numerator:權利範圍分子(例如「10000000分之10364」中的 10364)
     - ownership_denominator:權利範圍分母(例如「10000000分之10364」中的 10000000)
     - address:所有權人戶籍地址

2. encumbrances(他項權利部,陣列,可能有 0 到多筆;沒有的話回傳空陣列 []):
   - registration_order:登記次序
   - applies_to_parcels:這筆他項權利對應到的地號/建號(可能是單一筆、多筆、或「全部」,依文件原文填寫)
   - right_type:權利種類(例如「最高限額抵押權」)
   - right_holder:他項權利人(例如銀行名稱)
   - debtor_info:債務人及債務額比例(把文件上寫的內容原文整理成一段文字)

3. buildings(建物標示部+所有權部,陣列,一筆建號一個項目;若整份文件完全沒有建物部分則回傳空陣列 []):
   - building_number:建號
   - building_address:建號門牌(建物門牌地址)
   - parcel_number:建物坐落地號
   - total_floors:層數(依文件原文,例如「地上10層」)
   - floor:層次(這筆建物標示部所在的樓層,例如「三層」)
   - total_area_sqm:建物總面積(平方公尺),純數字
   - floor_area_sqm:層次面積(平方公尺,該樓層/主建物本身的面積),純數字
   - owners(陣列,若這筆建物沒有所有權部則回傳空陣列 []):
     - registration_order:登記次序
     - owner_name:所有權人姓名
     - ownership_numerator:權利範圍分子
     - ownership_denominator:權利範圍分母
     - address:所有權人戶籍地址

找不到、看不清楚、或文件上沒有的欄位一律填 null(陣列則填空陣列 []),絕對不要用臆測值填補。"""

LAND_OWNER_ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "registration_order": {"type": "STRING", "nullable": True},
        "owner_name": {"type": "STRING", "nullable": True},
        "id_number": {"type": "STRING", "nullable": True},
        "ownership_numerator": {"type": "INTEGER", "nullable": True},
        "ownership_denominator": {"type": "INTEGER", "nullable": True},
        "address": {"type": "STRING", "nullable": True},
    },
}

BUILDING_OWNER_ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "registration_order": {"type": "STRING", "nullable": True},
        "owner_name": {"type": "STRING", "nullable": True},
        "ownership_numerator": {"type": "INTEGER", "nullable": True},
        "ownership_denominator": {"type": "INTEGER", "nullable": True},
        "address": {"type": "STRING", "nullable": True},
    },
}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "land_parcels": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "township": {"type": "STRING", "nullable": True},
                    "section": {"type": "STRING", "nullable": True},
                    "subsection": {"type": "STRING", "nullable": True},
                    "parcel_number": {"type": "STRING", "nullable": True},
                    "area_sqm": {"type": "NUMBER", "nullable": True},
                    "owners": {"type": "ARRAY", "items": LAND_OWNER_ITEM_SCHEMA},
                },
            },
        },
        "encumbrances": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "registration_order": {"type": "STRING", "nullable": True},
                    "applies_to_parcels": {"type": "STRING", "nullable": True},
                    "right_type": {"type": "STRING", "nullable": True},
                    "right_holder": {"type": "STRING", "nullable": True},
                    "debtor_info": {"type": "STRING", "nullable": True},
                },
            },
        },
        "buildings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "building_number": {"type": "STRING", "nullable": True},
                    "building_address": {"type": "STRING", "nullable": True},
                    "parcel_number": {"type": "STRING", "nullable": True},
                    "total_floors": {"type": "STRING", "nullable": True},
                    "floor": {"type": "STRING", "nullable": True},
                    "total_area_sqm": {"type": "NUMBER", "nullable": True},
                    "floor_area_sqm": {"type": "NUMBER", "nullable": True},
                    "owners": {"type": "ARRAY", "items": BUILDING_OWNER_ITEM_SCHEMA},
                },
            },
        },
    },
    "required": ["land_parcels", "encumbrances", "buildings"],
}


def _n(json_type: str) -> dict:
    """A nullable field in standard JSON Schema (Ollama's structured-output dialect) -
    unlike Gemini's OpenAPI-subset schema above which uses `"nullable": True`."""
    return {"type": [json_type, "null"]}


_OLLAMA_LAND_OWNER_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "registration_order": _n("string"),
        "owner_name": _n("string"),
        "id_number": _n("string"),
        "ownership_numerator": _n("integer"),
        "ownership_denominator": _n("integer"),
        "address": _n("string"),
    },
}

_OLLAMA_BUILDING_OWNER_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "registration_order": _n("string"),
        "owner_name": _n("string"),
        "ownership_numerator": _n("integer"),
        "ownership_denominator": _n("integer"),
        "address": _n("string"),
    },
}

OLLAMA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "land_parcels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "township": _n("string"),
                    "section": _n("string"),
                    "subsection": _n("string"),
                    "parcel_number": _n("string"),
                    "area_sqm": _n("number"),
                    "owners": {"type": "array", "items": _OLLAMA_LAND_OWNER_ITEM_SCHEMA},
                },
            },
        },
        "encumbrances": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "registration_order": _n("string"),
                    "applies_to_parcels": _n("string"),
                    "right_type": _n("string"),
                    "right_holder": _n("string"),
                    "debtor_info": _n("string"),
                },
            },
        },
        "buildings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "building_number": _n("string"),
                    "building_address": _n("string"),
                    "parcel_number": _n("string"),
                    "total_floors": _n("string"),
                    "floor": _n("string"),
                    "total_area_sqm": _n("number"),
                    "floor_area_sqm": _n("number"),
                    "owners": {"type": "array", "items": _OLLAMA_BUILDING_OWNER_ITEM_SCHEMA},
                },
            },
        },
    },
    "required": ["land_parcels", "encumbrances", "buildings"],
}


class OcrError(Exception):
    """Raised when the OCR/extraction provider cannot be reached or returns an error."""


# Empirically, asking Gemini to read a whole large batch (~27+ pages) in a single
# request causes it to degenerate into repeating garbage tokens instead of real data
# (confirmed by testing against a real 27-page batch deed - 8 pages in one call
# produced clean results, 27 pages in one call did not). Splitting into small chunks
# and merging the results client-side keeps each individual call well within whatever
# limit causes that breakdown.
PAGES_PER_CHUNK = 8
# A local 7B-class vision model has much less capacity than Gemini Flash to reliably
# track multiple pages at once - one page per call keeps each call's job simple, and
# the same parcel/building merge logic below still stitches a multi-page owner list
# back together across calls.
OLLAMA_PAGES_PER_CHUNK = 1
PDF_RENDER_DPI = 200


def _expand_pdf_pages(content: bytes) -> list[tuple[bytes, str | None]]:
    """Splits a multi-page PDF into one page-image per page. Chunking has to operate on
    actual pages, not uploaded files - a single 27-page PDF is still just 1 "file", so
    without this a whole batch deed uploaded as one PDF would still be sent to Gemini in
    one request and hit the same quality breakdown chunking is meant to avoid."""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        pages = [(page.get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png"), "image/png") for page in doc]
    except Exception as exc:  # fitz raises its own exception types on malformed PDFs
        raise OcrError(f"無法讀取 PDF 檔案:{exc}") from exc
    if not pages:
        raise OcrError("PDF 檔案沒有任何頁面")
    return pages


def _flatten_to_pages(files: list[tuple[bytes, str | None]]) -> list[tuple[bytes, str | None]]:
    pages: list[tuple[bytes, str | None]] = []
    for content, mime_type in files:
        if (mime_type or "").lower() == "application/pdf" or content[:5] == b"%PDF-":
            pages.extend(_expand_pdf_pages(content))
        else:
            pages.append((content, mime_type))
    return pages


def extract_title_deed(files: list[tuple[bytes, str | None]]) -> tuple[dict, str | None]:
    """Sends 1+ scanned pages (in the given order) to Gemini (Google AI Studio) and asks
    it to return the title-deed sections as structured JSON. The pages may be a single
    地號/建號's title deed, or a batch covering many parcels/buildings - either shape is
    returned as land_parcels/buildings arrays. Multi-page PDFs are first split into
    per-page images, then large page counts are processed in chunks of PAGES_PER_CHUNK
    and merged (by parcel_number / building_number) to avoid per-request quality
    breakdown. Each chunk already retries once internally on failure; if a chunk still
    fails, the other chunks' results are kept and a warning is returned alongside the
    data instead of discarding everything. Returns (data, warning_message_or_None).
    Every field is a suggestion for the user to review before saving, not authoritative."""
    provider = settings.OCR_PROVIDER
    if provider == "gemini":
        if not settings.GEMINI_API_KEY:
            raise OcrError("尚未設定 GEMINI_API_KEY,請聯絡系統管理員設定 OCR 金鑰後再試")
        chunk_fn, pages_per_chunk = _extract_title_deed_chunk_gemini, PAGES_PER_CHUNK
    elif provider == "ollama":
        if not settings.OLLAMA_BASE_URL:
            raise OcrError("尚未設定 OLLAMA_BASE_URL,請聯絡系統管理員設定後再試")
        chunk_fn, pages_per_chunk = _extract_title_deed_chunk_ollama, OLLAMA_PAGES_PER_CHUNK
    else:
        raise OcrError(f"未知的 OCR_PROVIDER 設定:{provider}")
    if not files:
        raise OcrError("沒有可供辨識的檔案")

    pages = _flatten_to_pages(files)
    chunks = [pages[i : i + pages_per_chunk] for i in range(0, len(pages), pages_per_chunk)]

    results = []
    failed_chunks = []
    for i, chunk in enumerate(chunks):
        try:
            results.append(chunk_fn(chunk))
        except OcrError as exc:
            failed_chunks.append((i, exc))

    if not results:
        raise failed_chunks[0][1]

    warning = None
    if failed_chunks:
        ranges = [f"第 {i * pages_per_chunk + 1}-{i * pages_per_chunk + len(chunks[i])} 頁" for i, _ in failed_chunks]
        warning = f"{'、'.join(ranges)}辨識失敗,以下結果可能不完整,請仔細核對並視需要手動補充"

    data = results[0] if len(results) == 1 else _merge_extractions(results)
    data = _drop_empty_entries(data)
    return data, warning


def _drop_empty_entries(data: dict) -> dict:
    """Occasionally a chunk's response includes a degenerate entry - garbled text with
    no parcel_number/building_number and no owners. A real 地號/建號 always has at
    least one of those, so entries with neither carry no information and are almost
    certainly noise; drop them rather than showing the user empty junk cards."""
    data["land_parcels"] = [p for p in data["land_parcels"] if p.get("parcel_number") or p.get("owners")]
    data["buildings"] = [b for b in data["buildings"] if b.get("building_number") or b.get("owners")]
    return data


def _merge_extractions(chunk_results: list[dict]) -> dict:
    """Merges per-chunk extraction results, combining entries that share the same
    parcel_number / building_number (a single 地號/建號's owner list can span a chunk
    boundary) instead of producing duplicate entries."""

    def merge_group(items_key: str, id_field: str, owner_fields: tuple[str, ...]) -> list[dict]:
        by_id: dict[str, dict] = {}
        order: list[str] = []
        no_id: list[dict] = []
        for chunk in chunk_results:
            for item in chunk[items_key]:
                key = (item.get(id_field) or "").strip()
                if not key:
                    no_id.append(item)
                    continue
                if key not in by_id:
                    by_id[key] = {**item, "owners": list(item.get("owners") or [])}
                    order.append(key)
                else:
                    existing = by_id[key]
                    existing["owners"].extend(item.get("owners") or [])
                    for field in owner_fields:
                        if not existing.get(field) and item.get(field):
                            existing[field] = item[field]
        return [by_id[k] for k in order] + no_id

    land_parcels = merge_group("land_parcels", "parcel_number", ("township", "section", "subsection", "area_sqm"))
    buildings = merge_group(
        "buildings",
        "building_number",
        ("building_address", "parcel_number", "total_floors", "floor", "total_area_sqm", "floor_area_sqm"),
    )
    encumbrances = [e for chunk in chunk_results for e in chunk["encumbrances"]]
    return {"land_parcels": land_parcels, "encumbrances": encumbrances, "buildings": buildings}


def _extract_title_deed_chunk_gemini(files: list[tuple[bytes, str | None]]) -> dict:
    parts = [{"text": EXTRACTION_PROMPT}]
    for content, mime_type in files:
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type or "image/jpeg",
                    "data": base64.b64encode(content).decode("ascii"),
                }
            }
        )

    url = GEMINI_ENDPOINT.format(model=settings.GEMINI_MODEL)
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            # Batch title deeds can contain dozens of parcels/buildings, each with many
            # co-owners - the resulting JSON can be far larger than a single-parcel
            # extraction, so raise the cap to avoid a truncated (invalid) response.
            "maxOutputTokens": 65536,
        },
    }

    # A single chunk occasionally times out, or Gemini occasionally returns a
    # truncated/malformed response, under load even though most calls complete cleanly
    # well under a minute - retry the whole request once before giving up, rather than
    # failing the whole (possibly multi-chunk) job over one bad call.
    last_error: OcrError | None = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(url, params={"key": settings.GEMINI_API_KEY}, json=payload, timeout=240.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise OcrError(f"呼叫 Gemini 服務失敗:{detail}") from exc
        except httpx.HTTPError as exc:
            last_error = OcrError(f"呼叫 Gemini 服務失敗:{exc}")
            continue

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            last_error = OcrError(f"Gemini 未回傳結果{'(原因:' + block_reason + ')' if block_reason else ''}")
            continue

        response_parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in response_parts)
        if not text:
            last_error = OcrError("Gemini 回傳內容為空")
            continue

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = OcrError(f"無法解析 Gemini 回傳的 JSON:{exc}")
            continue

        return {
            "land_parcels": parsed.get("land_parcels") or [],
            "encumbrances": parsed.get("encumbrances") or [],
            "buildings": parsed.get("buildings") or [],
        }

    raise last_error


def _extract_title_deed_chunk_ollama(files: list[tuple[bytes, str | None]]) -> dict:
    url = OLLAMA_CHAT_ENDPOINT.format(base_url=settings.OLLAMA_BASE_URL.rstrip("/"))
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": EXTRACTION_PROMPT,
                "images": [base64.b64encode(content).decode("ascii") for content, _ in files],
            }
        ],
        "format": OLLAMA_RESPONSE_SCHEMA,
        "stream": False,
        "options": {
            # The long extraction prompt plus a full-page image's vision tokens
            # comfortably exceed Ollama's 4096-token default context window (measured
            # ~5300 tokens for one page), which otherwise fails with a 400 "exceeds
            # context size" error. num_predict also needs headroom - a deed page with
            # several owners easily produces a few hundred output tokens.
            "num_ctx": 16384,
            "num_predict": 4096,
        },
    }

    # Local inference on a laptop GPU is much slower and less predictable than a
    # hosted API - generous timeout, and the same retry-once-on-any-failure pattern
    # used for Gemini above.
    last_error: OcrError | None = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(url, json=payload, timeout=300.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("error", detail)
            except ValueError:
                pass
            last_error = OcrError(f"呼叫 Ollama 服務失敗:{detail}")
            continue
        except httpx.HTTPError as exc:
            last_error = OcrError(f"呼叫 Ollama 服務失敗(請確認 Ollama 已啟動且已下載 {settings.OLLAMA_MODEL} 模型):{exc}")
            continue

        data = resp.json()
        text = (data.get("message") or {}).get("content") or ""
        if not text:
            last_error = OcrError("Ollama 回傳內容為空")
            continue

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = OcrError(f"無法解析 Ollama 回傳的 JSON:{exc}")
            continue

        return {
            "land_parcels": parsed.get("land_parcels") or [],
            "encumbrances": parsed.get("encumbrances") or [],
            "buildings": parsed.get("buildings") or [],
        }

    raise last_error
