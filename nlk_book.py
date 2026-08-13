# -*- coding: utf-8 -*-
"""
BookOasis metadata plugin: 국립중앙도서관 도서검색 (Seoji Open API)

unified_book 플러그인의 nlk.py 모듈
(https://raw.githubusercontent.com/yume-script/unified_book/refs/heads/main/nlk.py)
을 기반으로, 국립중앙도서관 서지정보 유통지원시스템(Seoji) API만 단독으로
쓰는 독립 메타데이터 검색 플러그인으로 재구성했습니다.

핵심 계약(kyobobook 플러그인 개발 과정에서 실제 동작하는 다른 플러그인
(unified_book)과 대조해 확인한 내용):
  - search(db_type, query)는 {'success':..., 'items':...} 로 감싸지 않고
    아이템 딕셔너리로 이루어진 "평범한 list"를 그대로 반환해야 코어가
    화면에 결과를 표시한다.
  - 아이템 딕셔너리 키: title / author / publisher / description / isbn /
    cover / link / source / pubDate.
  - apply()가 실제로 쓰는 books 테이블 컬럼: title, author, publisher,
    summary, link, release_date, isbn, cover_image, cover_updated_at.
    아이템 키 이름과 컬럼 이름이 다른 것들이 있다(description→summary,
    pubDate→release_date, cover(URL)→다운로드 후 cover_image).
"""

import hashlib
import json
import logging
import os
import re
import traceback
import urllib.parse
import urllib.request
from io import BytesIO
from logging.handlers import RotatingFileHandler

from plugins.metadata.base import BaseMetadataProvider

SEOJI_API_URL = "https://www.nl.go.kr/seoji/SearchApi.do"
REQUEST_TIMEOUT = 8
USER_AGENT = "BookOasis-NlkBook/1.0"

DEFAULTS = {
    'MAX_RESULTS': 10,
    'ENABLE_LOGGING': False,
}

# ----------------------------------------------------------------------
# 디버그 로깅 (kyobobook 플러그인과 동일한 관례: 설정의 "ENABLE_LOGGING"이
# 켜져 있을 때만 plugins/metadata/nlk_book/nlk_book_debug.log에 기록되며,
# 500KB x 최대 3개로 자동 순환된다. 이와 별개로 몇몇 핵심 지점은 항상
# print()로도 남겨서 docker logs로 바로 확인할 수 있게 했다.)
# ----------------------------------------------------------------------
_LOG_FILE_NAME = 'nlk_book_debug.log'
_logger = logging.getLogger('bookoasis.nlk_book')
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

if not _logger.handlers:
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _LOG_FILE_NAME)
        _handler = RotatingFileHandler(
            log_path, maxBytes=512 * 1024, backupCount=3, encoding='utf-8')
        _handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        _logger.addHandler(_handler)
    except Exception:
        _fallback = logging.StreamHandler()
        _fallback.setFormatter(logging.Formatter('[nlk_book] %(levelname)s %(message)s'))
        _logger.addHandler(_fallback)


# ----------------------------------------------------------------------
# Seoji 응답 -> item dict 변환 (원본 nlk.py의 _doc_to_item 로직 그대로)
# ----------------------------------------------------------------------

def _clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    return text.replace("<span>", "").replace("</span>", "")


def _format_pub_date(yyyymmdd):
    raw = (yyyymmdd or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _validate_isbn13(s):
    if len(s) != 13 or not s.isdigit():
        return False
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(s))
    return total % 10 == 0


def _validate_isbn10(s):
    if len(s) != 10:
        return False
    total = 0
    for i, ch in enumerate(s):
        if ch == 'X' and i == 9:
            val = 10
        elif ch.isdigit():
            val = int(ch)
        else:
            return False
        total += val * (10 - i)
    return total % 11 == 0


