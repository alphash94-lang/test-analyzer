# 알려진 제약

## L-062 Phase 7 독립 검수 후 남은 위험

- 2026-07-30 독립 검수에서도 KRX, OpenDART, 한국투자증권,
  NAVER API HUB와 ECOS 인증정보가 모두 미설정이었다. KIND는 공식
  자동 수집 계약이 확정되지 않아 `DEFERRED`다. 외부 HTTP 성공,
  실제 기준일, 실제 필드·단위·pagination·호출 제한과 실제 응답 fixture는
  검증하지 못했다.
- 전체 213개 pytest, Phase 7 20개 테스트, 데이터 진실성 표적 24개
  테스트는 통과했다. 이는 계약형 fixture와 무키·무데이터 경로의
  검증이며 실제 데이터 완료를 의미하지 않는다.
- 공식 수정가격·산업분류·반도체 구성과 완전한 과거 point-in-time
  corpus가 없다. 실제 RSI, 산업 비교, 시장충격 분석, 상장폐지 포함
  생존편향 제거 백테스트 완료를 주장할 수 없다.
- 실제 PostgreSQL migration·backup/restore, 다중 process 동시 upsert,
  장기 운영과 provider별 장애 복구는 검증하지 못했다.
- 현재 작업 폴더에 `.git` 메타데이터가 없어 `.gitignore`의 `.env`
  규칙과 실제 `.env` 부재만 확인했다. tracked secret 이력과 기준
  revision diff는 검증할 수 없다.
- 두 CLI의 최상위 예외 출력은 설정된 credential까지 마스킹하도록
  수정하고 회귀 테스트를 추가했다. 다만 제3자 library가 logging
  경계를 우회해 직접 출력하는 경우까지 통제하는 중앙 비밀관리
  시스템은 아니다.
- `pyproject.toml`에 선언된 dependency는 모두 import됐지만 선언되지
  않고 source에서도 사용하지 않는 Plotly는 설치돼 있지 않다.
  PowerShell `Start-Process`는 검수 환경의 `Path`/`PATH` 중복 key로
  launch 전에 실패했으며, 같은 Streamlit entrypoint를 hidden Python
  subprocess로 실행해 HTTP 200을 확인했다.
- `event_service.py`, `event_repository.py`, `stock_analysis_service.py`,
  `recommendation_service.py` 등 500행 이상 파일이 남아 있다. 이번
  검수에서 provider/service 책임 혼합이나 순환 import는 발견되지
  않았지만 후속 유지보수 시 역할별 분리를 검토해야 한다.

## L-060 Phase 7 실제 배포 검증의 외부 조건

- 2026-07-30 Phase 7 검수 환경에는 KRX, OpenDART, 한국투자증권,
  NAVER API HUB와 ECOS 인증정보가 없다. 실제 외부 HTTP 성공, 응답 hash,
  실제 데이터 기준일과 provider별 값 집합·단위·호출 제한을 검증하지
  못했다.
- 실제 원응답이 0건이므로 실제 응답 기반 fixture는 미확보다.
  계약형 mock이나 공식 문서 예시를 실제 fixture로 위장하지 않고
  `tests/fixtures/REAL_RESPONSE_STATUS.md`에 후속 확보 절차만 기록했다.
- 공식 수정가격 writer, 공식 산업분류 writer, 공식 반도체 구성과 완전한
  과거 point-in-time corpus가 없다. 실제 RSI, 산업 중앙 PER·PBR,
  반도체/비반도체 분석과 생존편향 제거 백테스트 완료를 주장할 수 없다.
- `FINAL_COMPLETION_CHECKLIST.md`의 20개 기준은 충족 5개, 부분 충족 3개,
  API 키 또는 외부 데이터 필요 9개, 현재 API 제공 범위에서 구현 곤란
  3개다. 미충족 0개만으로 전체 완료를 의미하지 않는다.

## L-061 Phase 7 운영·보안 검증 범위

- SQLite 기존 DB·새 빈 DB·복구본의 migration, 무결성, 전체 213개 pytest,
  Ruff, Pyright, compileall, 109개 module import, 무키 CLI·AppTest와 실제
  Streamlit HTTP 200은 검증했다.
- SQLite 파일 복사 백업·복구는 SHA-256과 migration head를 확인했지만
  실제 PostgreSQL migration·`pg_dump`/`pg_restore`, timezone·NUMERIC,
  다중 process 동시 upsert와 장기 운영은 검증하지 못했다.
- 최신성 경고는 마지막 성공 원응답의 수집시각과 공통
  `DATA_FRESHNESS_WARNING_HOURS`를 비교한다. provider별 공식 배포주기,
  장 휴장일과 응답 내부의 실제 데이터 기준일을 완전히 판정하지 않는다.
- 동일 process·transaction의 원응답 중복 저장은 flush와 회귀 테스트로
  보정했고 DB unique 제약이 최종 중복을 막는다. 다중 process가 같은
  원응답을 동시에 저장할 때의 unique 충돌 재시도는 실제 운영 DB에서
  검증하지 못했다.
- credential assignment, Bearer token, DB URL 사용자정보와 설정된 secret
  값의 log 마스킹을 추가했지만 제3자 library가 logging 체계를 우회해
  파일·stderr에 직접 출력하는 경우까지 통제하는 중앙 비밀관리 시스템은
  아니다.
- 현재 작업 폴더와 이전 프로젝트에는 `.git` 메타데이터가 없다.
  `.gitignore`의 `.env` 규칙과 실제 `.env` 부재는 확인했지만
  `git check-ignore`, tracked secret 이력과 기준 revision diff는 검증할
  수 없다.
- `event_service.py`, `event_repository.py`, `stock_analysis_service.py`,
  `recommendation_service.py` 등 500행 이상 파일이 남아 있다. provider와
  service 책임 혼합이나 순환 import는 발견되지 않았으나 후속 유지보수 시
  역할별 분리를 검토해야 한다.

## L-056 Phase 5 독립 검수 후 남은 실제 데이터 검증 범위

- 2026-07-30 검수 환경에는 `DART_API_KEY`,
  `NCP_APIGW_API_KEY_ID`·`NCP_APIGW_API_KEY`,
  `KIS_APP_KEY`·`KIS_APP_SECRET`가 없다. 따라서 OpenDART, NAVER API HUB,
  한국투자증권의 실제 인증 HTTP 요청과 실제 종목 결과는 검증하지 못했다.
