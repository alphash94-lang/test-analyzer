# 실제 응답 fixture 확보 상태

검사일: 2026-07-30 KST

## 현재 상태

**미확보**

검수 환경에 KRX, OpenDART, 한국투자증권, NAVER API HUB와 ECOS
인증정보가 없고 운영 DB의 실제 원응답도 0건이다. 따라서 실제 응답 기반
JSON·XML·ZIP fixture를 만들지 않았다. 계약형 mock payload나 공식 문서의
예시를 실제 응답 fixture로 이름만 바꾸어 저장하지 않는다.

## provider별 상태

| provider | 실제 fixture | 이유 |
|---|---|---|
| KRX 종목·가격·KOSPI 지수 | 미확보 | `KRX_API_KEY` 미설정 |
| OpenDART 고유번호·공시·재무·배당·감사 | 미확보 | `DART_API_KEY` 미설정 |
| 한국투자증권 참고 데이터 | 미확보 | 앱키·시크릿 미설정 |
| NAVER API HUB 뉴스 | 미확보 | API HUB 키 2종 미설정 |
| ECOS | 미확보 | 키 미설정, adapter 미구현 |
| KIND | 미확보 | 공식 공개 API 계약과 자동수집 권한 미확인 |

## 향후 확보 절차

1. provider별 정식 이용신청과 읽기 전용 인증정보를 준비한다.
2. 실제 종목 한 건의 최소 호출을 실행한다.
3. HTTP 2xx, 요청 기준일·응답 기준일, content type과 schema를 검증한다.
4. 인증 header, query parameter, 토큰, 계좌번호와 개인식별정보를 제거한다.
5. 원본 응답 SHA-256을 별도 메타데이터에 기록한다.
6. 운영 parser가 같은 결과를 만드는지 검증한 뒤 fixture로 고정한다.
7. 응답 재배포가 provider 이용조건상 허용되는지 확인한다.

실제 fixture가 추가되면 이 문서의 `미확보` 상태와
`docs/KNOWN_LIMITATIONS.md`를 함께 갱신해야 한다.