def _doc_to_item(doc):
    title = _clean(doc.get("TITLE"))
    isbn = _clean(doc.get("EA_ISBN") or doc.get("SET_ISBN"))
    intro = _clean(doc.get("BOOK_INTRODUCTION"))

    subject = _clean(doc.get("SUBJECT"))
    kdc = _clean(doc.get("KDC"))
    edition = _clean(doc.get("EDITION_STMT"))
    form = _clean(doc.get("FORM"))
    page_info = _clean(doc.get("PAGE"))
    book_size = _clean(doc.get("BOOK_SIZE"))
    price = _clean(doc.get("PRE_PRICE"))

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

    if intro:
        description = intro if not biblio_text else f"{intro}\n\n[서지정보] {biblio_text}"
    else:
        description = biblio_text

    link = ""
    if isbn:
        link = "https://www.nl.go.kr/seoji/SearchDetail.do?" + urllib.parse.urlencode({"isbn": isbn})

    return {
        "title": title,
        "author": _clean(doc.get("AUTHOR")),
        "publisher": _clean(doc.get("PUBLISHER")),
        "pubDate": _format_pub_date(doc.get("PUBLISH_PREDATE")),
        "cover": _clean(doc.get("TITLE_URL")),
        "description": description,
        "link": link,
        "source": "국립중앙도서관",
        "isbn": isbn,
    }