- KIND는 공식 공개 API 계약과 자동 수집 권한이 확인되지 않아 계속
  `UNSUPPORTED`이며 임의 endpoint를 만들지 않는다.
- KIS 응답의 `tr_cont=M/F`는 다음 페이지가 있음을 뜻하므로 현재 구현은
  `PARTIAL_RESPONSE_UNSUPPORTED`로 전체 정규화를 중단한다. 부분 결과를
  정상 데이터로 저장하지는 않지만, 실제 연속조회 수집은 아직 지원하지 않는다.
- NAVER 뉴스 검색 공식 응답에는 언론사 필드가 없다. URL 호스트를 언론사로
  추정하지 않으며 `publisher`는 확인 불가로 남는다.
- 뉴스 관련성 필터는 종목명의 제목·제공 요약 포함 여부를 사용한다. 이름이 다른
  회사명의 접두어인 종목은 오탐 가능성이 있으므로 실제 결과 대조가 필요하다.
- OpenDART 공시검색은 접수일만 제공하므로 정확한 접수시각을 만들지 않고
  `접수일, 시각 미제공`으로 표시한다.

## L-057 Phase 5 운영·유지보수 검증 범위

- SQLite 빈 DB와 기본 DB migration은 검증했지만 실제 PostgreSQL 서버의 DDL,
  `NUMERIC`·timezone·동시 upsert 동작은 검증하지 못했다.
- 실제 KOSPI 전 종목의 증분수집, KIS 연속조회, 반복수집, API rate limit 및
  대량 데이터 성능은 검증하지 못했다.
- 현재 프로젝트 디렉터리에는 `.git` metadata가 없어 `git status`와 기준
  revision 대비 diff를 사용할 수 없다. 검수는 문서, 파일시각, 정적 분석,
  실행 결과를 기준으로 수행했다.
- `event_service.py`는 약 900줄, `event_repository.py`는 약 700줄이다.
  provider와 service 책임 혼합이나 순환 import는 발견되지 않았지만 후속
  유지보수 전에 수집 orchestration과 조회 projection의 분리를 검토할 필요가 있다.

## L-001 실제 API 연결 미검증

- KRX, OpenDART, 한국투자증권, NAVER API HUB, 한국은행 ECOS 인증정보가 설정되어 있지 않다.
- 인증형 API 호출을 수행하지 않았고 성공한 HTTP 상태, 실제 응답 스키마, 응답 해시가 없다.
- 공식 문서에 계약이 있어도 실제 응답을 검증하기 전 운영 상태는 `NOT_VERIFIED`다.

## L-002 KIND 공개 API 계약 미확인

- KIND 공식 사이트에서 관리종목, 거래정지, 불성실공시, 투자주의·경고·위험, 상장폐지, 배당, 자사주, 밸류업 화면을 확인했다.
- 공식 공개 API의 endpoint, method, 인증, 요청·응답 필드, 호출 제한은 확인하지 못했다.
- 별도 계약·권한과 이용조건을 확인하기 전 자동 provider나 화면 내부 경로 기반 수집을 구현할 수 없다.

## L-003 KRX 공개 계약 범위

- 유가증권 종목기본정보, 일별매매정보, KOSPI 시리즈 일별시세 계약은 확인했다.
- 관리종목·투자주의/경고/위험·거래정지 이력, 공매도, 투자자별 거래, 프로젝트에 맞는 공식 반도체 지수의 공개 계약은 확정하지 못했다.
- 종목기본정보의 `SECT_TP_NM`은 공식 명세상 `소속부`다. 산업분류가 아니며, 공식 산업분류 계약이 확인될 때까지 반도체 프록시와 산업 중앙값 계산을 보류한다.
- KRX 기능 명세의 일부 수치 필드는 단위가 명시되지 않아 실제 응답과 공식 데이터 사전 대조가 필요하다.

## L-004 한국투자증권 확장 기능 계약 미완료

- 현재가와 일·주·월·년 기간별시세 계약은 확인했다.
- 종목투자의견·목표주가, 종목별 투자자 일별매매, KOSPI 프로그램매매
  일별 종합, 종목 공매도 일별추이는 공식 예제의 endpoint·TR ID·사용
  응답 필드를 검증해 Phase 5 adapter를 구현했다.
- EPS 추정실적, 대차·신용, 실시간 WebSocket과 배당일정은 앱에서
  안전하게 정규화할 필드 의미·단위 계약을 확정하지 못했다.
- REST 현재가는 공식 계약상 실시간 WebSocket과 구분되므로 실시간 체결가라고 표시할 수 없다.

## L-005 OpenDART 구조화 데이터의 한계

- `alotMatter` 배당 데이터는 `se` 행별 의미와 단위가 달라 실제 응답 사전이 필요하다.
- 현금·현물배당결정은 이번 검증에서 구조화 endpoint를 확인하지 못해 공시검색과 원문 파싱이 필요하다.
- 기업 확장 XBRL 계정, 주석, 금융업 규제비율, 계속기업 관련 문맥은 원문 파싱과 계정 매핑이 필요하다.
- 정정공시는 원본을 덮어쓰지 않고 접수번호별로 보존해야 한다.

## L-006 NAVER 뉴스 데이터 범위와 전환

- 뉴스 검색은 기사 제목, 요약 패시지, 제공시각, 링크만 제공하며 본문 전체를 제공하지 않는다.
- 개발자센터 레거시 Search API는 2026-07-30 24:00 신규 신청이 종료되고 기존 신청 지원은 2027-06-30 24:00에 종료될 예정이다.
- 신규 운영 연동은 NAVER API HUB 계약과 NCP 인증정보가 필요하다.

## L-007 ECOS 시리즈별 추가 검증

- `StatisticSearch` 공통 계약과 단위 필드 `UNIT_NAME`은 확인했다.
- 기준금리·국고채·환율·경기지표의 정확한 통계표코드, 항목코드, 제공기간과 갱신주기는 아직 확정하지 않았다.
- 상업적 이용 제한이 있는 통계는 원 통계작성기관의 승인이 필요할 수 있다.

## L-008 라이선스와 재배포

