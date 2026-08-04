# -*- coding: utf-8 -*-
"""
국립중앙도서관(NLK) 서지정보 유통지원시스템(Seoji) Open API를 이용한
BookOasis 메타데이터 검색 플러그인.

- 공식 API: https://www.nl.go.kr/seoji/SearchApi.do
- 인증키 발급: https://www.nl.go.kr/seoji/ > Open API 신청 (무료)
- 기본 검색 기준: 책 제목(title). 입력값이 유효한 ISBN(10/13자리)이면 isbn 파라미터로
  우선 검색하고, 그 외에는 title로 검색한다. title 결과가 없으면 author로 1회 재시도한다.
- 인증키가 없으면 search()는 안내 메시지만 반환하고,
  컨텍스트 메뉴의 "국립중앙도서관 통합검색에서 열기"는 인증키 없이도 동작한다.
- apply()는 unified_book 플러그인과 동일한 books 테이블 스키마(title/author/publisher/
  summary/link/release_date/isbn/cover_image/cover_updated_at)를 기준으로 저장한다.
"""
import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.request

try:
    from PIL import Image
except ImportError:
    Image = None

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
    def _get_row_val(row, key, default=None):
        try:
            return row[key]
        except Exception:
            return getattr(row, key, default)

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
        # Seoji 응답의 강조 태그(검색어 하이라이트) 제거
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
        # 정확한 에러 응답 키가 공식 문서에 명시돼 있지 않아, 알려진 후보 키들을 방어적으로 확인한다.
        if not isinstance(data, dict):
            return None
        for key in ("ERROR_CODE", "ERR_CODE", "errorCode", "error_code", "RESULT_CODE"):
            code = data.get(key)
            if code and str(code) in self._ERROR_MESSAGES:
                return str(code)
        return None

    # ------------------------------------------------------------------
    # ISBN 검증/변환 (unified_book 플러그인의 validate_isbn13/validate_isbn10 방식 참고)
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_isbn13(isbn):
        if len(isbn) != 13 or not isbn.isdigit():
            return False
        total = sum((int(d) * (1 if i % 2 == 0 else 3)) for i, d in enumerate(isbn))
        return total % 10 == 0

    @staticmethod
    def _validate_isbn10(isbn):
        if len(isbn) != 10:
            return False
        total = 0
        for i, ch in enumerate(isbn):
            if ch == "X" and i == 9:
                val = 10
            elif ch.isdigit():
                val = int(ch)
            else:
                return False
            total += (10 - i) * val
        return total % 11 == 0

    @staticmethod
    def _isbn10_to_isbn13(isbn10):
        core = "978" + isbn10[:9]
        total = sum((int(d) * (1 if i % 2 == 0 else 3)) for i, d in enumerate(core))
        check = (10 - (total % 10)) % 10
        return core + str(check)

    def _detect_isbn(self, query):
        """입력값이 유효한 ISBN(10 또는 13자리)이면 정규화된 13자리 ISBN을 반환, 아니면 None."""
        candidate = re.sub(r"[^0-9Xx]", "", query or "").upper()
        if self._validate_isbn13(candidate):
            return candidate
        if self._validate_isbn10(candidate):
            return self._isbn10_to_isbn13(candidate)
        return None

    def _doc_to_item(self, doc):
        title = self._clean(doc.get("TITLE"))
        author = self._clean(doc.get("AUTHOR"))
        publisher = self._clean(doc.get("PUBLISHER"))
        isbn = self._clean(doc.get("EA_ISBN") or doc.get("SET_ISBN"))
        pub_date = self._format_date(doc.get("PUBLISH_PREDATE"))
        cover_url = self._clean(doc.get("TITLE_URL"))
        intro = self._clean(doc.get("BOOK_INTRODUCTION"))

        subject = self._clean(doc.get("SUBJECT"))
        edition = self._clean(doc.get("EDITION_STMT"))
        kdc = self._clean(doc.get("KDC"))
        page_info = self._clean(doc.get("PAGE"))
        book_size = self._clean(doc.get("BOOK_SIZE"))
        form = self._clean(doc.get("FORM"))
        price = self._clean(doc.get("PRE_PRICE"))

        biblio_parts = []
        if subject:
            biblio_parts.append(f"주제분류(KDC 대분류): {subject}")
        if kdc:
            biblio_parts.append(f"한국십진분류: {kdc}")
        if edition:
            biblio_parts.append(f"판사항: {edition}")
        if form:
            biblio_parts.append(f"형태: {form}")
        page_size_parts = " / ".join([p for p in [page_info, book_size] if p])
        if page_size_parts:
            biblio_parts.append(f"페이지/책크기: {page_size_parts}")
        if price:
            biblio_parts.append(f"예정가격: {price}")

        biblio_text = " / ".join(biblio_parts)
        # 실제 책소개(BOOK_INTRODUCTION)가 있으면 맨 앞에 우선 배치하고,
        # 서지정보(KDC/형태/가격 등)는 뒤에 덧붙인다. 소개글이 없으면 서지정보만 사용.
        if intro:
            description_text = intro if not biblio_text else f"{intro}\n\n[서지정보] {biblio_text}"
        else:
            description_text = biblio_text

        # 화면(검색결과 카드)의 출간일 줄에는 별도 ISBN 표시 자리가 없고,
        # pubDate 문자열에 " | ISBN: ..."을 붙여서 함께 보여주는 방식이다.
        # (unified_book 플러그인과 동일한 표시 관례. apply()에서 저장 시 다시 분리한다.)
        display_pub_date = f"{pub_date} | ISBN: {isbn}" if isbn else pub_date

        nlk_detail_link = ""
        if isbn:
            nlk_detail_link = "https://www.nl.go.kr/seoji/SearchDetail.do?" + urllib.parse.urlencode({"isbn": isbn})

        return {
            "title": title,
            "author": author,
            "publisher": publisher,
            "isbn": isbn,
            "isbn13": isbn,
            "pubDate": display_pub_date,
            "cover": cover_url,
            "link": nlk_detail_link,
            "summary": description_text,
            "description": description_text,
            "source": "국립중앙도서관(NLK)",
        }

    @staticmethod
    def _fail_item(title, summary):
        """검색 실패/오류 상황을 결과 카드 한 장으로 표현.
        _not_applicable 플래그로 apply() 단계에서 실수로 저장되지 않도록 막는다.
        (extract_isbn 플러그인과 동일한 패턴)
        """
        return {
            "title": title,
            "author": "",
            "publisher": "",
            "summary": summary,
            "description": summary,
            "isbn": "",
            "cover": "",
            "pubDate": "",
            "link": "",
            "_not_applicable": True,
        }

    def _call_seoji(self, base_params, extra):
        params = dict(base_params)
        params.update(extra)
        data = self._http_get_json(SEOJI_API_URL, params)
        #print(f"[NlkBookMetadataProvider] RAW response ({list(extra.keys())}): {json.dumps(data, ensure_ascii=False)}")
        if self._extract_error_code(data):
            return data, self._extract_error_code(data)
        return data, None

    # ------------------------------------------------------------------
    # 필수 계약: search / apply
    # ------------------------------------------------------------------
    def search(self, db_type, query):
        """
        - 입력값이 유효한 ISBN(10/13자리, 체크섬 검증)이면 isbn 파라미터로 우선 검색한다.
          (필요 시 set_isbn 파라미터로 한 번 더 재시도)
        - ISBN이 아니면 기본 검색 기준은 '책 제목(title)'이다.
          title 검색 결과가 없으면 author 파라미터로 1회 재시도한다.
        """
        q = str(query or "").strip()
        #print(f"[NlkBookMetadataProvider] search called db_type={db_type!r} query={q!r}")

        if not q:
            return []

        cert_key = self._get_cert_key(db_type)
        if not cert_key:
            return [self._fail_item(
                "❌ 인증키가 설정되지 않았습니다",
                "환경설정 > 플러그인 설정에서 Seoji 인증키를 입력해 주세요. (무료 발급: https://www.nl.go.kr/seoji/)",
            )]

        base_params = {
            "cert_key": cert_key,
            "result_style": "json",
            "page_no": 1,
            "page_size": self._get_page_size(db_type),
        }

        isbn_query = self._detect_isbn(q)
        docs = []

        try:
            if isbn_query:
                # 1) 유효한 ISBN 입력 -> isbn 파라미터로 우선 검색
                data, err = self._call_seoji(base_params, {"isbn": isbn_query})
                if err:
                    message = self._ERROR_MESSAGES.get(err, f"알 수 없는 오류(코드 {err})가 발생했습니다.")
                    return [self._fail_item("❌ 국립중앙도서관 API 오류", message)]
                docs = data.get("docs") or []

                # 세트 ISBN일 가능성 -> set_isbn으로 재시도
                if not docs:
                    data, err = self._call_seoji(base_params, {"set_isbn": isbn_query})
                    if not err:
                        docs = data.get("docs") or []

                if not docs:
                    return [self._fail_item(
                        "❌ 검색 결과 없음",
                        f'ISBN "{isbn_query}"에 해당하는 도서를 국립중앙도서관에서 찾지 못했습니다.',
                    )]
            else:
                # 2) 기본 검색 값 = 책 이름(title)
                data, err = self._call_seoji(base_params, {"title": q})
                if err:
                    message = self._ERROR_MESSAGES.get(err, f"알 수 없는 오류(코드 {err})가 발생했습니다.")
                    return [self._fail_item("❌ 국립중앙도서관 API 오류", message)]
                docs = data.get("docs") or []

                # 제목 검색 결과가 없을 경우, 저자명일 가능성을 고려해 author 파라미터로 한 번 더 시도
                if not docs:
                    data, err = self._call_seoji(base_params, {"author": q})
                    if not err:
                        docs = data.get("docs") or []
        except Exception:
            import traceback
            print(f"[NlkBookMetadataProvider] API call failed: {traceback.format_exc()}")
            return [self._fail_item("❌ API 호출 실패", "국립중앙도서관 API 호출에 실패했습니다. 잠시 후 다시 시도해 주세요.")]

        print(f"[NlkBookMetadataProvider] docs count={len(docs)}")
        for idx, doc in enumerate(docs):
            print(f"[NlkBookMetadataProvider] doc[{idx}] = {json.dumps(doc, ensure_ascii=False)}")

        items = [self._doc_to_item(doc) for doc in docs if doc.get("TITLE")]
        print(f"[NlkBookMetadataProvider] search returned {len(items)} items")

        if not items:
            return [self._fail_item("❌ 검색 결과 없음", f'"{q}"와 일치하는 도서를 국립중앙도서관에서 찾지 못했습니다.')]

        return items

    def apply(self, db_type, book_id, item_data):
        """unified_book 플러그인과 동일한 books 테이블 스키마 기준으로 저장한다.
        (title, author, publisher, summary, link, release_date, isbn[선택], cover_image, cover_updated_at)
        """
        print(f"[NlkBookMetadataProvider] apply called db_type={db_type!r} book_id={book_id!r}")
        if not book_id:
            return False, "book_id가 없습니다."

        item_data = item_data or {}
        if item_data.get("_not_applicable"):
            return False, "적용할 수 없는 결과입니다. (검색 실패/안내 카드)"

        gateway = self.get_db_gateway(db_type)
        try:
            book = gateway.fetch_one("SELECT file_path, library_id FROM books WHERE id = ?", (book_id,))
            if not book:
                return False, "도서를 찾을 수 없습니다."

            file_path = self._get_row_val(book, "file_path")
            library_id = self._get_row_val(book, "library_id")

            # 표지: URL을 그대로 저장하지 않고 다운로드 -> WebP 변환 -> covers/<library_id>/ 에 저장
            cover_url = item_data.get("cover")
            cover_filename = None
            if cover_url and Image is not None:
                try:
                    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
                    covers_dir = os.path.join(base_dir, "covers", str(library_id))
                    os.makedirs(covers_dir, exist_ok=True)
                    hash_source = os.path.basename(file_path) if file_path else str(book_id)
                    book_hash = hashlib.md5(hash_source.encode("utf-8")).hexdigest()
                    filename_only = f"book_{book_hash}.webp"
                    dest_path = os.path.join(covers_dir, filename_only)

                    req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as response:
                        with Image.open(io.BytesIO(response.read())) as img:
                            img.save(dest_path, "WEBP", quality=95)
                    cover_filename = f"{library_id}/{filename_only}"
                except Exception:
                    import traceback
                    print(f"[NlkBookMetadataProvider] cover save failed: {traceback.format_exc()}")
                    cover_filename = None
            elif cover_url and Image is None:
                print("[NlkBookMetadataProvider] Pillow(PIL)가 없어 표지 이미지 저장을 건너뜁니다.")

            # 화면 표시용으로 pubDate에 붙여둔 " | ISBN: ..." 접미사 제거 후 순수 날짜만 저장
            pub_date_raw = item_data.get("pubDate", "") or ""
            clean_pub_date = pub_date_raw.split(" | ISBN:")[0].replace(" *", "").strip()

            # ISBN 표준화 (특수문자/하이픈 제거, X 대문자 정렬)
            raw_isbn = item_data.get("isbn", "") or ""
            clean_isbn = re.sub(r"[^0-9X]", "", str(raw_isbn).upper())

            # HTML 태그 제거
            raw_summary = item_data.get("description") or item_data.get("summary") or ""
            final_summary = re.sub("<[^<]+?>", "", raw_summary)

            # 안전 조치: books 테이블에 'isbn' 컬럼이 실제 존재하는지 동적 확인
            columns_info = gateway.fetch_all("PRAGMA table_info(books)")
            columns = [col["name"].lower() for col in columns_info] if columns_info else []
            has_isbn_column = "isbn" in columns

            if has_isbn_column:
                gateway.execute(
                    """UPDATE books SET title = ?, author = ?, publisher = ?, summary = ?, link = ?,
                       release_date = ?, isbn = COALESCE(NULLIF(?, ''), isbn), cover_image = COALESCE(NULLIF(?, ''), cover_image),
                       cover_updated_at = CASE WHEN ? IS NOT NULL AND ? != '' THEN CURRENT_TIMESTAMP ELSE cover_updated_at END
                       WHERE id = ?""",
                    (item_data.get("title"), item_data.get("author"), item_data.get("publisher"), final_summary,
                     item_data.get("link"), clean_pub_date, clean_isbn, cover_filename, cover_filename, cover_filename, book_id),
                )
            else:
                gateway.execute(
                    """UPDATE books SET title = ?, author = ?, publisher = ?, summary = ?, link = ?,
                       release_date = ?, cover_image = COALESCE(NULLIF(?, ''), cover_image),
                       cover_updated_at = CASE WHEN ? IS NOT NULL AND ? != '' THEN CURRENT_TIMESTAMP ELSE cover_updated_at END
                       WHERE id = ?""",
                    (item_data.get("title"), item_data.get("author"), item_data.get("publisher"), final_summary,
                     item_data.get("link"), clean_pub_date, cover_filename, cover_filename, cover_filename, book_id),
                )

            return True, f"[{item_data.get('source')}] 정보가 성공적으로 적용되었습니다."
        except Exception as e:
            import traceback
            print(f"[NlkBookMetadataProvider] apply failed: {traceback.format_exc()}")
            return False, f"적용 오류: {str(e)}"

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
