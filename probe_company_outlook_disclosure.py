#!/usr/bin/env python3
"""Probe official OpenDART fair-disclosure discovery and document format."""
from __future__ import annotations

import io
import json
import os
import urllib.parse
import urllib.request
import zipfile

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOC_URL = "https://opendart.fss.or.kr/api/document.xml"


def fetch(url: str, params: dict[str, str]) -> bytes:
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "krx-watchlist-outlook-source-probe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read(12_000_000)


def probe_document(key: str, receipt: str) -> None:
    raw = fetch(DOC_URL, {"crtfc_key": key, "rcept_no": receipt})
    print(f"DOCUMENT_RECEIPT={receipt}")
    print(f"DOCUMENT_BYTES={len(raw)}")
    print(f"DOCUMENT_IS_ZIP={zipfile.is_zipfile(io.BytesIO(raw))}")
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        print("DOCUMENT_ERROR_BODY=" + raw[:300].decode("utf-8", errors="replace"))
        return
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.infolist()[:5]:
            print(f"DOCUMENT_MEMBER={member.filename}:{member.file_size}")
            blob = archive.read(member)
            text = blob.decode("utf-8-sig", errors="replace")
            if text.count("�") > 20:
                text = blob.decode("cp949", errors="replace")
            print("DOCUMENT_PREFIX=" + text[:800].replace("\n", " "))
            for marker in ("정정사항", "매출액", "영업이익", "대상기간"):
                pos = text.find(marker)
                if pos >= 0:
                    print(f"DOCUMENT_{marker}_AROUND=" + text[max(0, pos - 150):pos + 350].replace("\n", " "))


def main() -> None:
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise SystemExit("DART_API_KEY_MISSING")
    params = {
        "crtfc_key": key,
        "bgn_de": "20251222",
        "end_de": "20251222",
        "pblntf_detail_ty": "I002",
        "last_reprt_at": "N",
        "page_no": "1",
        "page_count": "100",
    }
    payload = json.loads(fetch(LIST_URL, params).decode("utf-8"))
    print("LIST_STATUS=" + str(payload.get("status")))
    print("LIST_TOTAL_COUNT=" + str(payload.get("total_count")))
    matches = [
        {"rcept_no": item.get("rcept_no"), "report_nm": item.get("report_nm"),
         "stock_code": item.get("stock_code"), "corp_code": item.get("corp_code")}
        for item in payload.get("list") or []
        if "영업실적" in str(item.get("report_nm")) and "전망" in str(item.get("report_nm"))
    ]
    print("LIST_MATCHES=" + json.dumps(matches[:10], ensure_ascii=False))
    if not matches:
        raise SystemExit("OUTLOOK_CORRECTION_NOT_FOUND_IN_I002_LIST")
    selected = matches[-1]
    corp_params = dict(params, corp_code=selected["corp_code"])
    corp_payload = json.loads(fetch(LIST_URL, corp_params).decode("utf-8"))
    corp_receipts = [item.get("rcept_no") for item in corp_payload.get("list") or []]
    print("CORP_LIST_STATUS=" + str(corp_payload.get("status")))
    print("CORP_LIST_TOTAL_COUNT=" + str(corp_payload.get("total_count")))
    print("CORP_LIST_KNOWN_RECEIPT_FOUND=" + str(selected["rcept_no"] in corp_receipts))
    if selected["rcept_no"] not in corp_receipts:
        raise SystemExit("CORP_FILTER_DROPPED_KNOWN_CORRECTION")
    probe_document(key, selected["rcept_no"])
    probe_document(key, "20260512900617")


if __name__ == "__main__":
    main()