- KRX Open API 데이터는 비상업적 이용, 출처 표시, 제3자 제공 제한이 있으며 재배포·영리·실시간 이용은 별도 계약이 필요할 수 있다.
- KIND 자동 수집, 한국투자증권 데이터의 제3자 서비스 제공, 뉴스 장기 저장·재배포 범위는 각 이용조건과 계약을 추가 확인해야 한다.
- 원자료의 내부 보존과 외부 재배포를 동일한 권리로 간주하지 않는다.

## L-009 실제 외부 데이터 없음

- 시장, 종목, 가격, 재무, 배당, 감사, 공시, 뉴스, 수급 원자료가 없다.
- 확인된 실제 데이터 기준일이 없다.
- KRX 종목·일별가격과 OpenDART 고유번호 provider 및 수집 service는
  구현되어 있으나 인증키가 없어 실제 응답은 수집하지 못했다.
- Phase 5 한국투자증권 참고 데이터와 NAVER API HUB provider는
  구현되어 있으나 인증정보가 없어 실제 응답은 수집하지 못했다.
- ECOS provider adapter와 수집 service는 아직 없다.
- 실제 종목 Phase 2 점수, 최종 추천, 포트폴리오, 반도체 분석,
  백테스트 결과를 제공할 수 없다. Phase 2 계산 코드는 구현됐지만
  공식 입력이 없으면 점수를 생성하지 않는다.

## L-010 공식 DOCX 시각 렌더링 미수행

- KRX 공식 다운로드 명세 3건은 구조적으로 추출해 endpoint·요청·응답 필드를 확인했다.
- 로컬에 LibreOffice `soffice`가 없어 문서 페이지 렌더링은 실패했다.
- 계약 내용은 공식 기능 페이지와 DOCX 구조를 대조했지만 원본 DOCX의 시각적 레이아웃 검증은 남아 있다.

## L-011 Phase 0B 실행 검증 범위

- Python 3.12.13 가상환경, 프로젝트 의존성, migration, import와 pytest 16건은 검증했다.
- Streamlit은 AppTest로 초기화·메뉴·무키 연결상태 화면을 검증했다.
- 장시간 서버 프로세스 유지는 사용자 지시에 따라 완료 판정에서 제외했으며, 2026-07-29 최종 확인 시 포트 8502는 수신 중이 아니었다.

## L-012 PostgreSQL 실제 서버 미검증

- `DATABASE_URL`과 `psycopg`를 통한 PostgreSQL 연결 구성을 포함했다.
- 실제 PostgreSQL 인스턴스에 migration을 적용하지 않았으므로 DDL, timezone 저장, JSON과 NUMERIC 동작은 운영 서버에서 추가 검증해야 한다.

## L-013 외부 provider 상태는 구성 점검

- KRX, OpenDART, 한국투자증권, NAVER, ECOS 상태는 키 환경변수의 구성 여부만 판정한다.
- 키가 존재해도 실제 HTTP 호출 전에는 `연결 미검증`이며 `연결됨`으로 승격하지 않는다.
- KIND는 공개 API 계약과 자동수집 권한 확인 전 `지원 보류`다.

## L-014 DB datetime의 timezone 강제 범위

- Pydantic 메타데이터와 연결 상태 모델은 naive datetime을 거부하고 `Asia/Seoul`로 정규화한다.
- SQLAlchemy 컬럼은 `DateTime(timezone=True)`를 사용하지만 SQLite 엔진 자체는 timezone offset 보존·검증을 강제하지 않는다.
- 향후 repository 계층은 검증된 메타데이터만 저장해야 하며, SQLite 직접 SQL 쓰기는 이 보장을 우회할 수 있다.

## L-015 공식 원천과 자체 계산값의 구분 방식

- 현재 schema는 `source_provider`, `source_function`, 원자료/정규화 테이블 분리, `rule_version`, `input_data_hash`로 출처와 계산 재현성을 기록한다.
- 별도의 강제 열거형 `source_kind`는 아직 없어 provider 명명 규칙을 우회한 직접 DB 쓰기까지 차단하지는 않는다.
- 실제 수집·계산 repository 구현 시 공식 API, 공식 원문 파싱, 자체 계산을 명시적으로 구분하는 검증이 필요하다.

## L-016 정적 분석 범위

- 독립 검수에서 AST parse, compileall, 전체 module import, import cycle과 패턴
  검색을 수행했다.
- Ruff 기본 전체 규칙을 `app`, `scripts`, `migrations`, `tests`에 실행했으며
  모두 통과했다.
- bundled Node와 가상환경을 지정한 Pyright를 `app`, `scripts`, `migrations`,
  `tests` 전체에 실행했으며 0 errors, 0 warnings였다.
- Pydantic Settings의 런타임 전용 `_env_file`은 테스트 helper의 타입 경계를
  통해 전달하도록 정리해 검증을 억제하지 않고 이전 정적 분석 오탐을 제거했다.

## L-017 Streamlit 실행 검수 범위 갱신

- AppTest로 빈 DB·API 키 미설정 화면 초기화와 금지된 샘플 숫자 부재를 확인했다.
- 실제 Streamlit 프로세스가 8503 포트에서 시작되는 것을 확인하고 10초 제한으로 종료한 뒤 포트가 닫힌 것을 확인했다.
- 장시간 서버 안정성, 다중 사용자 세션, 외부 reverse proxy 배포는 Phase 0B 검수 범위가 아니다.

## L-018 Phase 1A 실제 API 연결 미검증

- `KRX_API_KEY`, `DART_API_KEY`가 설정되지 않아 Phase 1A provider의 실제 HTTP 성공, 응답 스키마, 원응답 해시, 데이터 기준일을 확인하지 못했다.
- 무키 CLI는 `NOT_CONFIGURED`와 종료코드 2를 반환했고 종목·분류·원응답 행을 생성하지 않았다.
- 현재 검색 UI는 빈 목록과 KRX 데이터 연결 필요 오류만 표시한다.

## L-019 거래정지·관리종목 공식 상태 없음

- 확정된 KRX 유가증권 종목기본정보 계약에는 거래정지·관리종목 상태 필드가 없다.
- 따라서 공식 주권·보통주 분류가 확인돼도 최종 유니버스 적격 상태는 `REVIEW_REQUIRED`다.
- KIND 화면 내부 경로나 종목명 규칙으로 상태를 보완하지 않는다.

## L-020 상장폐지 판정 보류

