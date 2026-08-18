import base64
import io
import json
import re
import time

import fitz
import httpx
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from config import settings

OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

EXTRACTION_PROMPT = """你是台灣地政士助理。以下會依序提供同一份謄本文件連續頁面、經本地 OCR 引擎辨識出的原始文字\
內容(不是圖片)。這份文件可能是「單一地號/建號」的謄本,也可能是「批次謄本」——同一份文件裡連續印著好幾筆不同地號、\
好幾筆不同建號(例如信義區祥和段三小段0242-0000、0250-0000...等多筆地號依序印在同一份 PDF 裡),每筆地號/建號底下\
又可能有一長串繼承共有人(常見一筆地號有 10 位以上所有權人,分散在好幾頁)。請通盤閱讀所有頁面後,依照提供的 JSON \
schema 回傳結構化結果。

OCR 文字品質提醒:這些掃描件背景印有防偽浮水印,OCR 有時會把浮水印紋路誤判成一串沒有意義的英數字雜訊(例如\
「DCDDdDDDdDdDADCDdDDdDDdDdDDdDdCDDDQDD」這種夾雜在正常文字行之間的重複亂碼),請自行判斷、忽略這類雜訊,絕對不要\
當成真實資料填入任何欄位;OCR 也可能把個別字認錯(例如「日」認成「白」、「義」認成「羲」),請依上下文合理判斷還原\
正確字,不要照單全收。

重要規則:
- 每一頁最上方都會印出「XX段XX小段0242-0000地號」這樣的標題,這是每頁都會重複列印的頁首(跟頁次欄位一樣逐頁重印),\
不代表每次看到標題文字就是新的一筆——真正決定是否為新地號的關鍵,是標題裡的地號數字本身有沒有換成不同號碼。同一筆\
地號的所有權人清單常橫跨好幾頁,每一頁都會重複印同樣的標題文字,這些頁面全部算同一筆,收進同一個 land_parcels 項目\
的 owners 陣列裡,不可遺漏任何一位;只有當地號數字真的變成不同號碼時,才代表開始一筆新的土地資料,才在 land_parcels \
陣列中新增一個項目,絕對不要把同一個地號因為標題文字在好幾頁重複出現,就重複建立好幾筆一模一樣的項目。
- 同樣地,建號標題也是逐頁重複列印,判斷是否為新的一筆要看建號數字本身有沒有換,不是看標題文字有沒有再次出現;\
建物所有權人的收錄規則同上,同一建號絕對不要因為標題重複出現在好幾頁就重複建立。
- 登記次序請填「登記次序:」後面的實際值(例如「0002」),不要填每筆記錄前面括號內的流水編號(例如「(0001)」),\
這兩者不是同一個東西。
- 面積、地價、權利範圍等數字或分數欄位前後常有 * 字元作為版面對齊填充(例如「****134.00平方公尺」、\
「**********4分之1**********」),這些 * 不是資料的一部分,請忽略,只填實際的數字/文字內容。
- owners 的 ownership_numerator/ownership_denominator 只能取自單獨一行的「權利範圍:」欄位(目前的持分),\
絕對不要跟「歷次取得權利範圍:」欄位搞混——後者是這位所有權人「以前某一次取得時」的歷史持分紀錄(同一人底下\
常常會有好幾筆不同數字的歷次取得權利範圍,分別對應不同次取得的時間點),不是現在的持分,不可以拿來當作\
ownership_numerator/ownership_denominator。
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
     - ownership_numerator:「權利範圍:」欄位的分子(例如「10000000分之10364」中的 10364;不是「歷次取得\
權利範圍:」欄位)
     - ownership_denominator:「權利範圍:」欄位的分母(例如「10000000分之10364」中的 10000000;不是「歷次\
取得權利範圍:」欄位)
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
     - ownership_numerator:「權利範圍:」欄位的分子(不是「歷次取得權利範圍:」欄位)
     - ownership_denominator:「權利範圍:」欄位的分母(不是「歷次取得權利範圍:」欄位)
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


def merge_pages_to_pdf(pages: list[tuple[bytes, str | None]]) -> bytes:
    """The inverse of _expand_pdf_pages(): combines page images back into a single PDF,
    one page image per PDF page. Used to give a batch-import case group a durable, findable
    home as a normal project document right after it's split off - without this the
    original scan pages only exist transiently in the browser tab that ran the split, and
    are lost the moment that tab is closed or navigated away from without immediately
    running the OCR wizard on them. Page size is derived from each image's pixel
    dimensions at PDF_RENDER_DPI, matching how _expand_pdf_pages originally rendered them
    - this keeps a page merged from a PDF-sourced image the same physical size a PDF
    viewer would show, and produces a reasonable approximation for images that were
    directly uploaded (not from a PDF) too."""
    doc = fitz.open()
    for content, _mime_type in pages:
        img = Image.open(io.BytesIO(content))
        width_pt = img.width * 72 / PDF_RENDER_DPI
        height_pt = img.height * 72 / PDF_RENDER_DPI
        page = doc.new_page(width=width_pt, height=height_pt)
        page.insert_image(page.rect, stream=content)
    return doc.tobytes()


def downscale_for_preview(content: bytes, max_dimension: int = 1000, quality: int = 65) -> bytes:
    """Shrinks a page image for use as a lightweight preview - e.g. the batch-import
    case-split review grid only ever displays these at ~110px tall, so there's no need
    to ship the full ~200-DPI page (several MB each, since these are dense scans with a
    repeating watermark that compresses poorly). Returning the untouched original for a
    batch of a few dozen pages made that response payload huge (100+MB), which was
    painfully slow to actually download over a remote/mobile connection (e.g. through a
    Tailscale Funnel) even though the server had already finished processing and logged
    the request as complete. Falls back to the original bytes if the image can't be
    decoded, rather than dropping the page."""
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return content
    img = img.convert("RGB")
    if max(img.width, img.height) > max_dimension:
        scale = max_dimension / max(img.width, img.height)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def extract_title_deed(files: list[tuple[bytes, str | None]], record_type: str = "both") -> tuple[dict, str | None]:
    """OCRs 1+ scanned pages (in the given order) locally, then sends the recognized
    text to OpenAI and asks it to return the title-deed sections as structured JSON. The
    pages may be a single 地號/建號's title deed, or a batch covering many
    parcels/buildings - either shape is returned as
    land_parcels/buildings arrays. record_type ("land"/"building"/"both") tells the
    model which section(s) the batch actually contains, so it doesn't invent a spurious
    entry of the excluded type out of misread content (e.g. treating a land page's
    parcel_number as if it belonged to a building record). Multi-page PDFs are first
    split into per-page images, then large page counts are processed in chunks of
    PAGES_PER_CHUNK and merged (by parcel_number / building_number) to avoid per-request
    quality breakdown. Each chunk already retries once internally on failure; if a chunk
    still fails, the other chunks' results are kept and a warning is returned alongside
    the data instead of discarding everything. Returns (data, warning_message_or_None).
    Every field is a suggestion for the user to review before saving, not an
    authoritative value."""
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
            results.append(_extract_title_deed_chunk(chunk, record_type))
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


# Loading RapidOCR's models takes a couple seconds - doing that once per process and
# reusing the engine avoids paying that cost on every single page.
_OCR_ENGINE: RapidOCR | None = None


def _get_ocr_engine() -> RapidOCR:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _ocr_page_text(content: bytes) -> str:
    """Runs local OCR on one page image and returns its recognized text lines, one per
    line, in the reading order RapidOCR detects them in. Garbled noise from these scans'
    background security watermark sometimes gets picked up as spurious text lines -
    that's left as-is for the downstream OpenAI call to recognize and ignore, rather
    than trying to filter it heuristically here and risking real text getting dropped."""
    img = Image.open(io.BytesIO(content)).convert("RGB")
    result, _ = _get_ocr_engine()(np.array(img))
    return "\n".join(line[1] for line in result) if result else ""


# Appended to EXTRACTION_PROMPT when the caller already knows which section(s) a batch
# contains (the frontend asks the user upfront) - telling the model to not even attempt
# the excluded type is more reliable than extracting both and discarding one, because it
# stops the model from ever conjuring a spurious entry of the excluded type out of
# misread/ambiguous content in the first place (e.g. a land page's parcel_number
# bleeding into a fabricated buildings entry).
_RECORD_TYPE_INSTRUCTIONS = {
    "land": "\n\n這一批文件只有土地謄本,不會有建物謄本:buildings 一律回傳空陣列 [],絕對不要自己臆測或拼湊出建物資料。",
    "building": "\n\n這一批文件只有建物謄本,不會有土地謄本:land_parcels 一律回傳空陣列 [],絕對不要自己臆測或拼湊出土地資料。",
    "both": "",
}


def _extract_title_deed_chunk(files: list[tuple[bytes, str | None]], record_type: str = "both") -> dict:
    # Pages are OCR'd locally first (see _ocr_page_text) instead of sending the raw
    # images to a vision model - a dedicated OCR engine reads dense small print (parcel
    # numbers, ID numbers, ownership fractions) far more reliably than a vision LLM
    # skimming a downsized page image. The model's job here is purely to organize and
    # sanity-check already-recognized text, not to also read characters off pixels.
    page_texts = [_ocr_page_text(content) for content, _ in files]
    pages_block = "\n\n".join(
        f"----- 第 {i + 1} 頁 OCR 文字 -----\n{text or '(本頁 OCR 沒有讀到文字)'}"
        for i, text in enumerate(page_texts)
    )
    prompt = EXTRACTION_PROMPT + _RECORD_TYPE_INSTRUCTIONS.get(record_type, "")

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [{"role": "user", "content": f"{prompt}\n\n{pages_block}"}],
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

# Every page has a 「頁次:000001」-style field near the top (next to 「列印時間」) that
# counts pages *within the current 地號/建號's own record* - it resets to 000001 every
# time a new 地號/建號's data starts. That's a more reliable signal than the 「續次頁」
# text marker (whose position on the page varies with how much content that page has)
# because it's a fixed-format field in a fixed location: crop to the top strip, check
# whether 頁次 reads 000001, and a page that does is the start of a new group.
PAGE_SEQUENCE_PROMPT = """以下是同一份台灣土地/建物登記謄本依照順序排列的頁面。每一頁最上方,「列印時間」\
旁邊會印著「頁次:XXXXXX」這個欄位(6 位數字)。這個頁次是「目前這一筆地號/建號自己的內部頁碼」,每次\
換到新的一筆地號/建號,頁次就會重新從 000001 開始算。