class NlkBookMetadataProvider(BaseMetadataProvider):
    """BookOasis 국립중앙도서관(Seoji) 도서검색 플러그인"""

    id = "nlk_book"
    name = "국립중앙도서관(NLK) 도서검색"
    is_searchable = True

    config_schema = [
        {
            "key": "NLK_CERT_KEY",
            "label": "국립중앙도서관 Seoji 인증키",
            "type": "text",
            "required": True,
        },
        {
            "key": "MAX_RESULTS",
            "label": "최대 검색결과 개수",
            "type": "number",
            "default": DEFAULTS['MAX_RESULTS'],
        },
        {
            "key": "ENABLE_LOGGING",
            "label": "디버그 로그 남기기 (plugins/metadata/nlk_book/nlk_book_debug.log)",
            "type": "checkbox",
            "default": DEFAULTS['ENABLE_LOGGING'],
        },
    ]

    # 자동 업데이트 계약: raw_base_url의 <org>/<repo>/<branch>는
    # 실제 배포할 GitHub 저장소 경로로 교체해서 사용하세요.
    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": (
            "https://raw.githubusercontent.com/<org>/<repo>/<branch>"
            "/plugins/metadata/nlk_book"
        ),
        "files": ["nlk_book.py", "__init__.py", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # ------------------------------------------------------------------
    # 디버그 로깅 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _logging_enabled(cfg):
        return bool(cfg.get('ENABLE_LOGGING', DEFAULTS['ENABLE_LOGGING']))

    @classmethod
    def _log(cls, cfg, level, msg, *args):
        if not cls._logging_enabled(cfg):
            return
        _logger.log(level, msg, *args)

    @classmethod
    def _log_exception(cls, cfg, msg, *args):
        if not cls._logging_enabled(cfg):
            return
        _logger.error(msg, *args)
        _logger.error(traceback.format_exc())

    # ------------------------------------------------------------------
    # 공통 계약: search / apply
    # ------------------------------------------------------------------

    def search(self, db_type, query):
        print(f"[NlkBookMetadataProvider] search called db_type={db_type!r} query={query!r}")
        cfg = self.get_plugin_config(db_type, default={})
        cert_key = (cfg.get('NLK_CERT_KEY') or '').strip()
        self._log(cfg, logging.INFO, '=== search() 시작: query=%r ===', query)

        q = str(query or '').strip()
        if not q:
            print("[NlkBookMetadataProvider] empty query, returning []")
            return []

        if not cert_key:
            print("[NlkBookMetadataProvider] NLK_CERT_KEY가 설정되어 있지 않습니다.")
            self._log(cfg, logging.WARNING, 'NLK_CERT_KEY가 설정되어 있지 않습니다.')
            return []

        max_results = self._as_int(cfg.get('MAX_RESULTS'), DEFAULTS['MAX_RESULTS'])
        max_results = max(1, min(30, max_results))

        clean_q = re.sub(r'[^0-9Xx]', '', q).upper()
        is_isbn = _validate_isbn13(clean_q) or _validate_isbn10(clean_q)
        print(f"[NlkBookMetadataProvider] is_isbn={is_isbn} clean_q={clean_q!r}")
        self._log(cfg, logging.DEBUG, 'is_isbn=%s clean_q=%r', is_isbn, clean_q)

        try:
            if is_isbn:
                docs = self._search_isbn(clean_q, cert_key, max_results, cfg)
            else:
                docs = self._search_title(q, cert_key, max_results, cfg)
        except Exception as e:
            print(f"[NlkBookMetadataProvider] search FAILED: {e!r}")
            import traceback as _tb
            print(_tb.format_exc())
            self._log_exception(cfg, '검색 요청 중 예외 발생: query=%r', q)
            return []

        items = [_doc_to_item(doc) for doc in docs if doc.get('TITLE')]
        print(f"[NlkBookMetadataProvider] search returning {len(items)} item(s)")
        self._log(cfg, logging.INFO, '=== search() 종료: %d건 반환 ===', len(items))
        return items

    def _search_title(self, query, cert_key, max_results, cfg):
        """제목 검색 -> 결과 없으면 저자 검색으로 재시도 (원본 nlk.py와 동일)."""
        base = {'cert_key': cert_key, 'result_style': 'json', 'page_no': 1, 'page_size': max_results}
        data = self._call_seoji({**base, 'title': query}, cfg)
        docs = data.get('docs') or []
        if not docs:
            self._log(cfg, logging.DEBUG, '제목 검색 결과 없음, 저자 검색으로 재시도: %r', query)
            data = self._call_seoji({**base, 'author': query}, cfg)
            docs = data.get('docs') or []
        return docs

    def _search_isbn(self, isbn, cert_key, max_results, cfg):
        """ISBN 검색 -> 결과 없으면 set_isbn으로 재시도 (원본 nlk.py와 동일)."""
        base = {'cert_key': cert_key, 'result_style': 'json', 'page_no': 1, 'page_size': max_results}
        data = self._call_seoji({**base, 'isbn': isbn}, cfg)
        docs = data.get('docs') or []
        if not docs:
            self._log(cfg, logging.DEBUG, 'ISBN 검색 결과 없음, set_isbn으로 재시도: %r', isbn)
            data = self._call_seoji({**base, 'set_isbn': isbn}, cfg)
            docs = data.get('docs') or []
        return docs

    def _call_seoji(self, params, cfg):
        query_string = urllib.parse.urlencode(params)
        url = f"{SEOJI_API_URL}?{query_string}"
        print(f"[NlkBookMetadataProvider] fetching {url}")
        self._log(cfg, logging.DEBUG, 'Seoji API 요청 URL: %s', url)
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status = getattr(resp, 'status', None) or resp.getcode()
            raw = resp.read().decode('utf-8', errors='replace')
        print(f"[NlkBookMetadataProvider] response status={status} body length={len(raw)}")
        self._log(cfg, logging.DEBUG, 'Seoji 응답 status=%s 본문 길이=%d', status, len(raw))
        return json.loads(raw)

    def apply(self, db_type, book_id, item_data):
        print(f"[NlkBookMetadataProvider] apply called db_type={db_type!r} book_id={book_id!r}")
        cfg = self.get_plugin_config(db_type, default={})
        self._log(cfg, logging.INFO, '=== apply() 시작: book_id=%s ===', book_id)
        if self._logging_enabled(cfg):
            self._log(cfg, logging.DEBUG, 'item_data: %r', item_data)

        if not item_data:
            self._log(cfg, logging.WARNING, 'item_data가 비어 있어 적용을 건너뜁니다.')
            return False, '적용할 메타데이터가 없습니다.'

        try:
            gateway = self.get_db_gateway(db_type)
        except Exception as e:
            print(f"[NlkBookMetadataProvider] get_db_gateway FAILED: {e!r}")
            self._log_exception(cfg, 'get_db_gateway 실패: book_id=%s', book_id)
            return False, 'DB 연결 실패: %s' % e

        # books 테이블 실제 컬럼 목록을 확인해 isbn/cover_image 등
        # 없을 수 있는 컬럼에 대한 UPDATE 오류를 피한다 (SQLite/MariaDB 둘 다 지원).
        def _try_pragma():
            info = gateway.fetch_all("PRAGMA table_info(books)")
            return [row['name'].lower() for row in info] if info else []

        def _try_show_columns():
            info = gateway.fetch_all("SHOW COLUMNS FROM books")
            return [row['Field'].lower() for row in info] if info else []

        columns = []
        for attempt in (_try_pragma, _try_show_columns):
            try:
                columns = attempt()
                if columns:
                    break
            except Exception as e:
                print(f"[NlkBookMetadataProvider] column introspection attempt failed: {e!r}")
                continue
        self._log(cfg, logging.DEBUG, 'books 테이블 컬럼: %r', columns)

        # 표지: 원격 URL을 다운로드해 covers/<library_id>/ 아래에 webp로
        # 저장하고 그 상대경로를 cover_image 컬럼에 넣는다.
        cover_rel_path = None
        cover_url = item_data.get('cover')
        if cover_url and 'cover_image' in columns:
            cover_rel_path = self._download_cover(gateway, book_id, cover_url, cfg)

        set_parts = []
        params = []

        def _add(col, value):
            if col in columns or not columns:
                set_parts.append('%s = ?' % col)
                params.append(value)

        if item_data.get('title'):
            _add('title', item_data['title'])
        if item_data.get('author'):
            _add('author', item_data['author'])
        if item_data.get('publisher'):
            _add('publisher', item_data['publisher'])
        if item_data.get('description') and 'summary' in columns:
            _add('summary', item_data['description'])
        if item_data.get('link') and 'link' in columns:
            _add('link', item_data['link'])
        if item_data.get('pubDate') and 'release_date' in columns:
            _add('release_date', item_data['pubDate'])
        if item_data.get('isbn') and 'isbn' in columns:
            _add('isbn', item_data['isbn'])
        if cover_rel_path:
            _add('cover_image', cover_rel_path)
            if 'cover_updated_at' in columns:
                set_parts.append('cover_updated_at = CURRENT_TIMESTAMP')

        if not set_parts:
            self._log(cfg, logging.WARNING, '적용 가능한 필드가 없습니다. item_data=%r', item_data)
            return False, '적용할 메타데이터가 없습니다.'

        try:
            sql = 'UPDATE books SET %s WHERE id = ?' % ', '.join(set_parts)
            self._log(cfg, logging.DEBUG, 'SQL: %s / params=%r', sql, params + [book_id])
            gateway.execute(sql, params + [book_id])
            print(f"[NlkBookMetadataProvider] apply() DB update OK for book_id={book_id!r}")
            self._log(cfg, logging.INFO, 'apply() 성공: book_id=%s', book_id)
            return True, '[국립중앙도서관] 정보가 성공적으로 적용되었습니다.'
        except Exception as e:
            print(f"[NlkBookMetadataProvider] apply() DB update FAILED: {e!r}")
            self._log_exception(cfg, 'apply() 중 DB 반영 실패: book_id=%s', book_id)
            return False, '메타데이터 적용 실패: %s' % e

    def _download_cover(self, gateway, book_id, cover_url, cfg):
        """표지 이미지를 내려받아 covers/<library_id>/ 아래에 webp로 저장하고,
        DB의 cover_image 컬럼에 넣을 상대경로를 반환한다. Pillow가 없거나
        실패하면 None을 반환한다(적용 자체는 계속 진행됨)."""
        try:
            from PIL import Image
        except ImportError:
            self._log(cfg, logging.WARNING,
                       'Pillow가 설치되어 있지 않아 표지 다운로드를 건너뜁니다. '
                       'requirements.txt에 Pillow를 추가하고 플러그인을 재설치하세요.')
            return None

        try:
            book = gateway.fetch_one(
                'SELECT file_path, library_id FROM books WHERE id = ?', (book_id,))
            if not book:
                return None
            file_path = book['file_path'] if 'file_path' in book.keys() else book.get('file_path')
            library_id = book['library_id'] if 'library_id' in book.keys() else book.get('library_id')

            base_dir = os.path.abspath(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
            covers_dir = os.path.join(base_dir, 'covers', str(library_id))
            os.makedirs(covers_dir, exist_ok=True)

            name_for_hash = os.path.basename(file_path) if file_path else str(book_id)
            book_hash = hashlib.md5(name_for_hash.encode('utf-8')).hexdigest()
            cover_filename = 'book_%s.webp' % book_hash
            dest_path = os.path.join(covers_dir, cover_filename)

            req = urllib.request.Request(cover_url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read()
            with Image.open(BytesIO(raw)) as img:
                img.save(dest_path, 'WEBP', quality=95)

            self._log(cfg, logging.DEBUG, '표지 저장 완료: %s', dest_path)
            return '%s/%s' % (library_id, cover_filename)
        except Exception:
            self._log_exception(cfg, '표지 다운로드/저장 실패: book_id=%s url=%s', book_id, cover_url)
            return None

    @staticmethod
    def _as_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