- 기준일 종목 마스터에 존재하는 레코드는 해당 기준일 상장 상태로 저장한다.
- 이전 DB 종목이 새 응답에서 누락돼도 API 부분응답·기준일 오류 가능성이 있어 즉시 상장폐지로 변경하지 않는다.
- 공식 상장폐지 상태 또는 별도 검증 계약이 필요하다.

## L-021 OpenDART 매핑 범위

- 공식 고유번호 파일의 6자리 `stock_code` 정확 일치만 사용한다.
- 주식코드가 비어 있거나 우선주 등 별도 증권코드가 직접 제공되지 않는 경우 임의 회사명 매핑을 하지 않고 미매핑 상태를 유지한다.
- 실제 파일을 수집하기 전에는 중복 종목코드·매핑 충돌 건수를 알 수 없다.

## L-022 KRX 분류값 실제 응답 검증 필요

- 분류기는 공식 필드 원문을 보존하고 ETF·ETN·ELW·스팩·리츠·신주인수권증권·증서 의미가 명시된 값만 정규화한다.
- 실제 KRX 응답에서 사용하는 전체 값 집합은 인증 호출 전이라 확인하지 못했다.
- 자동 규칙에 없는 값은 `OTHER_OFFICIAL` 또는 `UNKNOWN`과 `REVIEW_REQUIRED`로 보존한다.

## L-023 SQLite datetime 복원 전제

- SQLite는 `DateTime(timezone=True)`의 timezone offset을 그대로 복원하지 않으므로 repository 조회 시 저장된 KST wall-clock 값에 `Asia/Seoul`을 복원한다.
- 애플리케이션 repository를 통한 쓰기는 timezone-aware KST를 요구하지만 직접 SQL 쓰기는 이 전제를 우회할 수 있다.
- 실제 PostgreSQL의 `timestamptz` 동작은 별도 운영 인스턴스에서 검증해야 한다.

## L-024 원자료 파일과 DB transaction의 원자성

- 원자료 파일은 정규화 DB transaction과 별도 파일시스템에 먼저 기록될 수 있다.
- 파일 기록 후 DB commit이 실패하면 DB 메타데이터가 없는 고아 원자료 파일이 남을 수 있다.
- 운영 배치에서는 고아 파일 점검·정리 정책과 원자료 백업 정책이 추가로 필요하다.

## L-025 연결상태의 의미

- KRX와 OpenDART의 `연결됨` 또는 `연결 실패`는 저장된 가장 최근 실제 원응답을 기준으로 하며 화면을 열 때 외부 API를 다시 호출하는 live check가 아니다.
- 인증키가 없으면 과거 성공 원응답이 있어도 `키 미설정`을 우선 표시한다.
- 마지막 성공 이후 실제 네트워크·키 상태가 바뀌었을 수 있으므로 운영 freshness 기준은 후속 단계에서 추가해야 한다.

## L-026 Phase 1A 독립 검수 후 외부 검증 잔여

- 독립 검수에서 pytest 45건, Ruff, Pyright, import, migration, 빈 DB·무키 앱·CLI와 실제 Streamlit HTTP 시작을 검증했다.
- `KRX_API_KEY`, `DART_API_KEY`는 여전히 미설정이므로 실제 외부 HTTP 성공, 실제 값 집합, 응답 해시와 데이터 기준일은 없다.
- Phase 판정은 `조건부 진행 가능`이며 실제 데이터를 사용하는 후속 완료 판정 전에 최소 읽기 호출 검증이 필요하다.

## L-027 Phase 1B KRX 일별가격 실제 호출 미검증

- `KRX_API_KEY`가 설정되지 않아 `유가증권 일별매매정보`의 실제 HTTP 성공,
  공식 수치 단위, 실제 응답 크기와 종목 식별자 매핑 건수를 확인하지 못했다.
- provider, 스키마 검증, 원응답 보존, 증분 upsert, 검색 화면 표시는
  계약 기반 응답과 격리된 테스트 DB로 검증했다.

## L-028 수정주가와 기술지표 보류

- KRX 일별매매정보 계약에는 수정주가 여부가 없어 저장한 가격을 수정주가라고
  표시하지 않는다.
- KIS 기간별시세 또는 기업행사를 반영한 공식 수정주가를 실제 검증하기 전까지
  RSI, 이동평균, 기간수익률은 계산하거나 화면에 표시하지 않는다.

## L-029 가격 수집 단위

- 현재 CLI는 호출 제한과 기준일 진실성을 명확히 하기 위해 한 번에 한 기준일만
  수집한다.
- 거래일 달력과 과거 구간 백필 orchestration은 아직 구현하지 않았으며,
  휴장일의 빈 응답을 직전 거래일 가격으로 대체하지 않는다.

## L-030 Phase 1B 독립 검수 후 잔여 위험

- 공식 KRX 일별매매정보 계약에서 수치 단위를 확인하지 못했으므로 통화를
  `KRW`로 추정하지 않고 UI에 `단위 미검증`으로 표시한다.
- `f2a5b6c7d8e9` migration은 기존 KRX 일별가격 중 검증되지 않은 `KRW`
  가정을 NULL로 보정하지만 실제 PostgreSQL 서버에서는 실행하지 못했다.
- 계약형 synthetic fixture와 HTTP 오류 격리 테스트는 통과했으나 실제 KRX
  응답 snapshot, 실제 단위, 식별자 충돌·미매핑 비율은 확인하지 못했다.
- 원자료 파일과 DB transaction의 비원자성, SQLite의 timezone 복원 전제,
  공식 수정주가 부재는 계속 남아 있다.
- Phase 판정은 `조건부 진행 가능`이며 실제 시장 숫자를 사용하는 다음 단계
  완료 판정 전 최소 읽기 API 검증이 필요하다.

## L-031 Phase 1C 실제 OpenDART 연결 미검증

- `DART_API_KEY`가 설정되지 않아 공시검색, 단일회사 전체 재무제표,
  배당에 관한 사항, 감사의견 API의 실제 HTTP 호출을 수행하지 못했다.
- provider schema, CFS 우선·OFS fallback, 원응답 분리, repository와 계산은
  계약형 격리 테스트로만 검증했다.
- 실제 종목의 최근 재무제표, 최근 5년 DPS와 최신 감사의견 기준일은 없다.

## L-032 재무 기간·정정 연결·XBRL 확장계정