請針對每一頁,讀出「頁次:」後面的 6 位數字,判斷是不是「000001」,依照頁面順序回傳一個布林值陣列\
(true=頁次是 000001、這頁是新一筆地號/建號的第一頁,false=頁次不是 000001、這頁接續前一頁同一筆記錄),\
陣列長度必須跟頁數一樣多。"""

PAGE_SEQUENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_first_page": {"type": "array", "items": {"type": "boolean"}},
    },
    "required": ["is_first_page"],
    "additionalProperties": False,
}


def _call_openai_structured(payload: dict) -> dict:
    """POSTs to OpenAI chat completions and returns the parsed JSON content, retrying
    once on a 429 (rate limit) after a real pause - OpenAI's per-minute token budget
    needs actual time to free up, so an instant retry just hits the same wall. Used by
    the lightweight per-page detection helpers below; the main extraction path
    (_extract_title_deed_chunk) has its own copy of this same pattern inline."""
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    last_error: OcrError | None = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(OPENAI_ENDPOINT, headers=headers, json=payload, timeout=120.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt == 1:
                last_error = OcrError(exc.response.text)
                time.sleep(20.0)
                continue
            raise OcrError(f"呼叫 OpenAI 服務失敗:{exc.response.text}") from exc
        except httpx.HTTPError as exc:
            last_error = OcrError(f"呼叫 OpenAI 服務失敗:{exc}")
            continue

        data = resp.json()
        text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        if not text:
            last_error = OcrError("OpenAI 回傳內容為空")
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = OcrError(f"無法解析 OpenAI 回傳的 JSON:{exc}")
            continue

    raise last_error


def _detect_page_sequence_chunk(files: list[tuple[bytes, str | None]]) -> list[bool] | None:
    """Returns None (rather than a guessed value) if detection fails after retrying -
    the caller must treat that as "unknown", not silently merge it into whatever group
    happened to be current. A wrong guess here is what let 99 pages that actually
    covered several different 地號/建號 silently collapse into one group with no visible
    sign anything had gone wrong."""
    content_parts = [{"type": "text", "text": PAGE_SEQUENCE_PROMPT}]
    for content, mime_type in files:
        cropped = _crop_top_strip(content)
        b64 = base64.b64encode(cropped).decode("ascii")
        content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "page_sequence_detection", "strict": True, "schema": PAGE_SEQUENCE_SCHEMA},
        },
        "max_tokens": 2048,
    }

    try:
        parsed = _call_openai_structured(payload)
    except OcrError:
        return None

    flags = parsed.get("is_first_page") or []
    if len(flags) != len(files):
        flags = (flags + [True] * len(files))[: len(files)]
    return flags


def detect_page_groups(pages: list[tuple[bytes, str | None]]) -> tuple[list[int], str | None]:
    """Returns (1-based group number per page, optional warning). Group numbers are
    computed from the 「頁次:000001」 field near the top of each page: a page whose 頁次
    reads 000001 starts a new group (it's the first page of a new 地號/建號's own
    record); any other 頁次 value continues the current group. If detection fails for
    some pages even after retrying, those pages are forced to start their own group
    (visible as an odd boundary) rather than silently merged into the current one, and
    a warning is returned naming which pages need manual review. This is only a
    suggestion either way - the wizard's grouping step still lets the user review and
    override every page's group number before OCR runs."""
    if not settings.OPENAI_API_KEY or not pages:
        return [1] * len(pages), None

    chunks = [pages[i : i + PAGES_PER_CHUNK] for i in range(0, len(pages), PAGES_PER_CHUNK)]
    flags: list[bool] = []
    failed_ranges = []
    for i, chunk in enumerate(chunks):
        result = _detect_page_sequence_chunk(chunk)
        if result is None:
            result = [True] * len(chunk)
            start = i * PAGES_PER_CHUNK + 1
            failed_ranges.append(f"第{start}-{start + len(chunk) - 1}頁")
        flags.extend(result)

    groups = []
    group = 1
    for i, is_first in enumerate(flags):
        if i > 0 and is_first:
            group += 1
        groups.append(group)
    warning = f"{'、'.join(failed_ranges)}自動分組偵測失敗,已強制獨立成一組,請務必手動確認分組" if failed_ranges else None
    return groups, warning


