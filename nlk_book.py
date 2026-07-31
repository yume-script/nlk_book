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

    @staticmethod
    def _clean(value):
        if value is None:
            return ""
        text = str(value).strip()
        # Seoji 응답의 <> 강조 태그(검색어 하이라이트) 제거
        text = text.replace("<span>", "").replace("</span>", "")
        return text

    @staticmethod
    def _pick_isbn(doc):
        # EA_ISBN에는 "9788901234567 03810" 처럼 부가기호가 붙어 오는 경우가 있어
        # 앞쪽 13자리 ISBN만 추출한다.
        raw = (doc.get("EA_ISBN") or doc.get("SET_ISBN") or "").strip()
        if not raw:
            return ""
        return raw.split()[0]

    def _doc_to_item(self, doc):
        title = self._clean(doc.get("TITLE"))
        author = self._clean(doc.get("AUTHOR"))
        publisher = self._clean(doc.get("PUBLISHER"))
        isbn = self._pick_isbn(doc)
        pub_date = self._clean(doc.get("REAL_PUBLISH_DATE") or doc.get("PUBLISH_PREDATE"))
        subject = self._clean(doc.get("SUBJECT"))
        price = self._clean(doc.get("PRE_PRICE"))
        page_info = self._clean(doc.get("PAGE"))

        summary_parts = []
        if subject:
            summary_parts.append(f"주제분류: {subject}")
        if page_info:
            summary_parts.append(f"형태사항: {page_info}")
        if price:
            summary_parts.append(f"정가: {price}")

        return {
            "title": title,
            "author": author,
            "publisher": publisher,
            "isbn": isbn,
            "pub_date": pub_date,
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

        docs = data.get("docs") or []
        if not docs:
            # 제목 검색 결과가 없으면 통합 키워드(kwd)로 한 번 더 시도
            try:
                params2 = dict(params)
                params2.pop("title", None)
                params2["kwd"] = q
                data = self._http_get_json(SEOJI_API_URL, params2)
                docs = data.get("docs") or []
            except Exception:
                import traceback
                print(f"[NlkBookMetadataProvider] fallback kwd search failed: {traceback.format_exc()}")

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