- OpenDART 전체 재무제표 응답에는 정확한 `period_start`, `period_end`가 없어
  XBRL context 원문을 추가하기 전 날짜를 추정하지 않는다.
- 공시검색 결과로 원·정정 접수번호와 제출일은 각각 보존하지만
  `original_receipt_no` 직접 연결 필드가 없어 자동 원본 연결을 하지 않는다.
- 표준 XBRL 계정 ID와 member context가 없는 행만 핵심 지표에 자동 매핑한다.
  기업 확장계정과 상세 member는 `UNMAPPED`로 남고 0으로 변환되지 않는다.
- TTM은 공식 당기누적·전기누적과 전기연간 값 및 통화가 모두 일치할 때만
  계산하며 입력이 하나라도 없으면 NULL이다.

## L-033 배당·감사 원문 해석 범위

- `배당에 관한 사항`은 라벨에 `(원)` 또는 `(백만원)`이 명시된 확인된
  현금배당 행만 정규화한다. 실제 응답에서 다른 라벨이 사용되면 원자료 fact로
  남고 DPS로 변환되지 않는다.
- 현금·현물배당결정은 공시 메타데이터와 원문 링크만 수집하며 원문 표의
  금액·지급일 파싱은 구조화 계약 확인 전 보류한다.
- OpenDART 감사의견 구조화 응답은 강조사항 텍스트를 제공하지만 계속기업
  위험 전용 boolean을 제공하지 않는다. 따라서 텍스트를 보존하고 상태를
  `NOT_VERIFIED`로 두며 키워드만으로 위험을 확정하지 않는다.

## L-034 Phase 1C 기술지표 운영 보류

- Wilder RSI, SMA 20·60·120·200, ATR 14와 52주 고점 대비 낙폭 계산은
  구현·테스트했다.
- 계산기는 모든 입력행이 `is_adjusted=True`이고
  `adjustment_status=VERIFIED`인 단일 가격 원천만 허용한다.
- 현재 KRX 일별가격은 수정가격 여부가 `NOT_VERIFIED`이므로 운영 화면에서
  기술지표 숫자를 표시하지 않고 구체적인 계산 보류 사유를 표시한다.
- 공식 수정가격 원천을 실제 연결하기 전에는 실제 종목 RSI 검증 완료를
  주장할 수 없다.

## L-035 Phase 1C 판정

- 독립 검수 결함 수정 후 전체 pytest 79건, migration, 빈 DB, 무키
  CLI·AppTest, 실제 Streamlit HTTP 시작, Ruff와 Pyright 검사는 통과했다.
- Alembic head는 `i5d8e9f0a1b2`이며 SQLite 기존 DB와 빈 DB 모두 적용했고
  schema drift가 없음을 확인했다.
- 실제 OpenDART와 공식 수정가격 연결 조건은 충족하지 못했다.
- Phase 판정은 `조건부 진행 가능`이며 실제 데이터 기반 다음 Phase 완료 판정
  전에 종목 한 개 이상의 공식 결과를 검증해야 한다.

## L-036 Phase 1C 독립 검수 후 잔여 위험

- `DART_API_KEY`, `KRX_API_KEY`와 그 밖의 외부 provider 인증정보가 없어
  실제 외부 HTTP 요청은 수행하지 못했다. 계약형 fixture 통과는 실제 응답
  값 집합과 운영 제한을 증명하지 않는다.
- 공식 수정가격 원천이 없어 실제 종목 RSI·SMA·ATR·52주 낙폭은 계속
  계산 보류 상태다.
- SQLite migration은 검증했지만 실제 PostgreSQL의 DDL, `timestamptz`,
  `NUMERIC` 동작은 검증하지 못했다.
- `stock_analysis_service.py`와 `financial_repository.py`는 각각 수집
  orchestration과 재무 영속화 책임이 커진 상태다. 현재 provider/service
  책임 혼합이나 순환 import는 확인되지 않았지만 다음 유지보수 변경 전
  역할별 분해를 검토할 필요가 있다.

## L-037 Phase 2 공식 필터 입력 부재

- 관리종목·거래정지·상장폐지 위험과 기업 이벤트를 정규화할 공식 writer가
  아직 없다. 내부 상태 코드의 읽기 계약만 마련했으며 값이 없으면 모든 항목을
  정상으로 가정하지 않고 강제필터 `MISSING`으로 차단한다.
- KRX `SECT_TP_NM`을 산업분류로 쓰지 않는다. 공식 산업분류가 수집되기 전에는
  금융·비금융 구분과 산업 PER/PBR을 실제 운영 데이터로 계산할 수 없다.
- 금융업 규제지표 별도 모형은 골격만 있으며 실제 입력이 없으면 일반
  이자보상비율을 대신 적용하지 않고 `MISSING`으로 처리한다.

## L-038 Phase 2 점수 범위

- 프로젝트 전체 기본 투자매력 100점 중 이번 Phase가 직접 계산하는 배당 25점,
  재무 25점, 산업·역사 밸류에이션 20점만 `PHASE2_CORE_ONLY`로 저장한다.
- 이 70점 내부 구성은 사용자 확인을 위해 100점 척도로 정규화하지만,
  시장충격 15점·공시/뉴스 10점·애널리스트/수급 5점이 포함된 전체
  기본 투자매력 점수로 표시하거나 사용하지 않는다.
- 개별 종목 RSI·추세 20점 부분만 별도 정규화한다. 시장국면·반도체·
  시장 폭·수급이 필요한 전체 진입준비 점수는 NULL로 유지한다.
- `recommendation_computable`은 Phase 2 입력 완전성 게이트이며 최종
  추천 생성 완료를 뜻하지 않는다. 추천 레코드는 생성하지 않는다.

## L-039 Phase 2 실제 데이터 검증 부재

- `KRX_API_KEY`, `DART_API_KEY`와 다른 provider 인증정보가 없고 기본 DB의
  활성 종목도 0건이므로 실제 종목의 강제필터·배당·재무·밸류에이션·
  RSI 결과를 계산하지 못했다.
- KRX 거래대금의 KRW 단위와 수정가격 여부가 확인되지 않아 기존
  KRX 가격만으로 유동성과 진입 구성요소를 통과시키지 않는다.
- 계약형 fixture와 격리 DB 테스트는 통과했지만 실제 API의 값 집합,
  최신성, 산업 표본 분포와 계산 성능을 증명하지 않는다.