# ---- Auto-grouping by 都更案件 (urban renewal case) via the page title ----
#
# Every page's title has two lines: the document type (「土地登記第三類謄本(地號全部)」
# or 「建物登記第三類謄本(建物全部)」), then 「XX區XX段XX小段XX地號/建號」. In this system a
# "案件" is one 地號/建號, not one whole urban-renewal project area - a batch upload
# routinely contains several different 地號 that all sit in the same 鄉鎮市區+段+小段
# (e.g. 0223-0000, 0229-0001, 0229-0002 all under 信義區祥和段三小段), so the location
# text alone can't tell them apart. The signal used here is the same one
# detect_page_groups() uses one level down: a change in the specific 地號/建號 number
# starts a new group - except here it's read via regex off locally-OCR'd text (see
# _parse_case_header) instead of asking a vision model, because both the title and the
# 頁次 field are in a fixed, rigid printed format that doesn't need an LLM to parse, and
# doing it locally means no OpenAI call (no per-page cost, no shared-quota rate limit -
# a batch of a few dozen pages was routinely blowing through the org's 200k
# tokens-per-minute cap and silently losing whole chunks of pages to "detection
# failed").
#
# The title and the 頁次 field live in the same fixed header area at the very top of
# every page (unlike the old 續次頁-marker approach, whose position on the page varied
# with how much content that page had), so cropping to a small top strip before OCR
# keeps each page's OCR pass fast without losing either field.
TOP_STRIP_CROP_FRACTION = 0.15


