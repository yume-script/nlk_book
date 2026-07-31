# 국립중앙도서관(NLK) ISBN 서지정보 Open API 가이드

> 출처: 국립중앙도서관 누리집 &gt; 도서관 서비스 &gt; 이용자 &gt; Open API &gt; 활용방법 &gt; ISBN 서지정보
> (https://www.nl.go.kr/NL/contents/N31101030500.do)
>
> 이 문서는 `plugins/metadata/nlk_book` 플러그인이 사용하는 국립중앙도서관 서지정보
> 유통지원시스템(Seoji) Open API의 공식 명세를 정리한 것입니다. `nlk_book.py`의 요청
> 파라미터/응답 필드 매핑(`_doc_to_item`, `search`)을 수정할 때 이 문서를 기준으로 삼으세요.

## 담당 부서

디지털정보기획과 (02-590-0548)

## 개요

- 서비스명: ISBN 서지정보 목록 정보
- 일반검색 요청 URL: `https://www.nl.go.kr/seoji/SearchApi.do`
- 미납본 목록(구:출판예정도서): `https://www.nl.go.kr/seoji/SearchApi.do?deposit_yn=N`

## 요청 변수 (Request Parameters)

| NO | 요청변수 | 형식 | 설명 |
|---|---|---|---|
| 1 | `cert_key` | String (필수) | 인증키 |
| 2 | `result_style` | String (필수) | 결과 형식 (`json`, `xml`) |
| 3 | `page_no` | Integer (필수) | 현재 쪽번호 (페이지 1부터 시작) |
| 4 | `page_size` | Integer (필수) | 쪽당 출력 건수 |
| 5 | `isbn` | String | ISBN |
| 6 | `set_isbn` | String | SET ISBN |
| 7 | `ebook_yn` | String | 전자책 여부 (Y, N) |
| 8 | `title` | String | 본표제 |
| 9 | `start_publish_date` | String | 발행예정일 시작 (8자리, `yyyymmdd`) |
| 10 | `end_publish_date` | String | 발행예정일 끝 (8자리, `yyyymmdd`) |
| 11 | `cip_yn` | String | CIP 신청여부 (Y, N) |
| 12 | `deposit_yn` | String | 납본 유무 (Y, N) |
| 13 | `series_title` | String | 총서명 |
| 14 | `publisher` | String | 발행처명 |
| 15 | `author` | String | 저자 |
| 16 | `form` | String | 형태사항 (종이책, 혼합자료, 전자책, 오디오북, 기타 전자출판물, 다양한 제본형태, 다양한 형식혼합 세트) |
| 17 | `sort` | String | 정렬 기준: `PUBLISH_PREDATE`, `INPUT_DATE`, `INDEX_TITLE`, `INDEX_PUBLISHER` |
| 18 | `order_by` | String | 정렬 방식: `ASC`, `DESC` |

### API 샘플 URL

```
https://www.nl.go.kr/seoji/SearchApi.do?cert_key=[발급된키값]&result_style=json&page_no=1&page_size=10&start_publish_date=20220509&end_publish_date=20220509
```

## 출력 결과 항목 (Response Fields)

| NO | 필드 | 값 | 설명 |
|---|---|---|---|
| 1 | `PAGE_NO` | String | 현재 쪽번호 |
| 2 | `TOTAL_COUNT` | String | 전체 출력수 |
| 3 | `TITLE` | String | 표제 |
| 4 | `VOL` | String | 권차 |
| 5 | `SERIES_TITLE` | String | 총서명 |
| 6 | `SERIES_NO` | String | 총서편차 |
| 7 | `AUTHOR` | String | 저자 |
| 8 | `EA_ISBN` | String | ISBN |
| 9 | `EA_ADD_CODE` | String | ISBN 부가기호 |
| 10 | `SET_ISBN` | String | 세트 ISBN |
| 11 | `SET_ADD_CODE` | String | 세트 ISBN 부가기호 |
| 12 | `SET_EXPRESSION` | String | 세트 표현 (세트, 전2권 등) |
| 13 | `PUBLISHER` | String | 발행처 |
| 14 | `EDITION_STMT` | String | 판사항 |
| 15 | `PRE_PRICE` | String | 예정가격 |
| 16 | `KDC` | String | 한국십진분류 (2020년 12월 31일 이후 데이터 제공 불가) |
| 17 | `DDC` | String | 듀이십진분류 |
| 18 | `PAGE` | String | 페이지 |
| 19 | `BOOK_SIZE` | String | 책 크기 |
| 20 | `FORM` | String | 발행제본형태 |
| 21 | `PUBLISH_PREDATE` | String | 출판예정일 |
| 22 | `SUBJECT` | String | 주제 (KDC 대분류) |
| 23 | `EBOOK_YN` | String | 전자책 여부 (Y: 전자책, N: 인쇄책) |
| 24 | `CIP_YN` | String | CIP 신청여부 (Y: CIP 신청, N: CIP 신청안함) |
| 25 | `CONTROL_NO` | String | CIP 제어번호 |
| 26 | `TITLE_URL` | String | 표지이미지 URL |
| 27 | `BOOK_TB_CNT_URL` | String | 목차 |
| 28 | `BOOK_INTRODUCTION_URL` | String | 책소개 |
| 29 | `BOOK_SUMMARY_URL` | String | 책요약 |
| 30 | `PUBLISHER_URL` | String | 출판사 홈페이지 URL |
| 31 | `INPUT_DATE` | String | 등록날짜 |
| 32 | `UPDATE_DATE` | String | 수정날짜 |

> ※ 제공 서비스에 따라 출력결과 필드는 제한될 수 있습니다.

## 에러 메시지

| 에러코드 | 설명 |
|---|---|
| 000 | 시스템 오류 |
| 010 | 인증키값 누락 |
| 011 | 유효하지 않은 인증키 |
| 012 | 필수 파라메터 입력 누락 |

## 관련 단체

국립중앙도서관 — (06579) 서울특별시 서초구 반포대로 201 (반포동)
대표전화 02-590-0500 (운영시간: 09:00~18:00, 휴관일/공휴일 제외) · 팩스 02-590-0530

---

## `nlk_book` 플러그인과의 매핑 참고

`plugins/metadata/nlk_book/nlk_book.py`에서 사용 중인 매핑은 다음과 같습니다.

| Seoji 필드 | 플러그인 item 필드 |
|---|---|
| `TITLE` | `title` |
| `AUTHOR` | `author` |
| `PUBLISHER` | `publisher` |
| `EA_ISBN` / `SET_ISBN` | `isbn` |
| `PUBLISH_PREDATE` | `pub_date` (`yyyy-mm-dd`로 변환) |
| `TITLE_URL` | `cover_url` |
| `SUBJECT`, `KDC`, `EDITION_STMT`, `PAGE`, `BOOK_SIZE`, `FORM`, `PRE_PRICE` | `summary` (조합) |

플러그인의 `search()`는 `title` 파라미터로 우선 검색하고, 결과가 없으면 `author` 파라미터로
한 번 더 재시도합니다. `kwd`(통합 키워드) 파라미터는 위 공식 명세에 없으므로 사용하지 않습니다.