## L-040 Phase 2 성능·시점 한계

- 산업 peer 현재 PER/PBR은 현재 구현에서 후보 종목별 재무·가격 조회를
  수행하므로 실제 KOSPI 전체 배치에서는 집계 쿼리와 인덱스 최적화가 필요하다.
- 기준일 이후 수집된 종목·시장상태·분류·역사 밸류에이션은 차단한다.
  다만 현재 종목 마스터가 최신 스냅샷 하나만 유지하므로 과거 유니버스를
  완전하게 재구성하는 백테스트용 point-in-time 저장소는 아니다.
- SQLite migration과 KST wall-clock 복원은 검증했지만 실제 PostgreSQL의
  DDL·timezone·NUMERIC 동작은 검증하지 못했다.
- Phase 2 최초 구현 후 전체 pytest 97건이 통과했고, 독립 검수 보완 후에는
  전체 pytest 110건, Ruff, Pyright, compileall, migration, CLI 누락 처리,
  빈 DB·무키 UI와 실제 Streamlit HTTP 시작이 통과했다.
- 실제 외부 데이터 조건이 충족되지 않아 Phase 판정은 `조건부 진행 가능`이다.

## L-041 Phase 2 독립 검수 후 잔여 위험

- `phase2-rule-v2`는 단일 TTM 이자보상비율 1배 미만을 즉시 배제하지 않고
  `REVIEW_REQUIRED`로 차단한다. 연속 기간의 이자보상비율을 구조화해
  “지속”을 확정하는 입력은 아직 없으므로 이 사유만으로 자동 `FAIL`을
  만들 수 없다.
- 금융업 별도 모형은 실제 규제지표와 통과 결과가 없어 골격 상태다.
  모형 존재 여부만으로 통과시키지 않으며 실제 결과가 없으면 `MISSING`이다.
- 기준시각 이후 수집된 가격과 비정상 상태 재무·배당·감사 자료는
  Phase 2 입력에서 제외하지만, 최신 종목 마스터 하나만 유지하는 구조라
  과거 유니버스 전체를 재현하는 point-in-time 백테스트 저장소는 아니다.
- `stock_analysis_service.py`, `financial_repository.py`, `stock_search.py`는
  각각 757행, 614행, 568행으로 책임이 커져 있다. 현재 순환 import나
  provider/service 책임 혼합은 확인되지 않았지만 후속 유지보수 시
  역할별 분해가 필요하다.
- 실제 KRX·OpenDART·KIS 인증 호출, 실제 종목 결과, PostgreSQL migration은
  여전히 검증하지 못했다.

## L-042 Phase 3 실제 시장 데이터 미검증

- `KRX_API_KEY`가 없어 KRX `KOSPI 시리즈 일별시세정보`를 실제 호출하지
  못했고 실제 `IDX_NM` 값 집합, 지수 수치 단위, 원응답 해시와 기준일이 없다.
- 무키 지수 CLI는 `NOT_CONFIGURED`, 종료코드 2, 저장 지수 0건을 반환했다.
- 기본·검증용 DB에는 실제 종목·가격·지수 데이터가 없으므로 실제 시장충격
  분류와 시장국면 숫자를 확인하지 못했다.

## L-043 Phase 3 반도체·수정가격 입력

- 공개 계약에서 공식 KRX 산업분류와 프로젝트에 맞는 공식 반도체 지수
  구성종목을 확인하지 못해 산업분류 writer가 없다.
- Phase 3 계산기는 config에 지정된 공식 분류 체계·정확 코드만 사용하며,
  값이 없으면 종목명이나 `SECT_TP_NM`으로 대체하지 않고 `UNCERTAIN`이다.
- KIS 기간별시세 provider가 아직 없어 실제 검증된 수정가격 시계열이 없다.
  기존 KRX 가격은 `NOT_VERIFIED`이므로 시장 폭과 바스켓 입력에서 제외한다.

## L-044 Phase 3 기여도와 배당주 표본 범위

- 종목별 기여도는 공식 지수 제공 기여도가 아니라 비교 가능한 KOSPI
  구성종목의 전일 전체 시가총액 비중×당일 수정가격 수익률이다.
  화면과 저장값에 `EXPLANATORY_ESTIMATE`로 표시하며 인과관계가 아니다.
- 배당주 바스켓은 기준일 이전 확정 DPS가 저장된 종목만 포함한다. 배당이
  없다는 공식 음의 관측을 전 종목에 저장하는 구조가 없어 미수집 종목과
  무배당 종목을 완전히 구분한 전체 시장 배당주 모집단은 아니다.
- 산업조정 초과수익률과 과거 베타 회귀는 입력 계약·시점 데이터가 부족해
  이번 Phase에서 숫자를 만들지 않았다.

## L-045 Phase 3 실행·성능 범위

- SQLite 기존 DB와 빈 DB migration, 131개 pytest, Ruff, Pyright,
  전체 import, 무키 CLI, 저장된 누락 스냅샷 UI와 Streamlit HTTP 200을
  검증했다.
- 실제 KOSPI 전체의 60일 이상 수정가격을 한 번에 읽는 쿼리는 실제 대규모
  DB에서 성능을 검증하지 못했다. 운영 전 날짜·provider 복합 인덱스와
  배치 집계를 점검해야 한다.
- 실제 PostgreSQL migration·timezone·NUMERIC·JSON 동작은 미검증이다.

## L-046 Phase 3 독립 검수 후 잔여 위험

- `phase3-rule-v2`와 migration `l8a1b2c3d4e5`, `m9b2c3d4e5f6`에서
  공식 반도체 지수의
  시작·종료일 정렬, KRX 확정 종가 시가총액, 최신 정정 배당, 전체
  유니버스 기여도 분모, 시세구분과 종목별 provenance를 보강했다.
- migration 이전에 저장된 기여도는 당시 원천을 사후 추정하지 않아
  `market_cap_source_provider=UNKNOWN`, `collected_at=NULL`일 수 있다.
  운영 표시 전에 같은 기준일을 `phase3-rule-v2`로 재계산해야 한다.
- 실제 KRX 지수·공식 산업분류·KIS 수정가격·OpenDART 배당 입력이 없어
  실제 시장 숫자와 국면은 여전히 검증하지 못했다.
