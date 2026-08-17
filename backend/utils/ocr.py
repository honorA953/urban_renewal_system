import base64
import json
import time

import fitz
import httpx

from config import settings

OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

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


def _n(json_type: str) -> dict:
    """A nullable field in standard JSON Schema. OpenAI's structured-output "strict"
    mode requires every property (including ones that may be null) to appear in the
    object's "required" list - the type itself carries the nullability."""
    return {"type": [json_type, "null"]}


_LAND_OWNER_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "registration_order": _n("string"),
        "owner_name": _n("string"),
        "id_number": _n("string"),
        "ownership_numerator": _n("integer"),
        "ownership_denominator": _n("integer"),
        "address": _n("string"),
    },
    "required": ["registration_order", "owner_name", "id_number", "ownership_numerator", "ownership_denominator", "address"],
    "additionalProperties": False,
}

_BUILDING_OWNER_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "registration_order": _n("string"),
        "owner_name": _n("string"),
        "ownership_numerator": _n("integer"),
        "ownership_denominator": _n("integer"),
        "address": _n("string"),
    },
    "required": ["registration_order", "owner_name", "ownership_numerator", "ownership_denominator", "address"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
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
                    "owners": {"type": "array", "items": _LAND_OWNER_ITEM_SCHEMA},
                },
                "required": ["township", "section", "subsection", "parcel_number", "area_sqm", "owners"],
                "additionalProperties": False,
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
                "required": ["registration_order", "applies_to_parcels", "right_type", "right_holder", "debtor_info"],
                "additionalProperties": False,
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
                    "owners": {"type": "array", "items": _BUILDING_OWNER_ITEM_SCHEMA},
                },
                "required": [
                    "building_number",
                    "building_address",
                    "parcel_number",
                    "total_floors",
                    "floor",
                    "total_area_sqm",
                    "floor_area_sqm",
                    "owners",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["land_parcels", "encumbrances", "buildings"],
    "additionalProperties": False,
}


class OcrError(Exception):
    """Raised when the OCR/extraction provider cannot be reached or returns an error."""


# Asking a vision model to read a whole large batch (dozens of pages) in a single
# request risks degenerate/truncated output - splitting into small chunks and merging
# the results client-side keeps each individual call comfortably sized.
PAGES_PER_CHUNK = 8
PDF_RENDER_DPI = 200


def _expand_pdf_pages(content: bytes) -> list[tuple[bytes, str | None]]:
    """Splits a multi-page PDF into one page-image per page. Chunking has to operate on
    actual pages, not uploaded files - a single 27-page PDF is still just 1 "file", so
    without this a whole batch deed uploaded as one PDF would still be sent in one
    request and hit the same quality breakdown chunking is meant to avoid."""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        # JPEG instead of PNG: these are scanned pages with a dense repeating security
        # watermark pattern, which PNG (lossless) compresses very poorly - each page was
        # coming out ~5-7MB, making both the split-pages preview and every OCR upload
        # painfully slow, especially over a public tunnel. High-quality JPEG is a
        # fraction of the size with no meaningful loss of text legibility.
        pages = [
            (page.get_pixmap(dpi=PDF_RENDER_DPI).tobytes("jpg", jpg_quality=85), "image/jpeg") for page in doc
        ]
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
    """Sends 1+ scanned pages (in the given order) to OpenAI and asks it to return the
    title-deed sections as structured JSON. The pages may be a single 地號/建號's title
    deed, or a batch covering many parcels/buildings - either shape is returned as
    land_parcels/buildings arrays. Multi-page PDFs are first split into per-page images,
    then large page counts are processed in chunks of PAGES_PER_CHUNK and merged (by
    parcel_number / building_number) to avoid per-request quality breakdown. Each chunk
    already retries once internally on failure; if a chunk still fails, the other
    chunks' results are kept and a warning is returned alongside the data instead of
    discarding everything. Returns (data, warning_message_or_None). Every field is a
    suggestion for the user to review before saving, not an authoritative value."""
    if not settings.OPENAI_API_KEY:
        raise OcrError("尚未設定 OPENAI_API_KEY,請聯絡系統管理員設定 OCR 金鑰後再試")
    if not files:
        raise OcrError("沒有可供辨識的檔案")

    pages = _flatten_to_pages(files)
    chunks = [pages[i : i + PAGES_PER_CHUNK] for i in range(0, len(pages), PAGES_PER_CHUNK)]

    results = []
    failed_chunks = []
    for i, chunk in enumerate(chunks):
        try:
            results.append(_extract_title_deed_chunk(chunk))
        except OcrError as exc:
            failed_chunks.append((i, exc))

    if not results:
        raise failed_chunks[0][1]

    warning = None
    if failed_chunks:
        ranges = [f"第 {i * PAGES_PER_CHUNK + 1}-{i * PAGES_PER_CHUNK + len(chunks[i])} 頁" for i, _ in failed_chunks]
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