def _crop_top_strip(content: bytes, fraction: float = TOP_STRIP_CROP_FRACTION) -> bytes:
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return content  # not a decodable raster image - fall back to sending it whole
    width, height = img.size
    cropped = img.crop((0, 0, width, max(1, int(height * fraction))))
    buf = io.BytesIO()
    cropped.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# Matches titles like 「信義區祥和段三小段0249-0000地號」or 「板橋區松雲段00102-000建號」.
# 小段 is optional - many 謄本 don't have one. 地號/建號 also matches with the simplified
# 号 glyph (「地号」/「建号」), which some pages get OCR'd as instead of 號.
_CASE_TITLE_PATTERN = re.compile(
    r"(?P<location>[一-鿿]{1,4}(?:市|區|鄉|鎮)[一-鿿]{1,8}段(?:[一-鿿]{1,6}小段)?)"
    r"(?P<number>\d{3,6}-\d{3,6})\s*(?:地[號号]|建[號号])"
)
_DIGITS_PATTERN = re.compile(r"(\d{4,6})")
# Anchors on the 列印時間 line's own date/time digits (「115年04月10日」) rather than the
# 「列印時間」label text - real OCR output showed that label getting misread in several
# different, unpredictable ways (「列」->「岁」, 「間」->「周」, or missing entirely), while
# the digits next to 年/月/日 came through correctly every time across dozens of real
# pages. 年/月/日 are common, visually distinct characters unlikely to all get misread
# together, making this a much sturdier anchor than the label text was.
_PRINT_TIME_LINE_PATTERN = re.compile(r"\d{2,3}年\d{1,2}月\d{1,2}日")