- 산업조정 배당주 초과수익률과 과거 베타 회귀는 검증된 시점 입력 계약이
  없어 숫자를 만들지 않는다. 구현된 설명 기여도 역시 인과관계가 아니다.
- 최신 종목 마스터 한 행과 provider별 일별가격 upsert 구조는 완전한
  과거 유니버스·수정 이력을 보존하는 point-in-time 백테스트 저장소가
  아니다.
- `market_metric_builder.py`는 provenance 조립 책임만 가지지만 588행으로
  커져 있어 후속 유지보수 시 지표군별 분리를 검토할 필요가 있다.
- 실제 PostgreSQL migration과 KOSPI 전체 배치 성능은 여전히 미검증이다.
- Phase 판정은 `조건부 진행 가능`이며 실제 데이터 완료 판정 전 최소 한
  기준일의 공식 입력·원응답·출처·수집시각·계산 결과를 검증해야 한다.

## L-047 Phase 4 실제 추천 미검증

- 운영 DB의 활성 KOSPI 종목은 0건이며 KRX·OpenDART·KIS 인증정보도
  설정되지 않았다.
- 빈 DB Phase 4 CLI는 `MISSING`, 종료코드 2, 추천 0건으로 끝났고
  가짜 종목·점수·가격·목표비중을 만들지 않았다.
- 실제 KOSPI 전체의 추천 그룹, 제외 사유 분포, 목표비중과 처리시간은
  검증하지 못했다.

## L-048 Phase 4 점수 범위와 과도할인 해석

- 투자매력은 Phase 5 촉매·애널리스트/수급이 없는
  `PHASE2_CORE_ONLY` 범위다.
- 진입준비는 개별 종목 입력 80%와 이미 반도체·시장 폭 신호를 포함한
  Phase 3 시장국면 20%를 결합한
  `PHASE4_INDIVIDUAL80_MARKET20` 범위다.
- 과도할인 점수는 같은 Phase 3 기간의 비반도체 동일가중 수익률 대비
  종목 상대수익률 차이다. 시장이 하락 원인이라는 인과 증거가 아니며
  산업조정·과거 베타·기업 고유 악재 원문 검토를 대체하지 않는다.
- 과도할인 후보에는 목표비중을 주지 않고 숨은 악재 추가검토 상태로 둔다.

## L-049 Phase 4 포트폴리오·보유 판단 한계

- 공식 기업집단 writer가 없어 기업집단 최대비중은 설정·스키마·엔진
  골격만 존재한다. 코드가 없으면 `NOT_AVAILABLE`이며 한도 검증 성공으로
  표시하지 않는다.
- 보유비중은 사용자가 입력한 수량, 총 투자 가능자금과 동일 기준일의
  검증된 수정종가가 모두 있을 때만 계산한다. 하나라도 없으면
  `NOT_COMPUTABLE`이다.
- 종목·산업 한도와 시장국면 목표는 적용하지만 상관관계·변동성 최적화는
  공식 point-in-time 입력이 없어 구현하지 않았다.
- 최신 종목 마스터 한 행 구조는 완전한 과거 유니버스가 아니며 Phase 4
  재현성은 저장된 현재 분석 snapshot 범위에 한정된다.

## L-050 Phase 4 실행 검증 범위

- SQLite 기본 DB와 빈 DB migration head `n0c3d4e5f6a7`, schema drift,
  전체 pytest 139건, Ruff, Pyright, compileall, 전체 module import,
  무키 CLI, 빈 DB 추천 버튼과 실제 Streamlit HTTP 200을 검증했다.
- 실제 PostgreSQL migration·JSON·NUMERIC·timezone, KOSPI 전체 배치
  성능과 동시 실행 unique 충돌 처리는 검증하지 못했다.
- 실제 공식 입력 조건이 충족되지 않아 Phase 판정은 `조건부 진행 가능`이다.

## L-051 Phase 4 독립 검수 후 잔여 위험

- `phase4-rule-v2`와 migration `o1d4e5f6a7b8`에서 config별 추천 저장,
  보수적 비중 내림, 전략군 최소 배분, 보유·가격 통화 일치, 비반도체
  비교 기준, 전 종목 데이터 부족 실행 상태, 기준가격 provenance,
  canonical profile hash와 설정 재선택을 보정했다.
- 기본 DB와 검증용 빈 DB는 `o1d4e5f6a7b8 (head)`이고 전체 pytest
  148건, Ruff, Pyright, compileall, 91개 module import, 빈 DB·무키 UI,
  Phase 4 CLI와 실제 Streamlit 서버 시작이 통과했다.
- 실제 KRX·OpenDART·KIS 인증정보와 활성 KOSPI·검증 수정가격·원응답은
  0건이어서 실제 추천·가격·점수·시장국면·목표비중을 검증하지 못했다.
- 공식 산업분류·기업집단 writer와 KIS 수정가격 provider가 없으며,
  PostgreSQL migration과 실제 KOSPI 전체 배치·동시 실행 성능도
  검증하지 못했다.
- `risk_profile`, 목표 배당수익률, 현재 현금, 우선주·리츠 설정은
  재현성 config에 보존되지만 현재 추천 규칙을 별도로 변화시키지 않는다.
  공식 별도 모형이 없는 우선주·리츠는 설정만으로 자동 추천하지 않는다.
- Phase 4 service와 repository는 책임 경계는 유지하지만 파일 크기가 커
  후속 유지보수 시 입력조립·실행·조회와 저장·복원 기능의 분리를
  검토할 필요가 있다.
- Phase 판정은 `조건부 진행 가능`이다. 실제 완료 판정 전 최소 한
  기준일의 공식 입력·원응답·추천 근거·수정가격 provenance·한도 적용을
  검증해야 한다.

## L-052 Phase 5 실제 외부 데이터 미검증

- OpenDART, NAVER API HUB, 한국투자증권 인증정보가 설정되지 않아
  Phase 5 실제 HTTP 호출을 수행하지 못했다.
- 기본 DB의 Phase 5 원응답·중요공시·뉴스·이벤트·애널리스트 의견·
  투자자 수급·프로그램매매·공매도는 모두 0건이다.
- mock 계약 테스트는 endpoint·요청·응답 검증을 보장하지만 운영 키,
  실제 호출 제한, 실제 응답 변형과 값 단위를 대체하지 않는다.

