import base64
import json

import httpx

from config import settings

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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


class OcrError(Exception):
    """Raised when the OCR/extraction provider cannot be reached or returns an error."""


# Empirically, asking Gemini to read a whole large batch (~27+ pages) in a single
# request causes it to degenerate into repeating garbage tokens instead of real data
# (confirmed by testing against a real 27-page batch deed - 8 pages in one call
# produced clean results, 27 pages in one call did not). Splitting into small chunks
# and merging the results client-side keeps each individual call well within whatever
# limit causes that breakdown.
PAGES_PER_CHUNK = 8


def extract_title_deed(files: list[tuple[bytes, str | None]]) -> dict:
    """Sends 1+ scanned pages (in the given order) to Gemini (Google AI Studio) and asks
    it to return the title-deed sections as structured JSON. The pages may be a single
    地號/建號's title deed, or a batch covering many parcels/buildings - either shape is
    returned as land_parcels/buildings arrays. Large page counts are processed in
    chunks of PAGES_PER_CHUNK and merged (by parcel_number / building_number) to avoid
    per-request quality breakdown. Every field is a suggestion for the user to review
    before saving, not an authoritative value."""
    if not settings.GEMINI_API_KEY:
        raise OcrError("尚未設定 GEMINI_API_KEY,請聯絡系統管理員設定 OCR 金鑰後再試")
    if not files:
        raise OcrError("沒有可供辨識的檔案")

    chunks = [files[i : i + PAGES_PER_CHUNK] for i in range(0, len(files), PAGES_PER_CHUNK)]
    results = [_extract_title_deed_chunk(chunk) for chunk in chunks]
    if len(results) == 1:
        return results[0]
    return _merge_extractions(results)


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


def _extract_title_deed_chunk(files: list[tuple[bytes, str | None]]) -> dict:
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

    # A single chunk occasionally times out under load even though most complete well
    # under a minute - retry once before giving up rather than failing the whole
    # (possibly multi-chunk) job over one slow call.
    for attempt in (1, 2):
        try:
            resp = httpx.post(url, params={"key": settings.GEMINI_API_KEY}, json=payload, timeout=240.0)
            resp.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise OcrError(f"呼叫 Gemini 服務失敗:{detail}") from exc
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise OcrError(f"呼叫 Gemini 服務失敗:{exc}") from exc

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise OcrError(f"Gemini 未回傳結果{'(原因:' + block_reason + ')' if block_reason else ''}")

    response_parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in response_parts)
    if not text:
        raise OcrError("Gemini 回傳內容為空")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OcrError(f"無法解析 Gemini 回傳的 JSON:{exc}") from exc

    return {
        "land_parcels": parsed.get("land_parcels") or [],
        "encumbrances": parsed.get("encumbrances") or [],
        "buildings": parsed.get("buildings") or [],
    }