def _find_page_sequence(text: str) -> int | None:
    """Finds the 頁次 field's numeric value by position: it's always printed on the line
    immediately after 列印時間 (located via _PRINT_TIME_LINE_PATTERN - see its comment for
    why), so this pulls the first run of digits off that next line regardless of what
    頁次's own label got misread as (「頁」->「真」, 「次」->「欠」, or garbled beyond
    recognition). Returns None if no 列印時間 line (or no digits on the line after it) was
    found - the caller treats that as "unknown", not "definitely page 1"."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _PRINT_TIME_LINE_PATTERN.search(line) and i + 1 < len(lines):
            match = _DIGITS_PATTERN.search(lines[i + 1])
            return int(match.group(1)) if match else None
    return None


def _parse_case_header(text: str) -> tuple[str, str, bool]:
    """Pulls this page's (地點, 地號/建號, is_first_page) straight out of its OCR'd
    header text. On success, is_first_page (是否「頁次:000001」, see _find_page_sequence)
    is what detect_case_groups() uses to decide group boundaries - comparing 地號/建號
    strings directly was tried first and turned out too fragile: a single misread digit
    in a multi-digit 地號 (e.g. a vision model conflating the adjacent 頁次 field and
    reading "0230-0000"/"000003" as if "0230-0003" was the parcel number) silently
    fractured one real group into two. is_first_page only needs a binary "is this
    000001 or not" judgment. location and sample_number are kept only for suggesting a
    readable case name/code, not used for the boundary."""
    # OCR sometimes splits the title across two detected lines right at the 小段
    # boundary (e.g. 「信義區祥和段」 / 「小段0250-0000地號」as separate lines) - flatten
    # newlines before matching so the title pattern still catches it as one string.
    # _find_page_sequence below needs the original line structure, so this flattened
    # copy is only used for the title search.
    flattened = text.replace("\n", "")
    location, sample_number = "", ""
    for match in _CASE_TITLE_PATTERN.finditer(flattened):
        # Skip 「共同保地號:」/「共同保建號:」cross-reference lines lower in the header -
        # they're a different parcel/building than this page's own title and can appear
        # without a 市/區/鄉/鎮 prefix, but guard anyway in case a document's OCR text
        # ever lines them up in a way that matches.
        prefix = flattened[max(0, match.start() - 6) : match.start()]
        if "共同" in prefix:
            continue
        location, sample_number = match.group("location"), match.group("number")
        break

    seq = _find_page_sequence(text)
    is_first_page = True if seq is None else seq == 1  # unknown defaults to "new group" - safer than a silent merge
    return location, sample_number, is_first_page


def detect_case_groups(pages: list[tuple[bytes, str | None]]) -> tuple[list[tuple[int, str, str]], str | None]:
    """Returns ([(1-based case group number, detected location label, sample 地號/建號),
    ...], optional warning). A "案件" here is one 地號/建號: a page whose 頁次 reads
    000001 starts a new group; any other 頁次 value continues whatever group is current.
    location/sample_number play no part in the boundary - they're only carried along to
    suggest a readable case name/code. Detection runs entirely locally (OCR + regex, see
    _parse_case_header) - no OpenAI call, no per-page cost, no shared rate limit. If a
    page's header can't be parsed (OCR failure or unexpected format), that page is
    forced to start its own new group instead of being silently merged into whatever
    group was current, and a warning names which pages need manual review. Only a
    suggestion either way - the batch-import review step lets the user move pages
    between groups and rename each group before any project gets created."""
    if not pages:
        return [], None

    entries: list[tuple[str, str, bool]] = []
    failed_pages: list[int] = []
    raw_texts: list[str] = []  # TEMP DEBUG
    for i, (content, _mime_type) in enumerate(pages):
        try:
            text = _ocr_page_text(_crop_top_strip(content))
            raw_texts.append(text)  # TEMP DEBUG
            entries.append(_parse_case_header(text))
        except Exception as exc:
            print(f"[detect_case_groups] page {i + 1} OCR/parse failed: {exc}", flush=True)
            raw_texts.append("")  # TEMP DEBUG
            entries.append(("(偵測失敗)", "", True))
            failed_pages.append(i + 1)

    grouped: list[tuple[int, str, str]] = []
    group = 1
    for i, (label, sample_number, is_first_page) in enumerate(entries):
        if i > 0 and is_first_page:
            group += 1
        grouped.append((group, label, sample_number))

    # TEMP DEBUG - remove once the case-split grouping issue is diagnosed. Prints what
    # each page was actually detected as (including the raw OCR text and the matched
    # 頁次 digits) so a live log-tail can show exactly which page the OCR/regex misread
    # instead of guessing from the UI's end result.
    print("[detect_case_groups] per-page detection:", flush=True)
    for i, ((group_no, label, sample_number), (_l, _s, is_first_page)) in enumerate(zip(grouped, entries)):
        seq = _find_page_sequence(raw_texts[i])
        print(
            f"  page {i + 1}: group={group_no} location={label!r} sample_number={sample_number!r} "
            f"is_first_page={is_first_page} 頁次={seq!r}",
            flush=True,
        )
        print(f"    raw_ocr={raw_texts[i]!r}", flush=True)

    warning = (
        f"第{'、'.join(str(p) for p in failed_pages)}頁自動分案偵測失敗,已強制獨立成一組,請務必手動確認分組"
        if failed_pages
        else None
    )
    return grouped, warning
