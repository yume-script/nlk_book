# 국립중앙도서관(NLK) 도서검색 플러그인

BookOasis의 `plugins/metadata/` 계약(가이드: `docs/guide_plugins.md`, 참고 샘플: `naver_book`)을
따라 만든 **검색형 메타데이터 플러그인**입니다.
국립중앙도서관 서지정보 유통지원시스템(Seoji) Open API로 실제 도서 검색과
메타데이터 적용(제목/저자/출판사/ISBN/요약)이 가능하며,
API 키 없이도 도서 컨텍스트 메뉴에서 NLK 통합검색 페이지를 바로 열 수 있습니다.

## 1. 설치

`plugins/metadata/nlk_book/` 폴더를 통째로 BookOasis 서버의 `plugins/metadata/` 아래에 복사합니다.

```text
plugins/metadata/
  nlk_book/
    __init__.py
    nlk_book.py
    VERSION
    README.md   (선택, 없어도 동작에는 영향 없음)
```

서버를 재시작하면 플러그인이 자동으로 로드됩니다.

## 2. 인증키 발급 (검색 기능에 필요)

1. https://www.nl.go.kr/seoji/ 접속
2. Open API 인증키 신청 (무료, 승인까지 다소 시간이 걸릴 수 있음)
3. 발급받은 인증키를 복사

## 3. 활성화 및 설정

1. BookOasis 웹 UI > 환경설정 > 플러그인 설정으로 이동
2. `국립중앙도서관 도서검색` 플러그인 활성화
3. `Seoji 인증키` 항목에 발급받은 키 입력 후 저장
4. (선택) `검색 결과 개수` 조정 (기본 20, 최대 100)

## 4. 사용 방법

### 4-1. 수동 메타데이터 검색
- 도서 상세 화면 > 메타데이터 검색 모달에서 제목으로 검색하면
  국립중앙도서관 서지정보가 검색 결과에 표시됩니다.
- 원하는 항목을 선택해 적용하면 제목/저자/출판사/ISBN/요약 정보가 반영됩니다.
- 제목으로 결과가 없으면 통합 키워드 검색으로 한 번 더 자동 재시도합니다.

### 4-2. 컨텍스트 메뉴 (인증키 없이도 동작)
- 도서 카드 우클릭(또는 메뉴 버튼) > `국립중앙도서관 통합검색에서 열기`
- 현재 도서의 제목/저자로 NLK 통합검색 결과 페이지를 새 탭으로 엽니다.

## 5. 자동 업데이트

`update_manifest`에 선언된 `raw_base_url`은 아래 경로를 가리킵니다.

```
https://raw.githubusercontent.com/leeyj/BookOasis_stable/refs/heads/main/plugins/metadata/nlk_book
```

실제로 이 저장소에 플러그인을 커밋/푸시한 뒤에만 자동 업데이트 버튼이 정상 동작합니다.
다른 저장소를 사용한다면 `nlk_book.py`의 `update_manifest["raw_base_url"]` 값을 실제 경로로 수정하세요.
버전을 올릴 때는 `VERSION` 파일의 `"plugin version"` 값도 함께 증가시켜야 합니다.

## 6. 필드 매핑 (공식 가이드 기준)

| Seoji 응답 필드 | 의미 | 매핑 대상 |
|---|---|---|
| TITLE | 표제 | title |
| AUTHOR | 저자 | author |
| PUBLISHER | 발행처 | publisher |
| EA_ISBN / SET_ISBN | ISBN | isbn |
| PUBLISH_PREDATE | 출판예정일(yyyymmdd) | pub_date (yyyy-mm-dd로 변환) |
| TITLE_URL | 표지이미지 URL | cover_url |
| SUBJECT / KDC / EDITION_STMT / PAGE / BOOK_SIZE / FORM / PRE_PRICE | 부가 서지정보 | summary에 조합 |

`books` 테이블에 `pub_date`, `cover_url` 컬럼이 없다면 `apply()`에서 해당 필드 반영이
무시되거나 오류가 날 수 있으니, 스키마에 맞게 `nlk_book.py`의 `apply()` 매핑을 조정하세요.

## 7. 에러 코드

국립중앙도서관 공식 가이드에 명시된 에러 코드를 한글 메시지로 변환해 반환합니다.

| 코드 | 의미 |
|---|---|
| 000 | 시스템 오류 |
| 010 | 인증키값 누락 |
| 011 | 유효하지 않은 인증키 |
| 012 | 필수 파라미터 입력 누락 |

※ 실제 에러 응답의 JSON 키 이름이 공식 문서에 명시되어 있지 않아,
`ERROR_CODE`/`ERR_CODE`/`errorCode`/`error_code`/`RESULT_CODE` 등 후보 키를 방어적으로
확인합니다. 실제 서버 응답을 확인한 뒤 `_extract_error_code()`를 정확한 키로 조정하는 것을 권장합니다.

## 8. 참고

- Seoji API 문서: https://www.nl.go.kr/seoji/ (Open API 활용방법 페이지)
- 응답 필드는 국립중앙도서관 정책에 따라 예고 없이 바뀔 수 있습니다.
  변경 시 `_doc_to_item()` 매핑 부분만 수정하면 됩니다.