## L-053 정정공시와 뉴스 해석 한계

- OpenDART 공시검색 응답에는 정정공시의 원본 접수번호가 없어 정규화한
  제목과 접수일 선후관계로 원본 후보를 찾는다.
- 후보가 정확히 하나일 때만 연결하고, 여러 개면 `AMBIGUOUS`, 없으면
  `ORIGINAL_NOT_FOUND`다. 모호한 정정공시는 자동 연결하지 않는다.
- NAVER API HUB 응답은 제목과 제공 요약만 포함한다. 앱은 기사 본문,
  유료 원문, 표·이미지 또는 기사 내 추가 문맥을 읽은 것으로 표현할 수
  없다.
- URL·내용·유사제목 중복제거는 결정적 규칙이지만 서로 다른 후속기사를
  하나로 합치거나 같은 사건의 모든 표현을 찾는 완전한 의미 중복제거는
  아니다.

## L-054 KIS 참고 데이터 단위와 미구현 기능

- 목표주가, 투자자 순매수 수량, 프로그램매매 수량, 공매도 값의 공식
  필드 의미는 검증했으나 응답에 통화·수량 단위 전역 메타가 없다.
  앱은 통화·단위를 추정하지 않고 `NULL` 또는 `공식 응답 단위 미표기`로
  표시한다.
- 프로그램매매는 KOSPI 전체 위탁 순매수 수량
  `whol_entm_ntby_qty`만 저장한다. 차익·비차익의 다른 필드를 임의로
  합산하지 않는다.
- EPS 추정실적, 대차거래와 신용잔고는 안전한 정규화 필드 계약이
  확정되지 않아 제공 상태만 표시하고 숫자를 만들지 않는다.
- 증권사 투자의견·목표주가는 추정 참고 데이터이고 실제 기관 매매와
  별도다. 서로 일치한다고 가정하거나 동일 점수로 합치지 않는다.

## L-055 Phase 5 규칙·실행 범위

- 이벤트 긍정·중립·부정은 `phase5-event-rule-v1` 키워드 규칙의
  설명 가능한 분류다. 사실 검증, 인과관계, 주가 선반영 여부, 투자추천
  또는 점수가 아니다.
- Phase 5 데이터를 기존 Phase 4 점수에 소급 결합하지 않았다. 수급
  15점을 포함한 전체 진입준비 점수는 여전히 미구현이다.
- SQLite 기본 DB와 빈 DB migration head `q3f6a7b8c9d0`, 175개 pytest,
  Ruff, Pyright, 102개 module import, 무키 CLI와 Streamlit HTTP 200은
  검증했다.
- 실제 PostgreSQL migration, 실제 API의 증분 페이지 처리, 대량 종목
  반복수집·동시 실행 성능은 미검증이다.
- Phase 판정은 `조건부 진행 가능`이며 실제 완료 판정 전 최소 한 종목의
  공식 원응답과 정규화 결과를 대조해야 한다.

## L-058 Phase 6 실제 point-in-time 데이터 미검증

- 기본 DB는 활성 종목 0건, 백테스트 실행 0건이며 KRX·OpenDART·KIS
  인증정보도 설정되지 않았다.
- 현재 종목 마스터는 최신 행 중심 구조여서 과거 전체 유니버스나 상장폐지
  이력을 복원할 수 없다. Phase 6는 이를 과거 유니버스로 사용하지 않고,
  검증된 외부 `BacktestDataset` 입력이 없으면 `MISSING`만 저장한다.
- 공식 과거 유니버스, 상장폐지 정산값, 제출일별 원·정정 재무 이력,
  실제 검증 수정가격과 과거 추천 snapshot을 한 기간에서 대조하지 못했다.
  따라서 생존편향 제거 완료나 실제 투자성과를 주장하지 않는다.
- 기본 수정가격 원천 이름은 config의 `KIS`지만, KIS 일별 수정가격을
  수집·검증해 쓰는 writer는 아직 없다. 입력행마다 동일 provider,
  `is_adjusted=true`, `adjustment_status=VERIFIED`를 증명해야 계산된다.

## L-059 Phase 6 계산·운영 범위

- 재무·정정·배당 이력의 완전성은 입력 계약의 명시적 완전성 플래그와
  원문 날짜를 검증하지만, 별도 공식 과거 corpus와 독립 교차검증하지 못한다.
- 거래비용은 config의 매수·매도 동일 basis-point 가정이다. 실제 증권사별
  수수료, 세제 변경, 호가 스프레드, 시장충격과 체결 미끄러짐은 포함하지 않는다.
- 배당은 보유기간 중 지급된 확정 현금 DPS만 포함한다. 주식배당·권리처리와
  세후 개인별 현금흐름은 포함하지 않는다.
- 정정 배당은 입력의 원접수번호 연결과 지급 사업연도를 사용한다. 실제
  OpenDART 과거 corpus로 연결 완전성을 독립 교차검증하지 못했으므로 잘못된
  원접수번호나 사업연도는 입력 생성 단계에서 차단해야 한다.
- 상장폐지 종목은 공식 정산값과 통화·원천이 없으면 해당 실행 전체를
  `MISSING`으로 막는다. 임의 0원 또는 마지막 종가로 대체하지 않는다.
- 최대낙폭은 일별 포트폴리오 평가곡선이 아니라 비중첩 primary-horizon
  fold 종료 수익률로 계산한다. UI와 결과에 이 방법을 명시하며 일별 MDD로
  해석해서는 안 된다.
- 고배당 벤치마크는 config에 공식 지수 이름과 시계열을 제공한 경우에만
  계산한다. 기본값은 미설정이며 실제 공식 고배당 지수 장기 입력은 검증하지
  못했다.
- SQLite migration·전체 192개 테스트·Ruff·Pyright·109개 module import·
  무데이터 CLI·Streamlit HTTP 200을 검증했다. 실제 PostgreSQL과 대규모
  KOSPI 장기 입력의 메모리·처리시간·동시 실행 unique 충돌은 미검증이다.
- 현재 계산 계약은 `phase6-backtest-v2`, `phase6-rule-v2`다.
- Phase 판정은 `조건부 진행 가능`이다. 실제 완료 판정 전 고정된 과거
  기간의 공식 입력과 저장 결과를 독립 재실행해 hash·성과가 같은지
  대조해야 한다.