def _extract_title_deed_chunk(files: list[tuple[bytes, str | None]]) -> dict:
    content_parts = [{"type": "text", "text": EXTRACTION_PROMPT}]
    for content, mime_type in files:
        b64 = base64.b64encode(content).decode("ascii")
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type or 'image/jpeg'};base64,{b64}"},
            }
        )

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "title_deed_extraction", "strict": True, "schema": RESPONSE_SCHEMA},
        },
        # Batch title deeds can contain dozens of parcels/buildings, each with many
        # co-owners - the resulting JSON can be far larger than a single-parcel
        # extraction, so raise the cap to avoid a truncated (invalid) response.
        "max_tokens": 16384,
    }
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    # A single chunk occasionally times out, or the model occasionally returns a
    # truncated/malformed response, under load even though most calls complete cleanly
    # well under a minute - retry the whole request once before giving up, rather than
    # failing the whole (possibly multi-chunk) job over one bad call. A 429 (rate
    # limit) gets a longer backoff since OpenAI's per-minute token windows take real
    # time to free up - a same-instant retry just hits the same wall.
    last_error: OcrError | None = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(OPENAI_ENDPOINT, headers=headers, json=payload, timeout=240.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            if exc.response.status_code == 429 and attempt == 1:
                last_error = OcrError(f"呼叫 OpenAI 服務失敗:{detail}")
                time.sleep(20.0)
                continue
            raise OcrError(f"呼叫 OpenAI 服務失敗:{detail}") from exc
        except httpx.HTTPError as exc:
            last_error = OcrError(f"呼叫 OpenAI 服務失敗:{exc}")
            continue

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            last_error = OcrError("OpenAI 未回傳結果")
            continue

        finish_reason = choices[0].get("finish_reason")
        text = (choices[0].get("message") or {}).get("content") or ""
        if not text:
            last_error = OcrError("OpenAI 回傳內容為空")
            continue
        if finish_reason == "length":
            last_error = OcrError("OpenAI 回傳內容被截斷(超過長度上限)")
            continue

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = OcrError(f"無法解析 OpenAI 回傳的 JSON:{exc}")
            continue

        return {
            "land_parcels": parsed.get("land_parcels") or [],
            "encumbrances": parsed.get("encumbrances") or [],
            "buildings": parsed.get("buildings") or [],
        }

    raise last_error


# ---- Auto-grouping via the "續次頁" (continued on next page) marker ----
#
# Taiwan land/building registry printouts mark the bottom of every page with either
# 「續次頁」(this 地號/建號's record continues onto the next page) or nothing/a terminal
# marker like 「本謄本列印完畢」(printing complete). That's a reliable, document-native
# signal for exactly where one parcel/building's record ends - reusing it to
# pre-compute page groups is far more trustworthy than asking a model to guess parcel
# boundaries while also trying to transcribe everything in the same pass.

CONTINUATION_PROMPT = """以下是同一份台灣土地/建物登記謄本依照順序排列的頁面。每一頁印完的資料內容\
「最後一行」,通常會印著「(續次頁)」或「(本謄本列印完畢)」其中一種——注意:這行字緊接在該頁最後一筆印出的\
資料內容之後,不是印在整張紙的最底部(這種謄本很多頁下半部是大片空白,不要被空白區域誤導,要往上找資料實際\
印到哪裡結束)。

- 如果那一行是「(續次頁)」:代表這一筆地號/建號的記錄會接續到下一頁,這頁不是這筆記錄的最後一頁。
- 如果那一行是「(本謄本列印完畢)」,或找不到這兩種字樣(例如版面已經直接接著下一筆地號/建號的新標題),\
代表這一頁是目前這筆記錄的最後一頁。

請針對每一頁,找到該頁資料內容實際結束的地方,判斷那裡印的是不是「(續次頁)」,依照頁面順序回傳一個布林值\
陣列(true=是續次頁、這筆記錄還沒結束,false=不是續次頁、這筆記錄在這頁結束),陣列長度必須跟頁數一樣多。"""

CONTINUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "continuation_flags": {"type": "array", "items": {"type": "boolean"}},
    },
    "required": ["continuation_flags"],
    "additionalProperties": False,
}


def _detect_continuation_chunk(files: list[tuple[bytes, str | None]]) -> list[bool]:
    content_parts = [{"type": "text", "text": CONTINUATION_PROMPT}]
    for content, mime_type in files:
        b64 = base64.b64encode(content).decode("ascii")
        content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type or 'image/jpeg'};base64,{b64}"}})

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "continuation_detection", "strict": True, "schema": CONTINUATION_SCHEMA},
        },
        "max_tokens": 2048,
    }
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    try:
        resp = httpx.post(OPENAI_ENDPOINT, headers=headers, json=payload, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        flags = json.loads(text).get("continuation_flags") or []
    except (httpx.HTTPError, json.JSONDecodeError):
        # Best-effort: if detection fails, treat every page in this chunk as
        # "continues" so they collapse into one group rather than being scattered
        # into spurious extra groups - the user can still split them apart manually.
        flags = [True] * len(files)

    if len(flags) != len(files):
        flags = (flags + [True] * len(files))[: len(files)]
    return flags


def detect_page_groups(pages: list[tuple[bytes, str | None]]) -> list[int]:
    """Returns a 1-based group number per page, computed from the 「續次頁」 marker: a
    page without the marker ends the current group, so the next page (if any) starts a
    new one. This is only a suggestion - the wizard's grouping step still lets the user
    review and override every page's group number before OCR runs."""
    if not settings.OPENAI_API_KEY or not pages:
        return [1] * len(pages)

    chunks = [pages[i : i + PAGES_PER_CHUNK] for i in range(0, len(pages), PAGES_PER_CHUNK)]
    flags: list[bool] = []
    for chunk in chunks:
        flags.extend(_detect_continuation_chunk(chunk))

    groups = []
    group = 1
    for flag in flags:
        groups.append(group)
        if not flag:
            group += 1
    return groups
