# 국립중앙도서관 도서검색 플러그인 (BookOasis)

[unified_book](https://github.com/yume-script/unified_book) 플러그인의
`nlk.py`(국립중앙도서관 서지정보 유통지원시스템, Seoji Open API 검색 모듈)를
바탕으로, Seoji API만 단독으로 쓰는 독립 메타데이터 검색 플러그인으로
재구성했습니다.

## 핵심 계약 (kyobobook 플러그인 개발 중 확인된 실제 동작)

- `search(db_type, query)`는 `{'success':..., 'items':...}`로 감싸지 않고
  **아이템 딕셔너리로 이루어진 평범한 `list`를 그대로 반환**해야 코어가
  화면에 결과를 표시합니다. (다른 실제 동작하는 플러그인 `unified_book`과
  대조해 확인했습니다.)
- 아이템 딕셔너리 키: `title` / `author` / `publisher` / `description` /
  `isbn` / `cover` / `link` / `source` / `pubDate`.
- `apply()`가 실제로 쓰는 `books` 테이블 컬럼: `title`, `author`,
  `publisher`, `summary`, `link`, `release_date`, `isbn`, `cover_image`,
  `cover_updated_at`. 아이템 키 이름과 컬럼 이름이 다른 것들이 있습니다
  (`description`→`summary`, `pubDate`→`release_date`, `cover`(원격 URL)→
  다운로드 후 `cover_image`(로컬 상대경로)).

## 검색 동작

1. 검색어가 유효한 ISBN-13/ISBN-10(체크섬 검증 포함)이면 Seoji의
   `isbn` 파라미터로 조회하고, 결과가 없으면 `set_isbn`으로 재시도합니다.
2. ISBN이 아니면 `title` 파라미터로 조회하고, 결과가 없으면 `author`
   파라미터로 재시도합니다(원본 `nlk.py`와 동일한 폴백 순서).
3. Seoji 응답의 각 `doc`을 아이템 딕셔너리로 변환합니다:
   - `TITLE`/`AUTHOR`/`PUBLISHER`/`PUBLISH_PREDATE`(YYYYMMDD→YYYY-MM-DD)/
     `TITLE_URL`(표지)/`EA_ISBN`(또는 `SET_ISBN`)을 그대로 매핑
   - `BOOK_INTRODUCTION`(책소개)에 `SUBJECT`/`KDC`/`EDITION_STMT`/`FORM`/
     `PAGE`/`BOOK_SIZE`/`PRE_PRICE`를 "[서지정보] ..." 한 줄로 덧붙여
     `description`으로 구성
   - `link`은 ISBN이 있으면 Seoji 상세조회 페이지 URL을 생성

## 설정 항목

- **국립중앙도서관 Seoji 인증키** (`NLK_CERT_KEY`, 필수): 국립중앙도서관
  서지정보유통지원시스템(https://www.nl.go.kr/seoji/)에서 발급받은
  인증키를 입력해야 검색이 동작합니다. 비어 있으면 `search()`는 빈
  결과를 반환합니다(요청 자체를 보내지 않음).
- **최대 검색결과 개수** (`MAX_RESULTS`, 기본 10): Seoji API의
  `page_size` 파라미터로 그대로 전달됩니다.
- **디버그 로그 남기기** (`ENABLE_LOGGING`, 기본 꺼짐): 켜면
  `plugins/metadata/nlk_book/nlk_book_debug.log`에 요청 URL/응답 상태·
  길이/파싱 결과 등이 기록됩니다(500KB × 최대 3개 자동 순환). 이와
  별개로 핵심 지점은 로그 설정과 무관하게 항상 `print()`로도 남아
  `docker logs`로 바로 확인할 수 있습니다.

## `apply()` 동작

`books` 테이블의 실제 컬럼을 `PRAGMA table_info(books)`(SQLite) 또는
`SHOW COLUMNS FROM books`(MariaDB)로 확인한 뒤, 존재하는 컬럼에만 값을
씁니다. 표지(`cover`)는 URL을 그대로 저장하지 않고 Pillow로 내려받아
webp로 변환한 후 `covers/<library_id>/book_<해시>.webp`에 저장하고 그
상대경로를 `cover_image`에 넣습니다. Pillow가 없으면 표지만 건너뛰고
나머지 필드(제목/저자/출판사/책소개/링크/발행일/ISBN)는 정상 적용됩니다.

## 설치

1. `nlk_book/` 폴더를 BookOasis 서버의 `plugins/metadata/` 아래에 복사합니다.
2. 서버를 재시작해 `requirements.txt`(Pillow)가 설치되는지 확인합니다.
3. 환경설정 > 플러그인 설정 > "국립중앙도서관 도서검색"에서 Seoji
   인증키를 입력하고 저장합니다.
4. `is_searchable = True`이므로 수동 메타데이터 검색 모달에 자동 노출됩니다.

## 자동 업데이트 설정

`nlk_book.py`의 `update_manifest['raw_base_url']`에 있는
`<org>/<repo>/<branch>`를 실제 배포할 GitHub 저장소 경로로 교체하세요.

## 파일 구성

```text
nlk_book/
  __init__.py        # Provider 클래스를 패키지 이름공간에 노출
  nlk_book.py         # search()/apply() 및 Seoji API 연동 로직
  VERSION             # 자동 업데이트용 버전 파일
  requirements.txt    # Pillow (표지 다운로드/변환용)
  README.md           # 이 문서
```

## 참고 / 한계

- 이 컨테이너는 `nl.go.kr`로 나가는 네트워크가 허용되어 있지 않아 실제
  Seoji API를 상대로 한 라이브 테스트는 하지 못했습니다. 대신
  `urllib.request.urlopen`을 모킹(mock)해 제목 검색/ISBN 검색/인증키
  누락/빈 검색어 네 가지 경로와, 실제 `books` 컬럼명을 흉내 낸 가짜
  DB 게이트웨이로 `apply()`의 SQL 생성까지 전부 테스트해 통과를
  확인했습니다.
- Seoji API의 정확한 파라미터명/응답 필드명은 원본 `nlk.py`(unified_book
  플러그인 저자가 이미 검증해 둔 코드)를 그대로 신뢰해 옮겼습니다.
- ISBN 판별은 자체 체크섬 검증(ISBN-13/ISBN-10)을 포함합니다.
