# -*- coding: utf-8 -*-
"""
국립중앙도서관(NLK) 서지정보 유통지원시스템(Seoji) Open API를 이용한
BookOasis 메타데이터 검색 플러그인.

- 공식 API: https://www.nl.go.kr/seoji/SearchApi.do
- 인증키 발급: https://www.nl.go.kr/seoji/ > Open API 신청 (무료)
- 참고: 인증키가 없으면 search()는 안내 메시지만 반환하고,
  컨텍스트 메뉴의 "NLK 통합검색에서 열기"는 인증키 없이도 동작합니다.
"""
import urllib.parse
import urllib.request
import json

from plugins.metadata.base import BaseMetadataProvider

SEOJI_API_URL = "https://www.nl.go.kr/seoji/SearchApi.do"
NLK_ONNARU_SEARCH_URL = "https://www.nl.go.kr/NL/search/tot/totalSearch.do"


class NlkBookMetadataProvider(BaseMetadataProvider):
    """국립중앙도서관(NLK) 서지정보(Seoji) 기반 도서 검색/메타데이터 적용 플러그인."""

    id = "nlk_book"
    name = "국립중앙도서관 도서검색"
    is_searchable = True

    config_schema = [
        {
            "key": "CERT_KEY",
            "label": "Seoji 인증키",
            "type": "password",
            "required": True,
            "help": "https://www.nl.go.kr/seoji/ 에서 무료로 발급받은 Open API 인증키",
        },
        {
            "key": "PAGE_SIZE",
            "label": "검색 결과 개수",
            "type": "number",
            "default": 20,
            "required": False,
        },
    ]

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/leeyj/BookOasis_stable/refs/heads/main/plugins/metadata/nlk_book",
        "files": ["nlk_book.py", "__init__.py", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # 이 플러그인은 별도의 대시보드 위젯을 제공하지 않는다.
    dashboard_widget = None

    # ------------------------------------------------------------------
    # 공통 헬퍼
    # ------------------------------------------------------------------
    def _get_cert_key(self, db_type):
        cfg = self.get_plugin_config(db_type, default={})
        return (cfg.get("CERT_KEY") or "").strip()

    def _get_page_size(self, db_type):
        cfg = self.get_plugin_config(db_type, default={})
        try:
            size = int(cfg.get("PAGE_SIZE") or 20)
        except (TypeError, ValueError):
            size = 20
        return max(1, min(size, 100))

    @staticmethod
    def _http_get_json(url, params, timeout=8):
        query = urllib.parse.urlencode(params)
        full_url = f"{url}?{query}"
        req = urllib.request.Request(full_url, headers={"User-Agent": "BookOasis-NlkBook/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    # 국립중앙도서관 공식 가이드(ISBN 서지정보 Open API 활용방법)에 명시된 에러 코드
    _ERROR_MESSAGES = {
        "000": "국립중앙도서관 시스템 오류가 발생했습니다.",
        "010": "인증키 값이 누락되었습니다. 플러그인 설정에서 인증키를 확인해 주세요.",
        "011": "유효하지 않은 인증키입니다. 발급받은 인증키를 다시 확인해 주세요.",
        "012": "필수 파라미터가 누락되었습니다.",
    }

    @staticmethod
    def _clean(value):
        if value is None:
            return ""
        text = str(value).strip()
        # Seoji 응답의 <> 강조 태그(검색어 하이라이트) 제거
        text = text.replace("<span>", "").replace("</span>", "")
        return text

    @staticmethod
    def _format_date(yyyymmdd):
        # PUBLISH_PREDATE는 "20220509" 형태(8자리)의 출판예정일로 내려온다.
        raw = (yyyymmdd or "").strip()
        if len(raw) == 8 and raw.isdigit():
            return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
        return raw

    def _extract_error_code(self, data):
        # 정확한 에러 응답 키가 문서에 명시돼 있지 않아, 알려진 후보 키들을 방어적으로 확인한다.
        if not isinstance(data, dict):
            return None
        for key in ("ERROR_CODE", "ERR_CODE", "errorCode", "error_code", "RESULT_CODE"):
            code = data.get(key)
            if code and str(code) in self._ERROR_MESSAGES:
                return str(code)
        return None

    def _doc_to_item(self, doc):
        title = self._clean(doc.get("TITLE"))
        author = self._clean(doc.get("AUTHOR"))
        publisher = self._clean(doc.get("PUBLISHER"))
        isbn = self._clean(doc.get("EA_ISBN") or doc.get("SET_ISBN"))
        pub_date = self._format_date(doc.get("PUBLISH_PREDATE"))
        cover_url = self._clean(doc.get("TITLE_URL"))

        subject = self._clean(doc.get("SUBJECT"))
        edition = self._clean(doc.get("EDITION_STMT"))
        kdc = self._clean(doc.get("KDC"))
        page_info = self._clean(doc.get("PAGE"))
        book_size = self._clean(doc.get("BOOK_SIZE"))
        form = self._clean(doc.get("FORM"))
        price = self._clean(doc.get("PRE_PRICE"))

        summary_parts = []
        if subject:
            summary_parts.append(f"주제분류(KDC 대분류): {subject}")
        if kdc:
            summary_parts.append(f"한국십진분류: {kdc}")
        if edition:
            summary_parts.append(f"판사항: {edition}")
        if form:
            summary_parts.append(f"형태: {form}")
        page_size_parts = " / ".join([p for p in [page_info, book_size] if p])
        if page_size_parts:
            summary_parts.append(f"페이지/책크기: {page_size_parts}")
        if price:
            summary_parts.append(f"예정가격: {price}")

        return {
            "title": title,
            "author": author,
            "publisher": publisher,
            "isbn": isbn,
            "pub_date": pub_date,
            "cover_url": cover_url,
            "summary": " / ".join(summary_parts),
            "source": "국립중앙도서관(NLK)",
        }

    # ------------------------------------------------------------------
    # 필수 계약: search / apply
    # ------------------------------------------------------------------
    def search(self, db_type, query):
        q = str(query or "").strip()
        print(f"[NlkBookMetadataProvider] search called db_type={db_type!r} query={q!r}")

        if not q:
            return {"success": True, "items": []}

        cert_key = self._get_cert_key(db_type)
        if not cert_key:
            return {
                "success": False,
                "error": "국립중앙도서관 Seoji 인증키가 설정되지 않았습니다. "
                         "환경설정 > 플러그인 설정에서 인증키를 입력해 주세요. "
                         "(무료 발급: https://www.nl.go.kr/seoji/)",
            }

        # 공식 요청 파라미터: cert_key, result_style, page_no, page_size, title(본표제) 등
        # (title 검색 요청)
        params = {
            "cert_key": cert_key,
            "result_style": "json",
            "page_no": 1,
            "page_size": self._get_page_size(db_type),
            "title": q,
        }

        try:
            data = self._http_get_json(SEOJI_API_URL, params)
        except Exception:
            import traceback
            print(f"[NlkBookMetadataProvider] API call failed: {traceback.format_exc()}")
            return {"success": False, "error": "국립중앙도서관 API 호출에 실패했습니다. 잠시 후 다시 시도해 주세요."}

        error_code = self._extract_error_code(data)
        if error_code:
            message = self._ERROR_MESSAGES.get(error_code, f"알 수 없는 오류(코드 {error_code})가 발생했습니다.")
            print(f"[NlkBookMetadataProvider] API error code={error_code}")
            return {"success": False, "error": message}

        docs = data.get("docs") or []
        # title 검색 결과가 없을 경우, 저자명일 가능성을 고려해 author 파라미터로 한 번 더 시도
        if not docs:
            try:
                params2 = dict(params)
                params2.pop("title", None)
                params2["author"] = q
                data = self._http_get_json(SEOJI_API_URL, params2)
                if not self._extract_error_code(data):
                    docs = data.get("docs") or []
            except Exception:
                import traceback
                print(f"[NlkBookMetadataProvider] fallback author search failed: {traceback.format_exc()}")

        items = [self._doc_to_item(doc) for doc in docs if doc.get("TITLE")]
        print(f"[NlkBookMetadataProvider] search returned {len(items)} items")
        return {"success": True, "items": items}

    def apply(self, db_type, book_id, item_data):
        print(f"[NlkBookMetadataProvider] apply called db_type={db_type!r} book_id={book_id!r}")
        if not book_id:
            return False, "book_id가 없습니다."

        item_data = item_data or {}
        fields = {}
        if item_data.get("title"):
            fields["title"] = item_data["title"]
        if item_data.get("author"):
            fields["author"] = item_data["author"]
        if item_data.get("publisher"):
            fields["publisher"] = item_data["publisher"]
        if item_data.get("isbn"):
            fields["isbn"] = item_data["isbn"]
        if item_data.get("pub_date"):
            fields["pub_date"] = item_data["pub_date"]
        if item_data.get("cover_url"):
            fields["cover_url"] = item_data["cover_url"]
        if item_data.get("summary"):
            fields["summary"] = item_data["summary"]

        if not fields:
            return False, "적용할 메타데이터가 없습니다."

        try:
            gateway = self.get_db_gateway(db_type)
            set_clause = ", ".join([f"{key} = ?" for key in fields.keys()])
            values = list(fields.values()) + [book_id]
            gateway.execute(f"UPDATE books SET {set_clause} WHERE id = ?", tuple(values))
        except Exception:
            import traceback
            print(f"[NlkBookMetadataProvider] apply failed: {traceback.format_exc()}")
            return False, "메타데이터 적용 중 오류가 발생했습니다."

        return True, "국립중앙도서관 메타데이터가 적용되었습니다."

    # ------------------------------------------------------------------
    # 선택 계약: 컨텍스트 메뉴 (인증키 없이도 동작)
    # ------------------------------------------------------------------
    def get_context_menu_items(self, db_type, context):
        print(f"[NlkBookMetadataProvider] get_context_menu_items db_type={db_type!r} context={context!r}")
        return [
            {
                "id": "open_nlk_search",
                "label": "국립중앙도서관 통합검색에서 열기",
                "icon": "fa-solid fa-landmark",
            }
        ]

    def _build_search_query(self, db_type, context):
        book_id = (context or {}).get("book_id")
        title = (context or {}).get("book_title") or ""
        author = ""

        if book_id:
            try:
                gateway = self.get_db_gateway(db_type)
                row = gateway.fetch_one("SELECT title, author FROM books WHERE id = ?", (book_id,))
                if row:
                    title = row["title"] or title
                    author = row["author"] or ""
            except Exception:
                import traceback
                print(f"[NlkBookMetadataProvider] db lookup failed: {traceback.format_exc()}")

        query_parts = [part.strip() for part in [title, author] if part and str(part).strip()]
        return " ".join(query_parts).strip()

    def run_context_menu_action(self, db_type, action_id, context):
        print(f"[NlkBookMetadataProvider] run_context_menu_action action_id={action_id!r} context={context!r}")
        if action_id != "open_nlk_search":
            return {"success": False, "error": f"지원하지 않는 액션입니다: {action_id}"}

        query = self._build_search_query(db_type, context)
        if not query:
            return {"success": False, "error": "검색할 도서 제목 정보가 없습니다."}

        url = NLK_ONNARU_SEARCH_URL + "?" + urllib.parse.urlencode({
            "kwd": query,
            "pageNum": 1,
            "detailSearchYn": "N",
        })
        return {
            "success": True,
            "message": "국립중앙도서관 통합검색 페이지를 새 탭으로 엽니다.",
            "open_url": url,
        }
