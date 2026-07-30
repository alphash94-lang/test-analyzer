# 구현 상태

## Phase 7 독립 검수 및 수정 결과 (2026-07-30)

이 절이 현재 프로젝트 상태의 기준이다. 새 기능은 추가하지 않고 Phase 7
통합·보안·실행 범위만 독립 검수했다.

- Phase 판정: **조건부 진행 가능**
- 검수 완료시각: `2026-07-30 03:01:05 +09:00`
- 최신 migration: `r4g7h8i9j0k1 (head)`
- 전체 pytest: **213 passed, 0 failed**
- Phase 7 대상 테스트: **20 passed**
- 데이터 진실성 표적 회귀: **24 passed**
- 실제 외부 API 성공 호출: **0건** — 모든 외부 provider 인증정보 미설정

### 발견한 문제

#### Critical

- 없음.

#### High

- `update_stock_analysis.py`와 `update_phase5_events.py`가 최상위 예외를
  출력할 때 설정값을 `safe_exception_message`에 전달하지 않았다.
  provider가 설정된 credential을 일반 예외 문자열로 되돌려 주면
  필드명 없는 secret이 평문으로 출력될 수 있었다.

#### Medium

- 한국투자증권 provider가 실제로 사용하는 OAuth token endpoint와
  `access_token` 응답 필드가 `docs/api_contract.md`에 빠져 있어
  실행 코드의 endpoint·응답 필드 근거를 계약 문서만으로 추적할 수
  없었다.

#### Low

- 없음.

### 수정한 내용

- `scripts/update_stock_analysis.py`
  - 설정 로드 전 실패도 처리할 수 있도록 `settings`를 먼저 초기화하고,
    최상위 예외 출력에 실제 설정을 전달해 설정된 secret을 마스킹했다.
- `scripts/update_phase5_events.py`
  - 같은 CLI 예외 출력 경계를 적용했다.
- `tests/test_phase_7_release_readiness.py`
  - 두 CLI의 provider-echoed credential 회귀 테스트와 실행 중인
    provider endpoint·응답 필드의 API 계약 수록 테스트를 먼저 추가했다.
- `docs/api_contract.md`
  - KIS OAuth `/oauth2/tokenP`, 요청 필드, `access_token`, 공식 근거와
    token 원응답 비저장 원칙을 기록했다.

### 실행 검수 결과

- Python 3.12.13에서 `pip check`는 broken requirement 0개였고
  `pyproject.toml`의 모든 runtime·development dependency import가
  성공했다.
- 선언되지 않았고 source에서도 사용하지 않는 `plotly`까지 포함한 첫
  탐색성 import 명령은 `ModuleNotFoundError`로 실패했다. 선언 dependency
  기준 재검사는 통과했으며 Plotly 준비 완료를 주장하지 않는다.
- `compileall`, Ruff, Pyright(`0 errors, 0 warnings`), `app`·`scripts`
  109개 module import가 통과했다.
- package `__init__.py` 집계 import를 제외한 92개 실제 module의 AST
  import graph에서 순환 import는 0개였다.
- 기존 SQLite DB와 새 빈 DB에서 `alembic upgrade head`, `current`,
  `check`를 통과했다. 새 DB는 37개 table, domain row 0개,
  `PRAGMA integrity_check=ok`, foreign-key violation 0개였다.
- 외부 키 없는 새 DB에서 Streamlit 8개 메뉴 AppTest는 exception 0개였고
  예시 종목·가짜 주가·배당수익률·RSI·점수·추천·시장국면·백테스트
  결과가 나타나지 않았다.
- Phase 1B~6의 9개 CLI를 무키·무데이터 DB에서 직접 실행했다. 모두
  `NOT_CONFIGURED` 또는 `MISSING`과 구체적 사유를 반환했고 정상
  데이터 행을 만들지 않았다.
- 실제 Streamlit server를 hidden subprocess로 실행해 HTTP 200과 종료
  후 listener 0개를 확인했다. PowerShell `Start-Process` 시도는 검수
  환경의 `Path`/`PATH` 중복 environment-key 오류로 launch 전에
  실패했고, Python subprocess 검증은 성공했다.
- 데이터 진실성 표적 테스트 24개는 HTTP 오류 비저장, 0과 누락 구분,
  계정 매핑 실패, 연결 우선, 누적 분기 변환, 정정공시, 수정가격,
  미래정보 차단, 재현성을 포함해 모두 통과했다.

### 실제 API 상태

- KRX: `NOT_CONFIGURED`
- OpenDART: `NOT_CONFIGURED`
- 한국투자증권(KIS): `NOT_CONFIGURED`
- NAVER API HUB 뉴스: `NOT_CONFIGURED`
- ECOS: `NOT_CONFIGURED`
- KIND: `DEFERRED`
- SQLite DB: `CONNECTED`
- 실제 외부 HTTP 호출·실제 기준일·실제 응답 fixture: 없음

### 남아 있는 위험

- 실제 API 키와 원응답이 없어 provider별 인증 성공, 실제 필드·단위,
  pagination, 호출 제한과 timeout을 운영 응답으로 확인하지 못했다.
- 공식 수정가격·산업분류·반도체 구성 및 완전한 과거 point-in-time
  corpus가 없어 실제 기술지표, 시장분석과 생존편향 제거 백테스트의
  데이터 완료를 주장할 수 없다.
- PostgreSQL migration·backup/restore, 다중 process 동시 upsert와
  장기 운영은 검증하지 못했다.
- `.git` 메타데이터가 없어 tracked secret 이력과 기준 revision diff를
  확인할 수 없다.
- 500행 이상 service·repository 파일이 남아 있지만 이번 검수에서
  책임 혼합, 순환 import 또는 실행 결함은 발견되지 않았다.

### 판정 근거

코드·migration·무키 실행·UI·전체 테스트는 통과했고 발견된 보안 및
계약 문서 결함은 수정됐다. 다만 실제 외부 API와 운영 데이터 검증이
완료되지 않았으므로 전체 완료나 무조건 배포 가능으로 판정하지 않는다.

---

## Phase 7 최종 통합·배포 준비 결과 (2026-07-30)

이 절은 최초 Phase 7 통합 결과이며 위 독립 검수 절이 현재 기준이다.
Phase 7에서는 새 투자 기능을
추가하지 않고 통합 오류, 보안, 최신성, 운영 문서와 최종 판정을 보완했다.

- 판정: **조건부 배포 준비 — 실제 데이터 운영 완료 아님**
- 최신 migration: `r4g7h8i9j0k1 (head)`
- 전체 pytest: **213 passed, 0 failed**
- Phase 7 대상 테스트: 전체 회귀에 포함된 **20 passed**
- 정적·구조 검증:
  - `compileall` 통과
  - Ruff 전체 통과
  - Pyright `0 errors, 0 warnings`
  - `app`·`scripts` 109개 module import 성공
  - AST 기준 `app` 101개 module, 순환 import 0개
  - Python 3.12.13, `pip check` broken requirement 0개

### 시작 상태와 기존 구현 확인

- 작업 전 `PROJECT_SPEC.md`, `IMPLEMENTATION_STATUS.md`, `DECISIONS.md`,
  `KNOWN_LIMITATIONS.md`를 전체 확인했다.
- 현재 작업 폴더에는 프로젝트가 없었고, 이전 실제 프로젝트
  `2026-07-28/kospi-analyzer-streamlit-project-spec-1-2`를 먼저 읽기
  검수했다. `.venv`, pytest cache와 원자료 cache를 제외한 기존 구현을
  현재 쓰기 가능한 작업 폴더로 그대로 복제한 뒤 미완성 Phase 7만
  보완했다.
- 이전 프로젝트와 현재 작업 폴더 모두 `.git` 메타데이터가 없어
  `git status --short`와 `git rev-parse --show-toplevel`은 저장소 상태를
  반환하지 못했다. 기존 기능 여부는 문서, source, migration, 테스트와
  실제 실행으로 확인했다.
- 시작 기준은 Phase 6 독립 검수의 192 passed,
  migration `r4g7h8i9j0k1`, 외부 API 키와 실제 데이터 없음 상태였다.

### 발견·수정한 통합 결함

#### High

- 비밀정보 logging filter가 실제 요청에서 쓰는 `crtfc_key`, `appkey`,
  `Authorization: Bearer`, NCP header와 DB URL 사용자정보의 비밀번호를
  모두 가리지 못했다.
  - 실사용 credential 형태와 설정된 secret 값을 공통
    `redact_sensitive_text`로 마스킹하고 CLI 예외 메시지도 같은 보호
    경계를 사용하도록 수정했다.
- 같은 DB transaction 안에서 동일 요청·동일 응답을 두 번 저장하면
  `autoflush=False` 때문에 첫 pending 행을 찾지 못해 두 행을 만들고
  commit 시 unique 충돌로 수집 전체가 실패할 수 있었다.
  - 원응답 행을 추가한 직후 flush하여 두 번째 저장이 기존 identity를
    재사용하도록 수정했다. DB unique 제약도 그대로 유지했다.

#### Medium

- 저장된 성공 원응답이 오래돼도 provider를 계속 `연결됨`으로 표시해
  데이터 최신성 경고가 없었다.
  - config 기반 `DATA_FRESHNESS_WARNING_HOURS` 기본 48시간과
    `데이터 지연` 상태·UI 경고를 추가했다.
- 필수 산출물인 `docs/data_dictionary.md`,
  `docs/investment_logic.md`, 최종 20개 기준 점검표가 없었다.
  - 현재 36개 domain table과 Alembic 관리 table의 데이터 사전,
    강제필터부터 백테스트까지의 투자 논리,
    `FINAL_COMPLETION_CHECKLIST.md`를 추가했다.
- README에 초기수집 전체 순서, 증분갱신, 백업·복구, 문제 해결과
  배포 전 검증 절차가 없었다.
  - 초보자 빠른 시작과 실제 CLI 순서, SQLite·PostgreSQL 운영 절차,
    정확한 무키·지연·migration 오류 대응을 추가했다.
- README가 Ruff·Pyright 실행을 안내하지만 `pyproject.toml`의 dev
  dependency에는 두 도구가 없었다.
  - `ruff`, `pyright`를 dev extra에 추가했다.

#### Low

- 실제 응답 기반 fixture가 없었지만 필수 산출물 관점에서 확보 상태와
  안전한 후속 절차를 한 곳에서 확인할 수 없었다.
  - 가짜 fixture를 만들지 않고
    `tests/fixtures/REAL_RESPONSE_STATUS.md`에 provider별 `미확보` 사유와
    비밀정보 제거·라이선스 확인 절차를 기록했다.

### 테스트 우선 보완 기록

- 최초 Phase 7 회귀는 **9 failed, 5 passed**였다.
  - 실제 credential 문자열 4형태 노출
  - 최신성 경고 부재
  - 데이터 사전·투자 논리·최종 점검표·fixture 상태 문서 부재를 재현했다.
- 배포 검증 도구 dependency 테스트는 추가 전 `ruff` 누락으로 1건
  실패했다.
- 원응답 중복수집 테스트는 수정 전 **1 failed, 15 passed**였고,
  같은 transaction의 두 pending 행이 서로 다른 객체로 생성되는 것을
  확인했다.
- 수정 후 Phase 7 17개 테스트는 전체 회귀에 포함되어 통과했다.
- API 오류·timeout·DART 요청 문맥 불일치·최신성·중복수집과
  Phase 2~6 재현성을 묶은 10개 핵심 시나리오도 모두 통과했다.
- 전체 기준선 첫 시도는 120초 실행 제한으로 37% 이후 종료됐으며
  테스트 실패는 출력되지 않았다. 600초 제한 재실행은 209 passed,
  최종 최신성 UI 테스트 추가 뒤 최종 실행은 **210 passed**였다.

### 실행·배포 검증 결과

- 기존 SQLite DB:
  - migration head `r4g7h8i9j0k1`
  - `alembic upgrade head`, `current`, `check` 성공
  - schema drift 없음
- 새 빈 SQLite DB:
  - 전체 migration 성공, table 37개
  - domain row 0, `integrity_check=ok`, foreign-key 위반 0
  - `alembic current/check` 성공
- 빈 DB·무키 Streamlit AppTest:
  - 최초 화면과 개별 종목, 시장국면, 추천, 포트폴리오, 공시·뉴스,
    백테스트, 설정 메뉴 모두 exception 0
  - 기존 UI 회귀를 포함해 예시 종목·가짜 가격·배당수익률·RSI·점수·
    추천·시장국면·백테스트 숫자 미표시 확인
- 실제 Streamlit 진입점:
  - headless port 8817에서 HTTP 200
  - 검증 프로세스 종료와 listener 0 확인
- 초기·증분 CLI 무키 실행:
  - 종목 마스터·일별가격·KOSPI 지수: `NOT_CONFIGURED`, 종료코드 2
  - 개별 종목 재무·배당·감사와 Phase 5: 종목 없음 `MISSING`,
    종료코드 3
  - Phase 2·3·4·6: `MISSING`, 종료코드 2
  - 정상 종목·가격·지수·재무·배당·감사·공시·뉴스·수급·추천 행 0
  - Phase 3·4·6은 숫자 없이 `MISSING` 실행 메타데이터만 저장
- SQLite 백업·복구 문서 절차:
  - 복사본과 복구본 SHA-256 일치
  - 복구본 migration head `r4g7h8i9j0k1`
- 보안:
  - `.env` 파일 없음
  - `.gitignore`의 `.env`, `.env.*`, `!.env.example` 규칙 확인
  - `.env.example`의 11개 인증정보 값 모두 빈 값
  - 광범위한 `except Exception`, 운영 코드 동적 SQL 문자열,
    secret 직접 print/log 패턴 0건
  - stock 검색 SQL injection·wildcard 입력 격리 테스트 통과
- 일부 provider 구성 격리 시나리오:
  - KRX만 구성하고 과거 성공 원응답을 둔 경우 `데이터 지연`
  - OpenDART는 `키 미설정`
  - 실제 외부 HTTP 연결 성공을 의미하지 않음

### 실제 API 및 fixture 상태

| provider·기능 | 실제 결과 |
|---|---|
| KRX 종목·가격·KOSPI 지수 | `KRX_API_KEY` 미설정, `키 미설정`, 실제 HTTP 미호출 |
| OpenDART 고유번호·공시·재무·배당·감사 | `DART_API_KEY` 미설정, `키 미설정`, 실제 HTTP 미호출 |
| 한국투자증권 참고·수정가격 | 앱키·시크릿 미설정, `키 미설정`, 실제 HTTP 미호출 |
| NAVER API HUB 뉴스 | 키 2종 미설정, `키 미설정`, 실제 HTTP 미호출 |
| ECOS | 키 미설정, adapter 미구현, 실제 HTTP 미호출 |
| KIND | 공식 공개 API 계약·자동수집 권한 미확인, `지원 보류` |
| SQLite | 기존 DB·빈 DB·복구본 migration과 연결 성공 |
| PostgreSQL | 서버 미제공, migration·backup/restore 미수행 |
| 실제 응답 fixture | 인증정보·실제 원응답 0건으로 미확보, 가짜 fixture 미생성 |

### 완료 기준 20개 판정 요약

- 충족: 5개
- 부분 충족: 3개
- 미충족: 0개
- API 키 또는 외부 데이터 필요: 9개
- 현재 API 제공 범위에서 구현 곤란: 3개

세부 항목과 근거는 `docs/FINAL_COMPLETION_CHECKLIST.md`를 따른다.
`미충족`이 0개라는 사실은 외부 데이터 조건이 충족됐다는 뜻이 아니며,
9개 외부 데이터 필요와 3개 현재 API 제공 범위 곤란 항목 때문에 전체
완료를 주장하지 않는다.

### 필수 산출물 상태

- source, `pyproject.toml`, `.env.example`, README, API 계약, 데이터 사전,
  점수 규칙, 투자 논리, migration, pytest, 초기·증분 명령,
  백업·복구·문제 해결 문서: 준비됨
- 실제 응답 기반 fixture: 미확보
- 실제 API 성공 로그·응답 hash·실제 데이터 기준일: 없음

### 남아 있는 위험

- 실제 KRX·OpenDART·KIS·NAVER 인증 호출이 없어 성공 HTTP, 실제 schema,
  값 집합, 수치 단위, 호출 제한과 실제 데이터 최신성을 검증하지 못했다.
- 공식 수정가격 writer, 공식 산업분류 writer, 공식 반도체 구성과 완전한
  과거 point-in-time corpus가 없다.
- provider 최신성 경고는 마지막 성공 원응답의 수집시각과 공통 config
  임계값을 비교한다. provider별 공식 갱신주기와 데이터 기준일 지연을
  완전히 판정하는 기능은 아니다.
- 같은 process·transaction 중복은 회귀 테스트로 막았고 DB unique 제약이
  최종 중복을 막지만, 다중 process 동시 수집의 unique 충돌 재시도와
  대량 배치 성능은 실제 운영 DB에서 검증하지 못했다.
- 실제 PostgreSQL migration·backup/restore·timezone·NUMERIC·동시성,
  reverse proxy와 장시간 다중 사용자 운영은 미검증이다.
- 500행 이상 service/repository/UI 파일의 유지보수 위험은 남아 있으나
  이번 Phase에서 대규모 리팩터링하지 않았다.
- `.git` 메타데이터가 없어 실제 Git tracked 상태와 `git check-ignore`
  결과를 검증할 수 없었다. ignore 파일 내용과 secret 부재만 확인했다.

### 마지막 갱신시각

- 2026-07-30 02:30 KST (Asia/Seoul)

---

## Phase 6 독립 검수 결과 (2026-07-30)

이 절은 아래 Phase 6 최초 구현 기록보다 최신이며 현재 상태의 기준이다.

- 판정: **조건부 진행 가능**
- 최신 migration: `r4g7h8i9j0k1 (head)`
- 현재 계산 계약: `phase6-backtest-v2`, `phase6-rule-v2`
- 전체 테스트: **192 passed, 0 failed**
- 정적·구조 검증:
  - `compileall` 통과
  - Ruff 전체 통과
  - Pyright `0 errors, 0 warnings`
  - `app`·`scripts` 109개 모듈 import 성공
  - AST 기준 `app` 101개 모듈의 순환 import 0개
  - Python 3.12.13, `pip check` broken requirement 0개
- 실행 검증:
  - 새 SQLite DB에 전체 migration을 직접 적용해
    `r4g7h8i9j0k1`, `integrity_check=ok`, foreign-key 위반 0건,
    테이블 37개를 확인했다.
  - 빈 DB에서 서비스와 앱을 초기화했고 최신 백테스트가 없는 상태를
    오류 없이 표시했다.
  - KRX·OpenDART·KIS·NAVER·ECOS 인증정보를 제거한 AppTest에서
    최초 화면과 백테스트 화면 모두 예외 0건, 예시 종목 0건이었다.
  - 무입력 Phase 6 CLI는 종료코드 2와
    `MISSING/UNAVAILABLE`, `metrics=null`,
    `POINT_IN_TIME_DATASET_MISSING`,
    `WALK_FORWARD_FOLDS_INSUFFICIENT`를 반환하고 같은 입력을 재사용했다.
  - 실제 Streamlit headless 서버를 기동해 HTTP 200을 확인한 뒤
    검증 프로세스를 종료했다.

### 독립 검수에서 수정한 결함

- 같은 지급일의 원 배당과 정정 배당을 모두 합산하거나, 평가 종료 뒤
  제출된 정정을 과거 성과에 소급할 수 있던 결함을 수정했다.
  지급 사업연도와 원접수번호 연결을 입력 계약에 추가하고, 각 평가
  종료일까지 이용 가능했던 최신 정정 한 건만 반영한다.
- 같은 날 지급된 정기배당과 특별배당처럼 서로 다른 접수 건은 정정으로
  오인하지 않고 모두 합산한다. 배당감액 비율도 지급 순서가 아니라
  지급 사업연도별 확정 DPS 합계로 비교한다.
- 12개월 청산가격이나 벤치마크가 선언된 데이터 종료일 뒤에 있어도
  짧은 기간으로 표시하며 계산하던 결함을 차단했다. 이제 해당 실행은
  `RESULT_OUTSIDE_DECLARED_DATA_PERIOD`로 `MISSING` 처리한다.
- config에 고배당 벤치마크를 설정하면 입력만 요구하고 결과에는 버리던
  실행되지 않는 경로를 수정했다. fold별 수익률, 누적 수익률과 전략
  초과수익률을 결과와 UI에 보존한다.
- 지수 출처, 가격 통화, 버전, 유니버스 원천, hash가 공백이거나
  64자리 비-16진수여도 통과하던 계약을 강화했다. Phase 6 모델은
  미정의 필드도 조용히 무시하지 않고 거부한다.
- 미래에 상장폐지 예정인 종목까지 `was_delisted=true`로 표시하던
  의미 오류를 실제 평가 구간에 정산된 경우만 참이 되도록 수정했다.
- fold 종료 수익률만으로 계산한 낙폭을 일반 일별 최대낙폭처럼 표시하지
  않고 `WALK_FORWARD_PRIMARY_HORIZON_FOLD_ENDPOINTS` 방법을 명시했다.
- 입력 원천과 최근 수집시각, score·추천·시장 규칙 버전을 UI에 표시한다.
- 785줄의 계산 파일을 orchestration 258줄, 체결·증거 게이트 465줄,
  성과 집계 245줄로 분리했다. provider와 service의 책임 혼합은 없다.

### 테스트 우선 수정 기록

- 독립 검수 전 전체 기준선은 프로젝트 내부 임시 경로에서
  **184 passed**였다. 기본 시스템 임시 경로는 권한 오류가 있어
  `123 passed, 69 setup errors`였고, 검수용 `--basetemp`를 명시했다.
- 정정 배당 중복·미래 정정 소급, 데이터 기간 초과, 고배당 벤치마크
  결과 누락, 출처·버전 계약 누락, 상장폐지 표시 오류를 재현한
  6건이 기존 코드에서 모두 실패하는 것을 확인한 뒤 수정했다.
- 공백 통화와 공백 고배당 벤치마크 계약, 같은 날의 독립 배당 보존,
  입력 출처·수집시각·낙폭 방법 보존 테스트를 추가했다.
- 최종 Phase 6 테스트 16건과 전체 **192건**이 모두 통과했다.

### 실제 데이터 및 API 상태

- KRX: `KRX_API_KEY` 미설정, `키 미설정`, 실제 HTTP 미호출
- OpenDART: `DART_API_KEY` 미설정, `키 미설정`, 실제 HTTP 미호출
- 한국투자증권: `KIS_APP_KEY`·`KIS_APP_SECRET` 미설정,
  `키 미설정`, 실제 HTTP 미호출
- NAVER API HUB: `NCP_APIGW_API_KEY_ID`·`NCP_APIGW_API_KEY` 미설정,
  `키 미설정`, 실제 HTTP 미호출
- ECOS: `BOK_API_KEY`·`ECOS_API_KEY` 미설정,
  `키 미설정`, 실제 HTTP 미호출
- KIND: 공식 공개 API 계약과 자동 수집 권한 미확인으로 `지원 보류`
- SQLite: 새 빈 DB 연결, migration과 무결성 검증 성공
- 공식 과거 유니버스·상장폐지 정산·시점 추천·검증 수정가격 묶음이
  없으므로 실제 투자성과나 생존편향 제거 완료는 주장하지 않는다.

## Phase 6 최초 구현 결과 (2026-07-30)

이 절은 최초 구현 당시 기록이며 현재 상태는 위 독립 검수 결과를 따른다.

- 판정: **조건부 진행 가능**
- 최신 migration: `r4g7h8i9j0k1 (head)`
- 전체 테스트: **184 passed, 0 failed**
- 정적·실행 검증:
  - `compileall` 통과
  - Ruff 전체 통과
  - Pyright `0 errors, 0 warnings`
  - `app`·`scripts` 107개 모듈 import 성공
  - Python 3.12.13, `pip check` broken requirement 0개
  - 빈 SQLite DB 전체 migration과 Phase 6 downgrade/upgrade 왕복,
    `integrity_check=ok` 통과
  - 기본 SQLite DB도 `r4g7h8i9j0k1 (head)`로 migration했고
    `integrity_check=ok`, foreign-key 위반 0건
  - 빈 DB·무인증 Streamlit 앱 초기화와 Phase 6 화면 진입 통과
  - 실제 Streamlit headless 서버 HTTP 200 확인 후 검증 프로세스 종료

### 구현 범위

- 현재 `stocks` 목록을 과거에 소급하지 않고, 시점별 유니버스 원천·구성
  hash·상장폐지 포함 여부를 명시한 `BacktestDataset`만 계산한다.
- 시점 유니버스가 현재 마스터이거나 불완전하고 상장폐지 이력이 없으면
  전체 실행을 `MISSING`으로 종료하며 일부 종목 성과도 표시하지 않는다.
- 재무정보와 정정공시는 제출일 다음 거래일부터만 사용할 수 있고,
  추천 신호 다음 거래일의 검증 수정시가로 체결한다.
- 1·3·6·12개월 수정종가 또는 공식 상장폐지 정산값으로 청산하고,
  보유기간 중 실제 지급된 확정 현금배당과 매수·매도 거래비용을 반영한다.
- KOSPI 벤치마크, 회전율, 누적·연환산·최대낙폭·변동성·샤프·승률,
  추천 후 기간별·시장국면별·산업별 성과를 계산한다.
- 기본 1개월 구간이 겹치거나 walk-forward fold, 수정가격, 공시 이력,
  배당 이력, 상장폐지 정산 또는 벤치마크가 불완전하면 숫자를 만들지 않는다.
- config·전체 입력·score/recommendation/market rule version과 canonical
  hash, 계산방법, 알려진 생존편향·누락 데이터를 `backtest_runs`에 저장한다.
  같은 config·입력·버전은 같은 저장 실행을 재사용한다.
- CLI `scripts.run_phase6_backtest`와 읽기 전용 Streamlit 백테스트 화면을
  추가했다. 입력 JSON이 없으면 운영 최신 종목으로 대체하지 않는다.

### 테스트 우선 구현 기록

- 모델이 없을 때 Phase 6 테스트가 collection error로 실패하는 것을 먼저
  확인한 뒤 모델·계산·저장을 구현했다.
- 누적 테스트에서 공시 가용일, 비용 포함 수익률, 상장폐지 정산과 fold
  기간 fixture 오류 4건을 확인해 계약과 fixture를 바로잡았다.
- 검증되지 않은 현재 유니버스가 결과 메타데이터에
  `POINT_IN_TIME_HISTORY`로 고정 표시되는 회귀 테스트를 먼저 실패시킨 뒤
  실제 입력 방식을 보존하도록 수정했다.
- 빈 입력에서 구체적인 `POINT_IN_TIME_DATASET_MISSING` 사유가 빠지는
  회귀 테스트를 먼저 실패시킨 뒤 누락 사유를 보강했다.
- 최종 Phase 6·migration·Streamlit 대상 33건과 전체 184건이 통과했다.

### 실제 데이터 상태

- KRX, OpenDART, 한국투자증권, NAVER API HUB 인증정보는 미설정이고
  KIND는 지원 보류 상태다. Phase 6는 이번 검증에서 실제 HTTP를 호출하지 않았다.
- 기본 DB는 활성 종목 0건, `backtest_runs` 0건이다.
- 검증용 빈 DB CLI는 종료코드 2, `MISSING/UNAVAILABLE`,
  `POINT_IN_TIME_DATASET_MISSING`, `WALK_FORWARD_FOLDS_INSUFFICIENT`,
  `metrics=null`, 유니버스 방식 `UNKNOWN`을 저장했다.
- 공식 과거 유니버스·상장폐지 정산·검증 수정가격·시점 추천 snapshot이 없어
  실제 수익률 숫자는 생성하거나 검증하지 않았다.

## Phase 5 독립 검수 결과 (2026-07-30)

이 절은 아래의 Phase 5 최초 구현 기록보다 최신이며, 현재 상태의 기준이다.

- 판정: **조건부 진행 가능**
- 최신 migration: `q3f6a7b8c9d0 (head)`
- 전체 테스트: **175 passed, 0 failed**
- 정적 검증:
  - `compileall` 통과
  - Ruff 전체 통과
  - Pyright `0 errors, 0 warnings`
  - `app`·`scripts` 102개 모듈 import 성공
  - AST 기준 로컬 import cycle 0개
- 의존성: Python 3.12.13, `pip check` broken requirement 0개
- 빈 SQLite DB에서 전체 migration, downgrade/upgrade 왕복, schema drift 검사를
  통과했다.
- 기본 SQLite DB도 `q3f6a7b8c9d0 (head)`로 migration했고 schema drift가 없다.
- 빈 DB·무인증 상태에서 앱 초기화와 Phase 5 화면 진입 예외가 없으며,
  예시 종목이나 가짜 가격·배당수익률·RSI·점수·추천·시장국면·백테스트를
  표시하지 않는다. OpenDART, NAVER API HUB, 한국투자증권의 미설정 환경변수와
  KIND 미지원 사유를 표시한다.
- Phase 5 CLI는 무인증 상태에서 `NOT_CONFIGURED`, 정상 데이터 저장 0건,
  종료 코드 2를 반환했다.
- Streamlit headless 서버는 실제 프로세스로 기동했고 HTTP 200 응답을 확인한 뒤
  검수 프로세스가 종료했다.

### 독립 검수에서 수정한 결함

- 과거 `as_of_date` 조회가 이후에 저장된 공시·뉴스 이벤트·애널리스트 의견·수급·
  프로그램매매·공매도를 포함할 수 있던 미래정보 참조를 차단했다.
- 과거 기준일 수집 시작일 계산, 중요공시 조회 및 정정공시 연결에도 같은 상한을
  적용했다.
- 현재 provider 호출 실패 또는 전체 미설정 상태를 과거 저장 데이터가
  `AVAILABLE`로 덮어쓰지 못하도록 수집 요약 상태 우선순위를 수정했다.
- 제목만으로 정정공시를 긍정·부정 확정하지 않고 `UNCLASSIFIED`/낮은 신뢰도로
  표시하며 원공시 확인이 필요하다고 명시했다.
- KIS 수량의 소수값, 공매도 음수 수량·금액, 0~100 범위 밖 비율을 provider
  모델과 DB 제약에서 모두 거부한다. 기존 부적합 `AVAILABLE` 행은 migration 시
  `CONFLICT`로 전환한다.
- KIS `tr_cont=M/F` 연속조회 신호가 있는데 다음 페이지를 수집하지 않은 응답은
  `PARTIAL_RESPONSE_UNSUPPORTED`로 실패 처리하고 부분 행을 저장하지 않는다.
- NAVER 공식 뉴스 검색 응답에 없는 언론사를 URL 호스트에서 추정하지 않는다.
- OpenDART 공시 접수일에 임의의 자정 시각을 붙이지 않고
  `접수일, 시각 미제공`으로 표시한다.
- Phase 5 UI의 폐기 예정 Streamlit 폭 인자를 현재 `width="stretch"`로 교체했다.
- 애널리스트 참고 데이터의 URL은 기사 원문이 아니라 `공식 API endpoint`로
  표시한다.

### 테스트 우선 수정 기록

- 위 결함을 재현하는 회귀 테스트를 먼저 추가해 실패를 확인한 뒤 코드를 수정했다.
- 주요 최초 실패:
  - Phase 5 회귀 묶음 10건 실패
  - 공시 시각 정밀도 helper 미구현으로 collection error
  - 미래 기준일 snapshot이 거부되지 않아 1건 실패
  - KIS 연속조회 첫 페이지만 `AVAILABLE`로 받아 1건 실패
  - Phase 5 Streamlit 폐기 인자 검사가 1건 실패
- 수정 후 Phase 5·migration·Streamlit 대상 테스트 46건과 전체 175건이 모두
  통과했다.

### 실제 API 상태

- OpenDART: `DART_API_KEY` 미설정, `NOT_CONFIGURED`, 실제 HTTP 미호출
- NAVER API HUB: `NCP_APIGW_API_KEY_ID`·`NCP_APIGW_API_KEY` 미설정,
  `NOT_CONFIGURED`, 실제 HTTP 미호출
- 한국투자증권: `KIS_APP_KEY`·`KIS_APP_SECRET` 미설정,
  `NOT_CONFIGURED`, 실제 HTTP 미호출
- KIND: 공식 공개 API 계약과 자동 수집 권한 미확인으로 `UNSUPPORTED`
- SQLite: 실제 연결·빈 DB와 기본 DB migration·schema 검증 성공
  (`integrity_check=ok`, foreign-key 위반 0건). 기본 DB의 종목·Phase 5 원자료·
  정규화 데이터는 모두 0건
- PostgreSQL: 서버가 제공되지 않아 실제 연결·migration 미검증

### 완료 조건 대비 상태

- 코드·계약·데이터 진실성·무데이터 UI·SQLite 실행 조건은 통과했다.
- 인증정보와 실제 KOSPI 데이터가 없어 실제 공시·뉴스·애널리스트·수급 결과를
  한 종목 이상에서 대조하는 완료 조건은 충족하지 못했다.
- 다음 Phase 구현 전 실제 자격증명으로 최소 한 종목의 공식 응답, 단위, 증분수집,
  정정 연결 및 연속조회 동작을 검증해야 한다.

## 현재 Phase

- Phase 6 시점정보 기반 백테스트
- 상태: 시점 입력 계약·계산 엔진·결과 저장·migration·CLI·Streamlit
  화면과 전체 192개 회귀 테스트 통과. 실제 point-in-time 데이터가 없어
  실제 수익률은 미검증
- 현재 종목 목록, 최신 정정공시, 미검증 가격을 과거 시점에 소급하지 않으며
  핵심 시점정보가 하나라도 부족하면 `MISSING`으로 저장하고 숫자를 숨김
- 다음 거래 가능 수정시가 체결, 수정종가/공식 상장폐지 정산 청산,
  확정 현금배당·거래비용·KOSPI 벤치마크를 포함함
- 1·3·6·12개월, 시장국면, 산업, 회전율과 walk-forward 성과를 계산함
- 설정된 경우 KOSPI 고배당 벤치마크의 fold·누적·초과 성과를 별도 보존함
- 입력 전체와 config·규칙 버전·hash·계산방법·생존편향·누락 데이터를
  보존하여 같은 입력과 버전의 결과를 재현함
- 현재 계산 계약은 `phase6-backtest-v2`, `phase6-rule-v2`
- Phase 7 이후 기능은 구현하지 않음

## 완료된 기능

- Phase 6 코드:
  - 시점별 유니버스·상장폐지 포함 이력을 강제하는 입력 계약
  - 제출일 다음 거래일 기준 재무·정정공시 가용 시점 검증
  - 다음 거래일 검증 수정시가 체결과 1·3·6·12개월 수정종가 청산
  - 공식 상장폐지 정산값, 확정 현금배당과 Decimal 거래비용 반영
  - KOSPI 벤치마크, 회전율, 시장국면별·산업별·추천 후 기간별 성과
  - primary horizon 비중첩 walk-forward 검증
  - 전체 config·입력·버전·결과 JSON과 canonical hash 영속화
  - `backtest_runs`와 migration `r4g7h8i9j0k1`
  - `scripts.run_phase6_backtest` CLI와 무데이터 숫자를 숨기는 백테스트 UI

- Phase 5 코드:
  - OpenDART 중요공시 접수일 증분 수집과 원응답·정규화 데이터 분리
  - 원·정정공시 별도 보존과 비모호한 정정공시 원본 연결
  - 공식 NAVER API HUB 뉴스 검색과 제목·제공 요약 범위 제한
  - canonical URL·내용 hash·2일 내 유사제목 기반 뉴스 중복 제거
  - config 기반 `phase5-event-rule-v1` 구조화 이벤트 분류와 계산근거
  - KIS 종목투자의견·투자자 일별매매·프로그램매매·공매도 provider
  - 목표주가·수급·프로그램·공매도 Decimal 저장과 누락/0 구분
  - 뉴스·이벤트·애널리스트·EPS 골격·수급·프로그램·공매도 테이블
  - Phase 5 migration `p2e5f6a7b8c9`, 독립 검수 제약 migration
    `q3f6a7b8c9d0`
  - provider별 연결·제공 가능 상태와 가짜 데이터 없는 Phase 5 UI
  - `scripts.update_phase5_events` 한 종목 증분수집 CLI

- Phase 4 코드:
  - 저장된 실제 KOSPI 유니버스 전체의 동일 기준시각 Phase 2 재계산
  - 최신 동일 기준시각 Phase 3 snapshot 결합과 보수적 최소 신뢰도
  - 회복 준비 완료·우량하지만 관망·과도할인 후보·일반 검토·투자배제·
    데이터 부족 6개 그룹
  - 강제필터 PASS/FAIL/MISSING/REVIEW_REQUIRED와 정확한 사유 보존
  - 종목별 원시 지표·정규화값·가중치·기여점·필터 결과 저장
  - 긍정 근거·반대/위험 근거·제외 사유·누락 데이터 정규화 저장
  - Phase 3 비반도체 동일가중 대비 종목 상대수익률 차이의 과도하락
    후보 점수. 인과관계로 표현하지 않고 적극추천·목표배분에서 제외
  - 데이터 신뢰도 기준 미달 시 점수를 낮춰 추천하지 않고 데이터 부족 처리
  - 종목·산업 공통 한도, 공식 코드가 들어온 경우의 기업집단 공통 한도
  - 배당주·성장주·현금 및 적색·주황·황색·녹색 시장국면별 목표비중
  - 15/25/35/25 config 분할 비중, 회차별 실행 조건과 전체 취소 조건
  - 검증된 수정종가만 기준가격으로 저장하고 미확인 목표가격 생성 금지
  - 사용자 입력 포트폴리오 설정과 보유종목, 투자배제 즉시 재검토,
    실제 비중의 종목한도 초과 시 부분 비중축소 검토
  - 추천 실행·설정·추천·사유·분할계획·보유·배분 테이블과 migration
    `n0c3d4e5f6a7`, 독립 검수 보완 migration `o1d4e5f6a7b8`
  - 추천하기 버튼, 중간 진행률, 주요 제외 종목 포함 결과표,
    종목별 근거·분할매수 상세와 포트폴리오 화면
  - `scripts.update_phase4_recommendations` 전체 유니버스 CLI

- Phase 3 코드:
  - 공식 KRX `KOSPI 시리즈 일별시세정보` 계약 필드만 사용하는 provider
  - 요청 `basDd`와 응답 `BAS_DD` 불일치, HTTP·schema·빈 응답 저장 차단
  - 원자료와 분리된 `index_daily` 증분 upsert와 기준일 단위 CLI
  - KOSPI 21·63·126·252거래일 고점·고점일·현재 낙폭
  - 검증된 단일 수정가격 원천과 구성종목 커버리지 게이트
  - 공식 산업분류 정확 코드 기반 자체 반도체 시총가중·동일가중 바스켓
  - 비반도체 시총가중·동일가중·중앙수익률, KOSPI 동일가중·중앙수익률
  - 상승종목 비율, 20일선·60일선 위 종목 비율
  - 종목별·삼성전자·SK하이닉스·반도체 전체 전일 시총 기여도 설명 추정치
  - 기준일 이전 확정 DPS 종목의 배당주 상대수익률
  - 반도체 주도 하락·시장 전반 투매·혼합형·불확실 분류
  - 적색·주황·황색·녹색·불확실 시장국면과 네 회복조건 독립 판정
  - config 임계값, `phase3-rule-v2`, 전체 계산 입력·규칙을 포함한
    결정적 입력 해시와 데이터 신뢰도
  - 주요 숫자별 출처·기준시각·수집시각·계산방법·품질·공식/자체 프록시 저장
  - `market_regime_snapshots`, `market_metric_records`,
    `market_contribution_records`와 migration `k7f0a1b2c3d4`,
    독립 검수 provenance migration `l8a1b2c3d4e5`,
    구버전 시세구분 보정 migration `m9b2c3d4e5f6`
  - 지수 수집·시장분석 CLI와 무데이터 오류를 표시하는 시장국면 대시보드

- Phase 2 코드:
  - KOSPI 일반주식, 공식 시장상태, 최신 감사, 유동성, 기업 이벤트,
    비금융업 재무위험 강제필터
  - 60일 중앙 거래대금, 최근 20일 무거래와 20일 중앙 거래대금 대비
    예정 주문금액 비율 검사
  - 금융업 별도 평가 골격과 일반 이자보상비율 적용 차단
  - 최근 5년 확정 DPS 연속성·안정성, 지배기업 순이익 배당성향,
    FCF 배당성향
  - 영업이익률, ROE, 부채비율, 영업현금흐름/지배기업 순이익
  - 양수 PER/PBR만 사용하는 산업 중앙값·백분위·IQR 완화와
    최소 표본 미달 시 상위 산업 fallback
  - 자체 역사 PER/PBR 중앙값·백분위
  - 완전성·최신성·공식 출처·교차검증·산업 표본·수정가격·계정 매핑
    데이터 신뢰도
  - 검증된 수정가격 기반 개별 종목 RSI·추세 진입 구성요소
  - 구성요소별 원시값·정규화값·가중치·기여점·설명과
    `score_version`·`rule_version`·입력 해시 저장
  - 강제필터·점수 구성요소·밸류에이션 비교 테이블과 migration
    `j6e9f0a1b2c3`
  - 한 종목 Phase 2 계산 CLI와 개별 종목 점수 탭
  - 기준일 이후 수집 데이터 차단, 원가격 0과 파생 입력 누락 구분,
    구버전 누락 신뢰도의 0점 변환 차단

- Phase 1C 코드:
  - 공식 OpenDART 공시검색·단일회사 전체 재무제표·배당에 관한 사항·
    회계감사인의 명칭 및 감사의견 endpoint와 확인된 필드만 사용하는 provider
  - 연결재무제표를 먼저 요청하고 공식 `013`일 때만 별도재무제표로 fallback
  - 공시 접수번호·제출일·원문 링크와 원·정정공시 보존
  - XBRL 표준계정 exact mapping, 계정 member context 자동 매핑 차단,
    미매핑값 원문 보존과 품질 로그
  - 당기·누적·전기·전기누적 원금액 분리 저장
  - 누적 분기값의 단독 분기 변환과 `전기연간+당기누적-전기누적` TTM 계산
  - 최근 5개 사업연도 확정 DPS, 현금배당총액과 배당결정 공시 메타데이터
  - 최신 감사의견·감사인·강조사항·핵심감사사항과 계속기업 확인 상태
  - 수정가격 `VERIFIED`를 강제하는 Wilder RSI 14, SMA 20·60·120·200,
    ATR 14, 52주 고점 대비 낙폭
  - 한 종목 단위 증분수집 CLI와 개별 종목 배당·재무·감사·기술·원자료 탭
  - Phase 1C migration `g3b6c7d8e9f0`, `h4c7d8e9f0a1`,
    `i5d8e9f0a1b2`

- Phase 1B 코드:
  - 공식 KRX `유가증권 일별매매정보` 계약 필드만 사용하는 provider
  - 키 미설정·HTTP 오류·스키마 오류·빈 응답을 정상 가격으로 저장하지 않는 수집 경로
  - 기준일·수집시각·전일종가 상태·수정가격 미검증 상태를 구분한 가격 저장
  - 결측 수량·거래대금·시가총액을 0으로 바꾸지 않는 nullable 조회 모델
  - 중복 종목 식별자를 임의 매핑하지 않고 충돌 품질 로그로 남기는 repository
  - 공식 단위 미검증 가격을 `단위 미검증`으로 표시하는 종목 검색 UI
  - 잘못 가정해 저장된 KRX `KRW` 값을 제거하는 Alembic 데이터 보정 migration

- Phase 1A 코드:
  - 공식 KRX `유가증권 종목기본정보` endpoint와 확인된 응답 필드만 사용하는 provider
  - 공식 OpenDART `고유번호` ZIP/XML endpoint와 확인된 응답 필드만 사용하는 provider
  - timeout, retry, exponential backoff, 기관별 rate limit
  - Pydantic 응답 스키마 검증과 응답 크기 제한
  - 인증정보를 제외한 요청 해시, 응답 해시, 원자료 파일과 DB 메타데이터 보존
  - 같은 요청·응답 해시의 원자료 중복 저장 방지
  - KRX 공식 시장·증권·소속부·주식종류 원문 보존
  - ETF, ETN, ELW, 스팩, 리츠, 신주인수권증권·증서 정규화
  - 종목명 규칙으로 보통주·우선주를 자동 추정하지 않고 미확인 값은 `REVIEW_REQUIRED`
  - OpenDART `stock_code` 6자리와 KRX 종목코드의 정확 일치 매핑
  - 종목·분류 증분 upsert와 데이터 품질 로그
  - 종목명·6자리 코드 검색 repository와 Streamlit 검색 화면
  - 데이터가 없을 때 빈 목록과 실제 KRX 연결 필요 오류 표시

- Python 3.12.13 가상환경과 `pyproject.toml` 기반 의존성 설치
- `.env.example`, `.gitignore`, 초보자용 설치·migration·실행 안내 작성
- `pydantic-settings` 설정과 인증정보 마스킹
- 민감한 키·토큰·계좌번호 할당문을 가리는 로깅 필터
- SQLAlchemy 2 기반 SQLite 연결과 `DATABASE_URL` PostgreSQL 지원
- SQLite 외래키 활성화와 DB 상위 디렉터리 자동 생성
- Alembic 초기 revision `7f491f98f46e`
- Phase 0B 필수 테이블 14개 생성:
  - `stocks`
  - `stock_classifications`
  - `market_status`
  - `price_daily`
  - `financial_statements`
  - `financial_accounts`
  - `financial_metrics`
  - `dividends`
  - `audit_opinions`
  - `disclosures`
  - `api_raw_responses`
  - `data_quality_logs`
  - `score_snapshots`
  - `recommendations`
- 금액·수량을 `NUMERIC`으로 저장하고 결측을 nullable로 유지
- 연결·별도 재무제표, 누적 여부, 정정공시, 수정가격 여부, 점수·규칙 버전, 입력 해시를 저장할 스키마 마련
- 공통 읽기 전용 provider 추상 인터페이스
- `AVAILABLE`, `NOT_CONFIGURED`, `NOT_VERIFIED`, `FETCH_FAILED`, `STALE`, `MISSING`, `CONFLICT`, `UNSUPPORTED` 응답 상태 모델
- 출처·기능명·기준시각·수집시각·시세구분·재무범위·추정 여부 메타데이터 모델
- API 오류 상태에 정상 payload가 포함되지 않도록 Pydantic 검증
- Streamlit 기본 메뉴와 데이터 품질·API 연결상태 화면
- 무키 상태에서 KRX, OpenDART, 한국투자증권, 네이버 뉴스, ECOS를 `키 미설정`으로 표시
- KIND를 공식 공개 API 계약 확인 전 `지원 보류`로 표시
- DB 연결과 필수 테이블 확인 성공 시 `연결됨`으로 표시
- 미래 Phase 메뉴에 데이터 연결 필요 상태만 표시하고 종목·시장 숫자 미표시

## 부분 완료된 기능

- Phase 5 실제 결과: provider·저장·UI·CLI는 구현했으나 인증정보가 없어
  실제 외부 HTTP를 수행하지 못했고 운영 DB의 Phase 5 원응답·이벤트·뉴스·
  애널리스트·수급·프로그램·공매도는 모두 0건임
- Phase 5 계약 제한: KIND 자동수집과 KIS EPS·대차·신용 정규화는 공식
  계약이 충분히 검증되지 않아 상태 표시만 구현함
- Phase 4 실제 결과: 서비스·저장·UI·CLI는 구현했으나 운영 DB 활성
  KOSPI 종목이 0건이고 Phase 3 공식 입력이 없어 실제 추천은
  `MISSING`으로만 검증함
- Phase 4 진입준비: 수급을 제외한 85점 범위만 명시적으로 정규화하며
  Phase 5 수급 15점이 포함된 전체 진입준비 점수는 계산하지 않음
- Phase 4 기업집단: 설정·스키마·공통 한도 엔진은 구현했으나 공식
  기업집단 writer가 없어 실제 행은 `NOT_AVAILABLE`
- PostgreSQL: 드라이버와 URL 지원 코드는 포함했으나 실제 PostgreSQL 서버 migration은 미검증
- KRX·OpenDART: 종목·일별가격·재무·배당·감사 provider와 수집 경로는
  구현했으나 인증키 미설정으로 실제 HTTP·응답 스키마·수치 단위 연결은 미검증
- 유니버스: 공식 상품·주식종류 분류는 구현했으나 거래정지·관리종목 공식 계약이 없어 일반 보통주도 최종 `ELIGIBLE` 대신 `REVIEW_REQUIRED`
- Phase 2 실제 입력: 공식 시장상태·산업분류·기업 이벤트 writer가 없어
  현재 운영 DB에서는 해당 필터를 `MISSING`으로 차단함
- Phase 2 점수 범위: 이번 Phase에서 확보 가능한 배당 25점·재무 25점·
  밸류에이션 20점의 합 70점을 `PHASE2_CORE_ONLY` 범위로 정규화함.
  후속 30점과 전체 진입준비는 계산하지 않음
- Phase 3 실제 입력: KRX KOSPI 지수 provider와 계산 경로는 구현했으나
  KRX 키·공식 산업분류 writer·KIS 수정가격 provider가 없어 운영 결과는
  `UNCERTAIN`으로 차단함
- Streamlit: 빈 DB·무키·저장된 Phase 2/3 누락 판정을 AppTest로 검증하고,
  실제 서버를 포트 8773에서 기동해 HTTP 200 확인 후 종료함

## 미구현 기능

- 한국은행 ECOS provider adapter와 외부 API 호출
- KRX·OpenDART 실제 인증 호출과 실제 종목 원자료
- 관리종목·거래정지·상장폐지 공식 상태 provider
- KIS 현재가·공식 수정주가와 운영 기술지표
- 관리종목·거래정지·상장폐지 위험·기업 이벤트·공식 산업분류 수집 writer
- 금융업 은행·보험·증권별 규제지표 평가모형
- 공식 산업분류 수집 writer와 공식 반도체 지수 구성종목 계약
- KIS 검증된 수정가격 수집 provider와 실제 KOSPI 전체 가격 이력
- Phase 5 이벤트·애널리스트·수급을 반영한 전체 기본 투자매력 점수
- Phase 3 시장국면·반도체·시장 폭은 구현됐으나 수급을 포함한 전체
  진입준비 점수는 미구현
- KIND 공식 이벤트 자동수집, KIS EPS·대차·신용 정규화
- 수급 15점을 포함한 전체 진입준비 점수
- 공식 기업집단 매핑 writer와 실제 기업집단 집중도 자동검증
- 산업조정 과도하락 점수와 기업별 숨은 악재 원문 자동검토
- Phase 6 공식 과거 유니버스·상장폐지·수정가격 입력 writer와 실제 장기 실행
- 자동주문·계좌 쓰기 기능은 전체 프로젝트 금지 범위

## 생성·수정한 파일

- `pyproject.toml`: Python 3.12 및 실행·개발 의존성
- `.env.example`: 인증정보와 DB 환경변수 이름
- `.gitignore`: 비밀정보, 가상환경, DB, 캐시 제외
- `README.md`: 설치, 환경변수, migration, 앱, 테스트 실행법
- `alembic.ini`, `migrations/`: migration 환경과 초기 schema revision
- `app/config.py`: 환경설정
- `app/logging_config.py`: 민감정보 마스킹 로깅
- `app/utils/dates.py`: `Asia/Seoul` 인지 시각 처리
- `app/models/`: 데이터 메타데이터와 연결상태 모델
- `app/providers/base.py`: 공통 provider와 응답 envelope
- `app/db/`: SQLAlchemy 연결, Base, 14개 테이블 모델
- `app/services/connection_status.py`: 키 구성과 DB schema 상태 판정
- `app/ui/`: 연결상태·보류 화면과 참고 이미지 기반 다크 테마
- `app/main.py`: Streamlit 진입점과 기본 메뉴
- `tests/`: 설정·시간·provider·schema·migration·연결상태·import·Streamlit 테스트
- `docs/IMPLEMENTATION_STATUS.md`: Phase 0B 실제 결과
- `docs/DECISIONS.md`: Phase 0B 범위와 상태 판정 결정
- `docs/KNOWN_LIMITATIONS.md`: 남은 실행·데이터 제약
- `docs/CHANGELOG.md`: Phase 0B 변경 이력

## 실제 실행한 명령

- `& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv`
- `.\.venv\Scripts\python.exe -m ensurepip --upgrade`
- `.\.venv\Scripts\python.exe -m pip install --upgrade pip`
- `.\.venv\Scripts\python.exe -m pip install -e '.[dev]'`
- 설치 제한시간 이후 누락 패키지를 작은 묶음으로 재실행한 `pip install` 명령
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m compileall -q app migrations`
- `.\.venv\Scripts\python.exe -c "import ..."`
- `.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m 'phase 0b initial schema'`
- `.\.venv\Scripts\python.exe -m alembic upgrade head`
- `.\.venv\Scripts\python.exe -m alembic current`
- `.\.venv\Scripts\python.exe -m alembic stamp head`
- `.\.venv\Scripts\python.exe -m alembic check`
- SQLAlchemy로 필수 테이블·빈 테이블·연결상태를 확인하는 Python 명령
- `.\.venv\Scripts\python.exe -m pytest`
- Streamlit AppTest를 포함한 pytest 재실행
- 포트 8502 수신 여부와 Streamlit 프로세스 확인 명령
- Streamlit 백그라운드 기동을 두 차례 시도했으나 PowerShell 환경의 `Path`/`PATH` 중복 오류와 사용자 중단으로 지속 서버 검증은 완료하지 않음

## 테스트 결과

- 상태: 통과
- pytest: 16 passed, 0 failed
- 전체 애플리케이션 모듈 import: 통과(`IMPORT_OK`)
- `pip check`: 통과(`No broken requirements found`)
- Python bytecode compile: 통과
- migration 생성 첫 시도: 실패(`data/` 디렉터리 미생성)
- migration 경로 준비 수정 후 재시도: 통과
- revision 회귀 테스트 추가 전: 실패(`alembic_version` 행 없음)
- SQLite PRAGMA transaction 종료 수정 후 revision 회귀 테스트: 통과
- 기존 빈 기본 DB revision 복구: `alembic stamp head` 성공
- 기본 SQLite migration `upgrade head`: 통과
- Alembic revision: `7f491f98f46e`
- Alembic schema drift 검사: 통과(`No new upgrade operations detected`)
- 필수 DB 테이블: 14개 모두 존재
- 필수 테이블 데이터 행: 모두 0개
- DB 연결상태: `연결됨`
- 무키 provider 상태: 5개 기관 `키 미설정`
- KIND 상태: `지원 보류`
- 키가 설정된 경우 실제 호출 전 `연결 미검증`: 테스트 통과
- API 오류 payload 차단: 테스트 통과
- naive datetime 거부와 `Asia/Seoul` 인지 시각: 테스트 통과
- Streamlit AppTest 초기화: 통과
- Streamlit 기본 연결상태 화면과 미래 Phase 보류 메뉴: 통과
- 화면 내 금지 예시 종목·코드·가격·점수 문자열: 발견 0
- 장시간 Streamlit 서버 검증: 사용자 지시에 따라 추가 대기 없이 종료; 현재 포트 8502는 수신 중이 아님

## API별 연결 상태

| 기관 | 화면 상태 | 실제 호출 | 비고 |
|---|---|---|---|
| KRX | 키 미설정 | 미수행 | `KRX_API_KEY` 필요 |
| OpenDART | 키 미설정 | 미수행 | `DART_API_KEY` 필요 |
| 한국투자증권 | 키 미설정 | 미수행 | 앱키·시크릿 필요 |
| KIND | 지원 보류 | 미수행 | 공개 API 계약·자동수집 권한 미확인 |
| 네이버 뉴스 | 키 미설정 | 미수행 | API HUB 인증정보 필요 |
| ECOS | 키 미설정 | 미수행 | ECOS 인증키 필요 |
| 데이터베이스 | 연결됨 | `SELECT 1` 및 schema 확인 성공 | SQLite 기본 DB |

## 실제 API 호출 성공 여부

- 성공한 외부 API 호출 없음
- 인증정보가 미설정이므로 호출하지 않음
- DB 로컬 연결과 schema 확인만 실제 성공
- 예시 응답이나 합성 응답을 실제 원자료로 저장하지 않음

## 현재 확인된 데이터 기준일

- 실제 시장·종목·가격·재무·배당·공시·뉴스 데이터 기준일: 없음
- DB 생성·migration 검증일: 2026-07-28~2026-07-29 KST
- 문서나 이미지의 예시 숫자를 데이터로 사용하지 않음

## 데이터상 제약

- 외부 API가 연결되지 않아 실제 데이터가 없음
- `api_raw_responses`를 포함한 모든 도메인 테이블은 비어 있음
- KRX 공식 산업분류 계약이 미확인이라 반도체 프록시와 산업 상대평가를 계산할 수 없음
- PostgreSQL 실제 서버 호환성은 아직 미검증
- KIND 자동 연동은 별도 계약·권한 확인 전 금지
- 추천·점수·시장국면·백테스트를 계산할 핵심 데이터가 없음

## 다음 작업

- Phase 0B 종료
- Phase 1A의 구체적인 데이터 범위와 검증 조건을 사용자 지시로 확정한 뒤 구현
- 다음 작업 시작 전 필수 상태 문서 4개 재확인
- 인증정보가 제공되면 기관별 읽기 전용 최소 호출부터 수행하고 HTTP 상태·스키마·응답 해시·기준일을 보존
- 미확인 endpoint·필드·단위를 provider에 추가하지 않음

## 마지막 갱신시각

- 2026-07-29 02:10:10 KST (Asia/Seoul)

## 완료 판정

- 완료 및 검증됨
- 사용자 지시에 따라 장시간 Streamlit 서버 대기는 완료 조건에서 제외하고, 성공한 AppTest·import·migration·pytest를 앱 초기화 검증 근거로 사용함

---

## Phase 0B 독립 검수 결과 (2026-07-29)

### 현재 Phase

- Phase 0B 프로젝트 기반 구조 구축
- 상태: 독립 검수 및 결함 수정 완료
- Phase 판정: 다음 Phase 진행 가능

### 발견 및 수정한 문제

- High: `AVAILABLE` provider 응답이 HTTP 4xx·5xx여도 정상 payload로 검증될 수 있었음.
  - `ApiResponse`에서 `AVAILABLE`이면 HTTP 2xx를 필수로 검증하도록 수정함.
  - `api_raw_responses`에도 같은 불변조건을 CHECK constraint로 추가함.
- Medium: `.env.example`을 그대로 복사한 빈 `DATABASE_URL`, `LOG_LEVEL`, `APP_ENV` 값이 안전한 기본값을 덮어 앱 초기화를 실패시킬 수 있었음.
  - `pydantic-settings`의 `env_ignore_empty=True`를 적용함.

### 생성·수정한 파일

- `app/config.py`
- `app/providers/base.py`
- `app/db/models/quality.py`
- `migrations/versions/b8c1d2e3f4a5_enforce_raw_response_truth.py`
- `migrations/versions/c9d2e3f4a5b6_require_available_http_status.py`
- `tests/test_config_and_time.py`
- `tests/test_provider_models.py`
- `tests/test_migration_and_schema.py`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/CHANGELOG.md`

### 실제 실행한 명령

- `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m pip show ruff pyright mypy pyflakes`
- `.\.venv\Scripts\python.exe -m compileall -q app migrations tests`
- 전체 `app` 패키지를 순회하여 import하는 Python 명령
- 전체 `app` Python 파일을 AST parse하는 Python 명령
- 결함 재현용 대상 pytest 명령
- `.\.venv\Scripts\python.exe -m alembic upgrade head`
- `.\.venv\Scripts\python.exe -m alembic current`
- `.\.venv\Scripts\python.exe -m alembic check`
- 빈 임시 SQLite DB에 대한 Alembic·AppTest 검증 명령
- `.\.venv\Scripts\python.exe -m streamlit run app/main.py --server.headless true --server.port 8503 --browser.gatherUsageStats false`
- `Get-NetTCPConnection -LocalPort 8503 -State Listen`
- `rg` 기반 광범위 예외·endpoint·샘플 숫자·누락값 0 변환 패턴 검사

### 테스트 결과

- 수정 전 회귀 테스트: 총 6개 실패 사례 재현
  - 빈 `.env` 기본값 덮어쓰기 1건
  - 비정상 HTTP 상태의 `AVAILABLE` 허용 3건
  - HTTP 500 원응답을 `AVAILABLE`로 DB 저장 가능 1건
  - HTTP 상태가 없는 원응답을 `AVAILABLE`로 DB 저장 가능 1건
- 수정 후 대상 테스트: 10 passed
- 최종 전체 pytest: 22 passed, 0 failed
- `pip check`: `No broken requirements found`
- AST parse: application Python 파일 26개 성공
- 전체 application module import: 25개 성공
- compileall: 성공
- Alembic: 기본 DB와 빈 DB 모두 `c9d2e3f4a5b6 (head)`, schema drift 없음
- 빈 DB·API 키 미설정 AppTest: 예외 없음, 금지된 샘플 숫자 0건
- Streamlit 실제 프로세스: 8503 포트에서 시작 성공, 10초 제한 종료 후 포트 닫힘 확인

### API별 연결 상태 및 실제 호출 성공 여부

| 기관 | 화면 상태 | 실제 호출 |
|---|---|---|
| KRX | 키 미설정 | 미수행 |
| OpenDART | 키 미설정 | 미수행 |
| 한국투자증권 | 키 미설정 | 미수행 |
| KIND | 지원 보류 | 미수행 |
| 네이버 뉴스 | 키 미설정 | 미수행 |
| ECOS | 키 미설정 | 미수행 |
| 데이터베이스 | 연결됨 | `SELECT 1`, 필수 14개 테이블 및 migration 확인 성공 |

### 현재 확인된 데이터 기준일

- 실제 시장·종목·가격·재무·배당·공시 데이터 기준일 없음
- DB/migration 검수일: 2026-07-29 KST

### 데이터상 제약

- 외부 provider adapter와 수집 service는 Phase 0B 범위 밖이므로 실제 HTTP 응답은 없음.
- 공식 데이터와 자체 계산값 구분은 `source_provider`, `source_function`, 원자료/정규화 테이블 및 계산 규칙 해시에 의존하며 별도 `source_kind` 제약은 없음.
- SQLite는 DB 자체에서 timezone-aware datetime을 강제하지 않아 검증 계층을 우회한 직접 저장은 차단되지 않음.
- 실제 PostgreSQL 서버 migration은 미검증임.

### 다음 작업

- Phase 1A 시작 전 필수 상태 문서 4개를 다시 읽고 구체 범위와 검증 조건을 확인함.
- Phase 1A 범위 밖 분석·추천·점수·백테스트 기능은 선행 구현하지 않음.

### 마지막 갱신시각

- 2026-07-29 02:22:57 KST (Asia/Seoul)

---

## Phase 1A 실행 결과 (2026-07-29)

### 생성·수정한 파일

- `pyproject.toml`: `httpx` 의존성과 `scripts` 패키지 포함
- `.env.example`: Phase 1A HTTP·원자료 설정 변수
- `README.md`: API 키 등록, migration, 증분갱신, 종료코드 안내
- `app/config.py`: timeout·retry·backoff·rate limit·원자료 경로 설정
- `app/models/stock.py`: KRX·OpenDART 계약 모델, 분류·검색·갱신 결과 모델
- `app/providers/krx.py`: 유가증권 종목기본정보 provider
- `app/providers/dart.py`: OpenDART 고유번호 ZIP/XML provider
- `app/utils/http.py`: timeout을 사용하는 재시도·지수 backoff·rate limiter
- `app/services/stock_classification.py`: 공식 분류 필드 전용 정규화
- `app/services/universe_service.py`: 수집·원자료 저장·정규화·매핑 orchestration
- `app/repositories/stock_repository.py`: 종목·분류 증분 upsert와 검색
- `app/repositories/raw_response_repository.py`: 원자료 파일·메타데이터·중복 방지
- `app/repositories/data_quality_repository.py`: 데이터 품질 로그
- `app/db/models/market.py`, `app/db/models/quality.py`: Phase 1A 컬럼·제약
- `migrations/versions/d0e3f4a5b6c7_phase_1a_stock_universe.py`: Phase 1A migration
- `scripts/update_stock_master.py`: 종목 마스터 증분갱신 CLI
- `app/ui/stock_search.py`, `app/main.py`: 종목 검색 메뉴·무데이터 오류 UI
- `tests/test_stock_classification.py`
- `tests/test_dart_parser.py`
- `tests/test_stock_repository.py`
- `tests/test_universe_service.py`
- `tests/test_streamlit_app.py`
- `tests/test_migration_and_schema.py`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/DECISIONS.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/CHANGELOG.md`

### 실제 실행한 명령

- `.\.venv\Scripts\python.exe -m pip install -e '.[dev]'`
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- 전체 `app`·`scripts` AST parse 및 module import 명령
- `.\.venv\Scripts\python.exe -m alembic upgrade head`
- `.\.venv\Scripts\python.exe -m alembic current`
- `.\.venv\Scripts\python.exe -m alembic check`
- 빈 임시 SQLite DB에 대한 migration·schema drift 검사
- `.\.venv\Scripts\python.exe -m scripts.update_stock_master --as-of 2026-07-29`
- `.\.venv\Scripts\python.exe -m scripts.update_stock_master --help`
- `.\.venv\Scripts\python.exe -m pytest`
- `.\.venv\Scripts\python.exe -m streamlit run app/main.py --server.headless true --server.port 8505 --browser.gatherUsageStats false`
- 실제 로컬 Streamlit 검색 화면의 DOM·금지 문자열 검사
- `rg` 기반 광범위 예외·가짜 종목/가격·누락값 0 변환 패턴 검사

### 테스트 결과

- pytest: 37 passed, 0 failed
- `pip check`: `No broken requirements found`
- AST·import: Python 파일 39개 parse, application module 37개 import 성공
- compileall: 성공
- Alembic: `d0e3f4a5b6c7 (head)`
- schema drift: 없음
- 빈 DB migration: 성공
- 무키 CLI: `NOT_CONFIGURED`, 종료코드 2, 저장 종목 0
- DB 행 수: `stocks=0`, `stock_classifications=0`, `api_raw_responses=0`, `data_quality_logs=1`
- 실제 Streamlit 서버: 시작 성공 후 종료, 포트 닫힘 확인
- 실제 검색 UI: 검색창과 KRX 데이터 없음 오류 확인
- UI 금지 문자열: 예시 코드·가격·배당수익률·RSI·추천점수 0건
- 광범위 `except Exception`, 운영 샘플 숫자, 누락값 0 변환 패턴: 0건

### API별 연결 상태

| 기관 | 상태 | 실제 호출 |
|---|---|---|
| KRX | 키 미설정 | 미수행 |
| OpenDART | 키 미설정 | 미수행 |
| 한국투자증권 | 키 미설정 | Phase 1A 범위 밖 |
| KIND | 지원 보류 | Phase 1A 자동수집 범위 밖 |
| 네이버 뉴스 | 키 미설정 | Phase 1A 범위 밖 |
| ECOS | 키 미설정 | Phase 1A 범위 밖 |
| 데이터베이스 | 연결됨 | migration·필수 테이블 조회 성공 |

### 실제 API 호출 성공 여부

- 성공한 외부 API 호출 없음
- `KRX_API_KEY`, `DART_API_KEY`가 모두 미설정이라 공식 최소 호출을 수행하지 않음
- 공개 샘플이나 합성 응답을 실제 원자료로 저장하지 않음

### 현재 확인된 데이터 기준일

- 실제 KRX·OpenDART 데이터 기준일 없음
- 사용자가 지정한 무키 CLI 요청 기준일 `2026-07-29`는 API 데이터 기준일로 간주하지 않음
- 코드·DB·UI 검증일: 2026-07-29 KST

### 데이터상 제약

- KRX 종목기본정보 계약에는 거래정지·관리종목 상태가 없어 일반 보통주의 최종 투자 유니버스 적격을 확정하지 않음.
- 상장폐지는 성공한 전체 기준일 종목 마스터에서 누락됐다는 사실만으로 자동 확정하지 않음.
- KRX 공식 분류 값은 실제 응답으로 아직 검증하지 못했으며 미확인 값은 `REVIEW_REQUIRED`.
- OpenDART는 공식 `stock_code` 정확 일치만 매핑하며 종목명 유사도 매핑을 하지 않음.
- 실제 PostgreSQL migration과 원자료 대용량 동작은 미검증.

### 다음 작업

- Phase 1A 완료 검증을 위해 실제 KRX·OpenDART 키 설정 후 읽기 전용 최소 수집을 실행하고 HTTP 상태·응답 스키마·해시·기준일을 확인해야 함.
- 실제 분류 값과 미매핑·충돌 건수를 검토한 뒤에만 Phase 1A를 `완료 및 검증됨`으로 변경함.
- 가격·재무·배당·감사·추천 등 다음 Phase 기능은 구현하지 않음.

### 마지막 갱신시각

- 2026-07-29 02:48:36 KST (Asia/Seoul)

### 완료 판정

- 코드 작성 완료·API 연결 미검증

---

## Phase 1A 독립 검수 결과 (2026-07-29)

### 발견한 문제

- Critical: 없음.
- High:
  - KRX 공식 필드의 `null`과 잘못된 달력 날짜가 빈 문자열 또는 지연된 repository 오류로 흡수될 수 있었음.
  - OpenDART 성공 본문이 공식 계약의 ZIP 형식이 아니어도 정상 목록으로 처리될 수 있었음.
  - 연결상태가 가장 최근 실패보다 과거 성공 원응답을 우선해 `연결됨`으로 표시될 수 있었음.
  - OpenDART 고유번호의 변경일·수집시각·현재 매핑 상태가 검색 결과 provenance에 분리되지 않았음.
- Medium:
  - KRX 상품·주식종류 값을 부분 문자열로 판정하여 미검증 복합값을 자동 확정할 수 있었음.
  - KOSPI 여부가 공식 시장구분과 별도 정규화 필드로 보존되지 않았음.
  - SQLite에서 읽은 datetime의 timezone offset이 제거된 상태로 UI에 전달될 수 있었음.
  - DB 문자열을 Pydantic enum과 `HttpUrl` 입력에 암묵적으로 전달하는 타입 불일치 7건이 있었음.
- Low:
  - import 정렬 문제 25건이 있었음.
  - 독립 정적 분석 도구가 기존 개발환경에 설치돼 있지 않았음.

### 수정한 내용

- `app/models/stock.py`
  - KRX `null`, 필수 빈값, 잘못된 `LIST_DD`를 schema validation 단계에서 거부함.
  - `is_kospi`, OpenDART 변경일·수집시각·상태와 timezone-aware 검색 모델을 추가함.
- `app/providers/dart.py`
  - 성공 응답은 공식 ZIP 계약만 허용하고 오류 XML만 별도로 판독함.
  - XML 필수 element 누락과 허용된 빈 선택 element를 구분함.
- `app/providers/krx.py`, `app/repositories/stock_repository.py`
  - `HttpUrl`과 DB enum 변환을 명시해 타입 불일치를 제거함.
  - KOSPI 여부와 OpenDART provenance를 저장·조회함.
- `app/services/stock_classification.py`
  - 공식 분류값의 정확 일치만 자동 분류하고 복합·미확인 값은 `REVIEW_REQUIRED`로 유지함.
- `app/services/connection_status.py`
  - provider별 가장 최근 원응답을 기준으로 성공·실패를 판정하고 KST 수집시각을 표시함.
- `app/services/universe_service.py`, `app/ui/stock_search.py`, `app/utils/dates.py`
  - OpenDART 수집 상태 전달, KRX/OpenDART 기준일·수집시각 분리 표시, SQLite KST 복원을 적용함.
- `app/db/models/market.py`
  - `is_kospi`, `dart_collected_at`, `dart_data_state`를 추가함.
- `migrations/versions/e1f4a5b6c7d8_phase_1a_audit_fixes.py`
  - Phase 1A 독립 검수 보완 migration을 추가함.
- `tests/`
  - 발견한 결함의 실패 재현과 수정 후 회귀 테스트를 추가함.
- `app/`, `scripts/`, `tests/`, `migrations/`
  - Ruff로 import 순서를 기계적으로 정리함.

### 실제 실행한 명령

- 필수 문서 5개를 `Get-Content -Encoding utf8`로 읽는 명령
- `rg --files` 및 `rg` 기반 예외·datetime·누락값 변환·하드코딩 숫자·endpoint·인증정보 사용 검사
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m pip show ...`
- `.\.venv\Scripts\python.exe -m pip install ruff pyright`
- `.\.venv\Scripts\python.exe -m ruff check ...`
- `.\.venv\Scripts\python.exe -m pyright --pythonpath .\.venv\Scripts\python.exe app scripts`
- 전체 `app`·`scripts` AST parse, module import, 내부 import cycle 검사 명령
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- 수정 전 결함 재현 대상 pytest 명령
- 수정 후 대상 pytest와 전체 `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe -m alembic upgrade head`
- `.\.venv\Scripts\python.exe -m alembic current`
- `.\.venv\Scripts\python.exe -m alembic check`
- 빈 임시 SQLite DB migration·테이블·행 수 검사 명령
- 빈 DB와 API 키 미설정 상태의 Streamlit AppTest 직접 초기화 명령
- `.\.venv\Scripts\python.exe -m scripts.update_stock_master --as-of 2026-07-29`
- Streamlit을 subprocess로 시작하여 `http://127.0.0.1:8515` HTTP 200을 확인하고 종료·포트 폐쇄를 검사한 명령
- `Start-Process` Streamlit 시도는 PowerShell `Path`/`PATH` 중복 오류로 시작 전에 실패함.
- 첫 전경 Streamlit 포트 검사 2회는 수신 확인에 실패해 프로세스를 종료했으며, subprocess 방식으로 최종 검증에 성공함.

### 테스트 결과

- 수정 전 결함 재현: 8건 실패 확인.
- 선택 element 빈값 추가 재현: 1건 실패 확인.
- 수정 후 전체 pytest: 45 passed, 0 failed.
- Ruff 핵심 검사(`F`, `E9`, `I`): 통과.
- Pyright: 0 errors, 0 warnings.
- AST·전체 module import: 39개 파일·39개 module 성공.
- 내부 순환 import: 없음.
- 최대 application module: 299행으로 단일 거대 파일 집중 문제 없음.
- compileall: 성공.
- Alembic: `e1f4a5b6c7d8 (head)`, schema drift 없음.
- 빈 DB: 핵심 4개 테이블 모두 0행으로 초기화 성공.
- 무키 CLI: `NOT_CONFIGURED`, 종료코드 2, 종목·분류·원응답 0행, 품질로그 1행.
- 실제 Streamlit: 포트 8515 HTTP 200, 종료 후 포트 폐쇄 확인.
- UI 금지 값: 예시 종목·가격·배당·RSI·점수·시장국면·백테스트 값 없음.

### 실제 API 상태

| 기관 | 상태 | 실제 호출 |
|---|---|---|
| KRX | 키 미설정 | 미수행 |
| OpenDART | 키 미설정 | 미수행 |
| 한국투자증권 | 키 미설정 | Phase 1A 범위 밖 |
| KIND | 지원 보류 | 미수행 |
| 네이버 뉴스 | 키 미설정 | Phase 1A 범위 밖 |
| ECOS | 키 미설정 | Phase 1A 범위 밖 |
| 데이터베이스 | 연결됨 | 기본 DB·빈 DB migration 및 조회 성공 |

### 데이터 진실성 검수

- API 오류는 정상 payload 또는 `AVAILABLE` 원응답으로 저장할 수 없음.
- 가격·금액·재무값은 nullable `NUMERIC`이며 0과 누락이 구분됨.
- 데이터 기준시각, provider 수집시각, OpenDART 변경일·수집시각이 분리됨.
- 가격의 실시간·지연·전일종가, 연결·별도, 누적 여부, 정정공시, 수정가격 여부를 저장할 schema는 존재함.
- Phase 1A에는 가격·재무 계산, 반도체 프록시, 추정값, 추천, 기술지표가 없어 해당 값을 생성하거나 표시하지 않음.
- 원자료 파일·원응답 메타데이터와 정규화 종목 테이블이 분리됨.
- 정확 일치 분류·매핑과 요청·응답 해시로 동일 입력의 결정적 처리를 유지함.

### 남아 있는 위험

- 실제 KRX·OpenDART 인증 호출과 실제 분류값·응답 크기·스키마는 여전히 미검증임.
- 거래정지·관리종목 공식 상태가 없어 일반 보통주를 최종 `ELIGIBLE`로 확정하지 않음.
- SQLite timezone 복원은 repository를 통해 KST로 저장한 wall-clock 값이라는 전제에 의존하며 직접 SQL 쓰기는 보장을 우회할 수 있음.
- 원자료 파일 기록 후 DB transaction이 실패하면 고아 원자료 파일이 남을 수 있음.
- 실제 PostgreSQL migration과 대용량 OpenDART ZIP 처리는 미검증임.

### 마지막 갱신시각

- 2026-07-29 03:11:43 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능

---

## Phase 2 구현 및 검수 결과 (2026-07-29)

### 구현 결과

- 강제필터 결과를 `PASS`, `FAIL`, `MISSING`, `REVIEW_REQUIRED`,
  `NOT_APPLICABLE`로 분리하고 실패·누락을 점수로 상쇄하지 않음.
- 핵심 투자매력 구성요소 12개, 데이터 신뢰도 구성요소 7개,
  개별 종목 진입 구성요소 2개의 원시값·정규화값·가중치·기여점·
  계산근거를 저장함.
- 산업 세부분류의 유효 표본이 설정값보다 작으면 상위 산업을 사용하고,
  상위 산업도 부족하면 비교 불가로 처리함.
- 현재 PER가 0 이하이면 `N/M`으로 보존하고 저평가 기여점을 부여하지 않음.
- 금융업은 일반 이자보상·제조업 품질비율을 적용하지 않고 금융업 별도
  모형 입력 부족으로 처리함.
- 설정 기반 임계값·가중치와 `score_version`, `rule_version`,
  결정적 입력 데이터 해시를 적용함.
- 기준일 이후 수집된 종목·시장상태·산업분류·역사 밸류에이션을
  점수 입력에서 제외함.
- 재무 원자료가 없을 때 계정 매핑률, 가격 원자료가 없을 때 수정가격
  확인 상태를 0점이 아닌 `MISSING`으로 유지함.
- 전체 100점 투자매력 중 후속 Phase 입력 30점은 만들지 않고,
  현재 70점 구성만 `PHASE2_CORE_ONLY`로 명시해 100점 척도로 정규화함.
- 전체 진입준비 점수와 최종 추천은 생성하지 않음.

### 생성·수정한 주요 파일

- `app/models/scoring.py`
- `app/services/forced_filter_service.py`
- `app/services/dividend_scoring.py`
- `app/services/financial_scoring.py`
- `app/services/valuation_service.py`
- `app/services/valuation_scoring.py`
- `app/services/confidence_entry_scoring.py`
- `app/services/scoring_service.py`
- `app/services/score_component_common.py`
- `app/repositories/phase2_input_repository.py`
- `app/services/phase2_input_service.py`
- `app/repositories/scoring_repository.py`
- `app/services/phase2_service.py`
- `app/services/scoring_rules.py`
- `app/db/models/analysis.py`
- `migrations/versions/j6e9f0a1b2c3_phase_2_scoring.py`
- `scripts/update_phase2_score.py`
- `app/ui/stock_search.py`
- `tests/test_phase_2_scoring.py`
- `tests/test_migration_and_schema.py`
- `tests/test_streamlit_app.py`
- `docs/scoring_rules.md`

### 직접 실행한 핵심 명령

- `git status --short`, `git rev-parse --show-toplevel`
- `python -m pip check`
- `python -m ruff check app migrations scripts tests`
- bundled Node와 `.venv` Python을 지정한 `pyright app scripts tests`
- `python -m compileall -q app scripts migrations`
- `python -m alembic upgrade head`
- `python -m alembic current`
- `python -m alembic check`
- 빈 SQLite DB migration·Phase 2 입력 조립·저장 회귀 테스트
- `python scripts/update_phase2_score.py --help`
- `python scripts/update_phase2_score.py --symbol 005930 --as-of 2026-07-29
  --planned-order-amount 1000000`
- `python -m pytest -q --basetemp .pytest_tmp_phase2_full`
- Streamlit 포트 8765 백그라운드 기동, HTTP 200 확인, 프로세스 종료

### 테스트·실행 결과

- 전체 pytest: 97 passed, 0 failed.
- Phase 2·migration 결합 테스트: 25 passed, 0 failed.
- Ruff 전체: 통과.
- Pyright `app`, `scripts`, `tests`: 0 errors, 0 warnings.
- 전체 애플리케이션 module import: 통과.
- compileall: 통과.
- pip check: `No broken requirements found`.
- Alembic: `j6e9f0a1b2c3 (head)`, schema drift 없음.
- 필수 DB 테이블: 18개.
- 기본 DB: 활성 종목 0건.
- Phase 2 CLI: 저장 종목 부재를 `MISSING`으로 반환, 가짜 점수 미생성.
- 빈 DB·무키 AppTest와 저장된 누락 판정 UI: 예외 0, 가짜 운영 숫자 0.
- Streamlit 실제 진입점: HTTP 200.
- pytest cache 경로는 기존 Windows ACL 때문에 경고가 있었으나
  별도 `--basetemp`의 테스트 실행·결과에는 영향을 주지 않음.

### 실제 API 상태

| provider | 실제 결과 |
|---|---|
| KRX | `KRX_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| 한국투자증권 | 키 미설정, 실제 HTTP 미수행 |
| KIND | 공식 공개 API 계약 미확인으로 지원 보류 |
| NAVER | 키 미설정, adapter·실제 HTTP 미구현 |
| ECOS | 키 미설정, adapter·실제 HTTP 미구현 |
| SQLite | migration·초기화·Phase 2 저장·조회 성공 |
| PostgreSQL | 서버 미제공으로 미수행 |

### 남아 있는 위험

- 실제 KRX·OpenDART 호출과 실제 종목 데이터가 없어 모든 강제필터 통과,
  실제 배당·재무·산업 밸류에이션과 실제 RSI 기반 결과는 확인하지 못함.
- 공식 산업분류와 관리·거래정지·상장폐지 위험, 기업 이벤트 수집 writer가
  없어 실제 운영 결과는 해당 항목을 `MISSING`으로 차단함.
- KRX 거래대금 통화·단위가 실제 검증되지 않아 기존 가격으로 유동성
  필터를 통과시키지 않음.
- 공식 수정가격이 없어 개별 종목 진입 구성요소와 전체 진입준비는
  실제 운영에서 계산 보류됨.
- 산업 peer 현재 밸류에이션을 종목별로 조회하므로 대규모 유니버스에서는
  배치 집계·인덱스 최적화가 필요함.
- SQLite 시점 복원은 KST wall-clock 전제이며 실제 PostgreSQL의
  migration·timezone·NUMERIC 동작은 미검증임.

### 마지막 갱신시각

- 2026-07-29 14:30:00 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능

---

## Phase 1C 독립 검수 결과 (2026-07-29)

### 발견한 문제

#### Critical

- `FinancialRepository`가 신규 `financial_statements` 행의 NOT NULL 필드인
  `corp_code`, `report_code`, `scope` 등을 채우기 전에 `flush()`해 실제
  재무 수집이 `IntegrityError`로 중단되는 실행 불가 경로가 있었다.

#### High

- OpenDART 응답의 법인코드·사업연도·공시 검색기간·페이지 문맥이 요청과
  일치하는지 검증하지 않아 다른 요청의 정상 응답을 현재 종목 데이터로
  저장할 가능성이 있었다.
- 기준일 이후의 공시가 DB에 이미 있으면 과거 기준일 수집에도 제출일로
  연결돼 미래정보가 정규화될 수 있었다.
- 배당·감사 행의 공시 접수번호에 대응하는 제출일이 없어도 `AVAILABLE`로
  저장될 수 있었고, DB도 이를 막지 않았다.
- 정규화가 차단된 OpenDART 원응답이 `normalized_success=true`로 남아
  원자료 상태와 실제 정규화 결과가 달라질 수 있었다.
- 최신 재무 조회가 최신 별도재무제표보다 오래된 연결재무제표를 전역
  우선하여 최신 보고기간을 잃을 수 있었다.

#### Medium

- 최근 5개 확정 사업연도 후보가 현재 미완료 사업연도를 포함해 가장 오래된
  완료연도 하나를 누락할 수 있었다.
- 52주 고점 대비 낙폭이 일중 고가가 아니라 종가 최고값으로 계산됐다.
- 기술지표 입력에 서로 다른 가격 원천 또는 알 수 없는 원천이 섞여도
  계산될 수 있었다.
- OpenDART 공식 정정 표시 중 일부가 누락돼 정정공시 우선순위 판정이
  불완전했다.
- 무키 개별 종목 화면에 OpenDART 연결상태와 구체적 미설정 원인이 없었다.

#### Low

- 전체 Ruff 기본 규칙의 기존 지적과 테스트 Settings 생성의 Pyright 오탐이
  남아 있어 전체 정적 검사 결과가 깨끗하지 않았다.
- `stock_analysis_service.py`와 `financial_repository.py`에 현재 Phase
  orchestration·영속화 로직이 많이 모여 있다. 기능 책임 혼합이나 순환
  import는 확인되지 않았으나 유지보수 위험으로 기록한다.

### 수정한 내용

- `app/repositories/financial_repository.py`
  - 필수 statement 필드를 모두 설정한 뒤 flush하도록 수정했다.
  - 최신 보고기간을 먼저 선택하고 동일 기간에서만 CFS를 우선하도록
    조회 규칙을 수정했다.
- `app/providers/dart_analysis.py`, `app/models/financial.py`
  - 공시 페이지·기간·법인, 배당 법인·사업연도, 감사 법인·사업연도 문맥을
    검증하고 불일치 응답을 `INVALID_RESPONSE`로 차단했다.
  - 공식 정정 표시 전체를 반영했다.
- `app/repositories/disclosure_repository.py`
  - 접수 메타데이터 조회에 `as_of_date` 상한을 적용했다.
- `app/services/stock_analysis_service.py`
  - 공시 제출일이 없거나 기준일 이후인 재무·배당·감사 정규화를 모두
    차단하고 원응답 정규화 성공/실패 상태를 실제 결과와 동기화했다.
  - 성공 재시도 시 이전 정규화 실패 상태를 정상 복원했다.
  - 최근 5개 완료 사업연도 후보 범위를 보정했다.
- `app/repositories/raw_response_repository.py`
  - 정규화 결과 상태와 오류 코드·메시지를 명시적으로 기록하는 경로를
    추가했다.
- `app/db/models/financial.py`,
  `migrations/versions/i5d8e9f0a1b2_phase_1c_filing_date_truth.py`
  - `AVAILABLE` 배당·배당 fact·감사의견에 제출일을 강제하는 DB 제약을
    추가하고 기존 불완전 행은 `MISSING`으로 보정했다.
- `app/utils/technical_indicators.py`
  - 52주 고점을 일중 고가로 계산하고 단일·확인된 가격 원천만 허용했다.
- `app/ui/stock_search.py`
  - OpenDART 키 미설정 또는 연결 미검증 상태와 구체적 이유를 표시했다.
- `app/models/__init__.py`, `app/providers/base.py`, `app/providers/krx.py`,
  `app/services/universe_service.py`, 초기 migration, 관련 테스트
  - 전체 Ruff·Pyright 지적을 동작 변경 없이 정리했다.
- `tests/test_phase_1c_analysis.py`, `tests/test_migration_and_schema.py`,
  `tests/test_streamlit_app.py`
  - 위 결함을 먼저 재현하는 회귀 테스트를 추가했다.
- `tests/helpers.py`와 Settings를 사용하는 테스트
  - 런타임 전용 `_env_file` 전달을 helper로 격리해 검증 약화 없이
    전체 Pyright 오탐을 제거했다.

### 실행한 명령

- `git status --short`
- `git rev-parse --show-toplevel`
- `Get-Content -Encoding UTF8`로 지정 문서 5개 전체 확인
- `Get-ChildItem`, `rg`, `Select-String`으로 최근 수정 파일과 코드 패턴 확인
- `.\.venv\Scripts\python.exe --version`
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m pip show sqlalchemy alembic httpx pydantic pydantic-settings streamlit pytest ruff pyright`
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- `pkgutil` 기반 전체 `app`·`scripts` module import 스크립트
- Python AST 기반 application import cycle 검사 스크립트
- `.\.venv\Scripts\python.exe -m ruff check app scripts migrations tests`
- `.\.venv\Scripts\python.exe -m pyright app scripts migrations tests`
  - bundled Node를 자동 설치하려다 네트워크 제한으로 실패했다.
- bundled Node와 가상환경을 명시한
  `pyright ... app scripts migrations tests`
- 기존 SQLite DB에서 `alembic current`, `alembic upgrade head`,
  `alembic current`, `alembic check`
- 빈 SQLite DB에서 `alembic upgrade head`, `alembic current`,
  `alembic check` 및 테이블·행 수 검사
- 빈 DB·무키 환경 Streamlit `AppTest`
- 무키 환경
  `python -m scripts.collect_stock_analysis --symbol 000001 --as-of 2026-07-29 --years 5`
- Streamlit 서버를 8527 포트에서 시작해 HTTP 200과 종료 후 포트 해제를
  검사한 PowerShell 스크립트
- 결함별 회귀 pytest와
  `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider`
- `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp work/pytest-final-20260729`

### 테스트 결과

- 수정 전 결함별 회귀 실행에서 요청 문맥 불일치, 미래 제출일, 불완전
  filing date, statement 조기 flush, CFS 범위, 사업연도 후보, 기술지표
  원천·고점, UI 상태 결함을 각각 실패로 재현했다.
- 최종 전체 pytest: 79 passed, 0 failed.
- Ruff 전체 기본 규칙: 통과.
- Pyright 전체: 0 errors, 0 warnings.
- compileall: 통과.
- 전체 module import: 52개 성공, 실패 0.
- AST import cycle: 0건.
- Alembic: `i5d8e9f0a1b2 (head)`, 기존 DB·빈 DB 적용 성공,
  schema drift 없음.
- 빈 DB 초기화: domain row 0, 예외 0.
- 무키 AppTest: 예외 0, 금지된 가짜 값 0, OpenDART 미설정 사유 표시.
- 무키 Phase 1C CLI: `NOT_CONFIGURED`, 종료코드 2, 재무·배당·감사·공시
  정상 데이터 저장 0건.
- Streamlit 진입점: HTTP 200, 프로세스 종료 및 포트 해제 성공.
- 명시적 `--basetemp` 없는 최종 pytest 1회는 사용자 임시 디렉터리 접근
  거부로 51 passed, 28 setup errors였으며 코드 실패는 아니었다. 저장소
  내부 `--basetemp` 재실행에서 79건 모두 통과했다.
- AppTest 메뉴를 한글 literal로 선택한 첫 실행은 PowerShell stdin 인코딩으로
  실패했고 메뉴 option 객체를 사용한 재실행은 통과했다.

### 실제 API 상태

| provider | 실제 연결 결과 |
|---|---|
| KRX 종목기본정보 | `KRX_API_KEY` 미설정, 실제 HTTP 미수행 |
| KRX 일별매매정보 | `KRX_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART 공시검색 | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART 재무제표 | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART 배당 | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART 감사의견 | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| 한국투자증권 | 키 미설정·현재 adapter 없음, 실제 HTTP 미수행 |
| NAVER | 키 미설정·현재 adapter 없음, 실제 HTTP 미수행 |
| ECOS | 키 미설정·현재 adapter 없음, 실제 HTTP 미수행 |
| KIND | 공식 공개 API 계약 미확정, 호출 미수행 |
| SQLite | 기존 DB·빈 DB migration 및 초기화 성공 |
| PostgreSQL | 실제 서버 미제공, 미수행 |

### 남아 있는 위험

- 실제 OpenDART 응답 snapshot과 실제 종목의 최근 재무·5년 배당·감사의견은
  인증키 부재로 확인하지 못했다.
- 공식 수정가격 원천이 없어 실제 종목 기술지표는 의도적으로 계산·표시하지
  않는다.
- 실제 KRX 수치 단위와 식별자 매핑, 실제 PostgreSQL migration은 미검증이다.
- 계약형 fixture는 검증했지만 운영 API의 미문서화 값과 호출 제한은
  실제 읽기 호출로 다시 확인해야 한다.
- 원자료 파일과 DB transaction의 비원자성, SQLite timezone 복원 전제,
  큰 service/repository 파일의 유지보수 위험이 남아 있다.

### Phase 판정

- 조건부 진행 가능

---

## Phase 1C 재무제표·배당·감사의견·기술지표 (2026-07-29)

### 시작 상태

- 작업 시작 전 지정 문서 4개를 전체 확인함.
- 프로젝트 디렉터리에 `.git` 메타데이터가 없어 `git status`, 최근 commit,
  tracked diff는 확인할 수 없었음.
- 기존 Phase 1B의 종목·가격·원응답 repository와 재무·배당·감사 schema
  골격을 재사용했으며 같은 기능을 다시 작성하지 않음.
- D-019에 따라 기존 KRX 일별가격의 수정가격 상태는 `NOT_VERIFIED`이고,
  이 가격으로 기술지표를 계산하지 않는 조건을 유지함.

### 구현 범위

- OpenDART 공시검색:
  - 정기공시와 현금·현물배당결정 거래소 공시 검색
  - 모든 접수번호·접수일·정정 표시·원문 링크 보존
  - 재무 API 접수번호와 제출일이 매칭되지 않으면 정규화 저장 중단
- 재무제표:
  - CFS 우선, 공식 `013`일 때만 OFS fallback
  - `BS`, `IS`, `CIS`, `CF`, `SCE` 구분
  - XBRL 표준계정 exact mapping과 기업 확장계정·member context 미매핑
  - 순이익과 지배기업 소유주지분 순이익을 별도 metric code로 유지
  - 당기·당기누적·전기·전기분기·전기누적·전전기 금액 원형 분리
  - 누적 분기 단독값 변환과 TTM 계산, 입력 누락 시 NULL 유지
- 배당:
  - 최근 1~5개 사업연도 조회
  - 라벨에 `(원)`이 명시된 확정 주당 현금배당금만 DPS로 정규화
  - `(백만원)`이 명시된 현금배당총액만 원 단위로 정규화
  - 추정 DPS 생성 금지
  - 지급 사업연도·결산기준일·접수일·접수번호·출처·원문 링크 보존
- 감사:
  - 감사의견·감사인·사업연도·결산기준일·보고서 제출일·접수번호 보존
  - 특기사항·강조사항·핵심감사사항 원문 필드 보존
  - 계속기업 위험은 구조화 전용 필드가 없어 자동 추정하지 않고
    `NOT_VERIFIED`로 표시
- 기술지표:
  - Wilder RSI 14, SMA 20·60·120·200, ATR 14, 52주 고점 대비 낙폭
  - 하나의 가격 원천과 Decimal 계산 사용
  - 모든 입력행의 수정가격 확인 상태가 `VERIFIED`가 아니면 전체 계산 보류
- UI·CLI:
  - 개별 종목 화면에 요약·배당·재무·감사·차트·공시 탭 추가
  - `scripts.update_stock_analysis` 한 종목 증분수집 명령 추가
  - 무키·무데이터 상태에서 가짜 숫자 대신 구체적 오류 원인 표시

### 생성·수정한 주요 파일

- `app/models/financial.py`
- `app/providers/dart_analysis.py`
- `app/repositories/disclosure_repository.py`
- `app/repositories/financial_repository.py`
- `app/repositories/price_repository.py`
- `app/services/account_mapping.py`
- `app/services/dividend_service.py`
- `app/services/stock_analysis_service.py`
- `app/utils/financial_math.py`
- `app/utils/technical_indicators.py`
- `app/db/models/financial.py`
- `app/db/models/disclosure.py`
- `app/ui/stock_search.py`
- `app/main.py`
- `scripts/update_stock_analysis.py`
- `migrations/versions/g3b6c7d8e9f0_phase_1c_analysis.py`
- `migrations/versions/h4c7d8e9f0a1_financial_account_context.py`
- `tests/test_phase_1c_analysis.py`
- `tests/test_migration_and_schema.py`
- `README.md`
- `docs/DECISIONS.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/CHANGELOG.md`
- `docs/IMPLEMENTATION_STATUS.md`

### 실제 실행한 명령

- `git status --short`, `git rev-parse --show-toplevel`
- `Get-Content -Encoding utf8`로 필수 문서 4개 전체 확인
- 공식 OpenDART 개발가이드의 공시검색·전체 재무제표·배당·감사의견 계약 확인
- `rg --files`, `rg`, `Select-String`으로 기존 구현·금지 패턴·endpoint 검사
- 결함·계산 회귀 테스트의 수정 전 pytest
- Phase 1C 대상 pytest와 전체 pytest
- `python -m ruff check` Phase 1C 전체 규칙 및 전체 코드 `F,E9,I`
- bundled Node와 가상환경을 지정한 Pyright 운영 코드 검사
- `python -m compileall -q app scripts migrations tests`
- 기본 DB와 새 빈 SQLite DB에서 `alembic upgrade head`, `current`, `check`
- 빈 DB·무키 Streamlit AppTest
- `python -m scripts.update_stock_analysis --help`
- 무키 테스트 DB에서 `python -m scripts.update_stock_analysis
  --symbol 000001 --as-of 2026-07-29 --years 5`
- Streamlit server를 8523 포트에서 시작해 HTTP 200 확인 후 종료
- 전체 application AST parse·module import·import cycle 검사

### 테스트·실행 결과

- 수정 전 Phase 1C 테스트: 구현 모듈 부재로 collection error 1건 재현.
- Phase 1C 계산·provider·repository·무키 저장 차단 테스트: 11 passed.
- 최종 전체 pytest: 66 passed, 0 failed.
- Phase 1C 파일 Ruff 전체 규칙: 통과.
- 전체 코드 Ruff `F,E9,I`: 통과.
- Pyright 운영 코드·script·migration: 0 errors, 0 warnings.
- AST parse: 54개 Python 파일 성공.
- application·script import: 44개 성공, 내부 import cycle 0건.
- compileall, pip check: 통과.
- Alembic: `h4c7d8e9f0a1 (head)`, schema drift 없음.
- 새 빈 DB: 16개 table, domain row 0.
- 빈 DB·무키 AppTest: exception 0, 금지 가짜 UI 값 0.
- 실제 Streamlit 진입점: 8523 포트 HTTP 200, 종료 후 포트 해제.
- 무키 Phase 1C CLI: `NOT_CONFIGURED`, 종료코드 2.
- 무키 CLI DB: 원응답·재무제표·계정·배당·감사·공시 0건.

### 실제 API 상태

| provider·기능 | 상태 | 실제 호출 결과 |
|---|---|---|
| KRX 종목기본정보 | 키 미설정 | 미수행 |
| KRX 일별가격 | 키 미설정 | 미수행, 기존 행도 수정가격 미검증 |
| OpenDART 고유번호 | 키 미설정 | 미수행 |
| OpenDART 공시검색 | 키 미설정 | CLI `NOT_CONFIGURED`, HTTP 미수행 |
| OpenDART 전체 재무제표 | 키 미설정 | HTTP 미수행 |
| OpenDART 배당에 관한 사항 | 키 미설정 | HTTP 미수행 |
| OpenDART 감사의견 | 키 미설정 | HTTP 미수행 |
| SQLite | 연결됨 | migration·빈 DB·무키 저장 차단 성공 |
| PostgreSQL | 서버 미제공 | 미수행 |

### 현재 확인된 데이터 기준일

- 실제 KRX·OpenDART 시장·종목·가격·재무·배당·감사 데이터 기준일 없음.
- CLI의 `2026-07-29`는 요청 기준일이며 실제 API 데이터 기준일이 아님.
- 코드·migration·격리 실행 검증일: 2026-07-29 KST.

### 남아 있는 위험·미완료

- 실제 OpenDART 인증 호출이 없어 실제 응답 값 집합, 정정공시 관계,
  기업별 XBRL 확장계정, 배당 `se` 라벨 변형을 확인하지 못함.
- 공시검색은 원·정정 접수번호를 모두 보존하지만 공식 응답에 원접수번호
  직접 연결 필드가 없어 `original_receipt_no` 자동 연결은 보류함.
- OpenDART 전체 재무제표 응답에는 정확한 재무기간 시작·종료일이 없어
  원문 XBRL context를 추가하기 전 `period_start`, `period_end`를 추정하지 않음.
- 현금·현물배당결정은 공시 메타데이터와 원문 링크만 제공하며 원문 표 금액
  자동 파싱은 구조화 계약 확인 전 보류함.
- 계속기업 불확실성은 전용 구조화 필드가 없어 강조사항 텍스트를 보존하되
  위험 여부를 임의 판정하지 않음.
- 공식 수정가격 원천이 없어 운영 기술지표는 `NOT_VERIFIED`로 계산 보류함.
- 실제 PostgreSQL migration은 미검증임.
- 추천·점수·산업비교·시장충격·포트폴리오·뉴스·백테스트는 다음 Phase
  기능으로 구현하지 않고 상태 문서에만 남김.

### 마지막 갱신시각

- 2026-07-29 12:33:00 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 실제 데이터 완료 판정 전 OpenDART 키로 종목 한 개의 최근 재무제표,
  연결·별도 선택, 최근 5년 배당, 최신 감사의견을 확인하고, 공식 수정가격
  원천으로 기술지표를 검증해야 함.
- 조건: 실제 공식 데이터가 필요한 후속 기능을 검증 완료로 판정하기 전에 KRX·OpenDART 키로 최소 읽기 호출을 수행하고 원응답·HTTP 상태·schema·기준일을 확인해야 함.

---

## Phase 1B KRX 확정 일별가격 (2026-07-29)

### 시작 전 저장소 상태 확인

- 요청된 작업 폴더에는 Git 저장소와 프로젝트 파일이 없었고, 실제 프로젝트는
  `2026-07-28/kospi-analyzer-streamlit-project-spec-1-2`에서 확인함.
- 실제 프로젝트 디렉터리에도 `.git` 메타데이터가 없어 `git status`,
  최근 commit, tracked diff는 확인할 수 없었음.
- 작업 시작 전 마지막 수정 파일은 `docs/IMPLEMENTATION_STATUS.md`,
  `docs/KNOWN_LIMITATIONS.md`, `app/providers/dart.py`,
  `tests/test_dart_parser.py`, `app/repositories/stock_repository.py` 순이었음.
- 상태 문서와 코드에는 Phase 1A 독립 검수(45 passed)까지만 기록되어 있었고
  Phase 1B 구현 파일이나 완료 기록은 없었음.

### 구현 범위

- 기존 `price_daily` 테이블과 원응답 repository를 재작성하지 않고 재사용함.
- KRX `유가증권 일별매매정보`의 공식 계약 필드만 사용하는 provider를 추가함.
- 응답 기준일, 필수 문자열, 숫자, OHLC 관계와 비음수 수량·금액을 검증함.
- 종목 마스터의 `ISU_CD`와 일별가격의 `ISU_CD`를 정확히 일치시켜 저장함.
- 동일 종목·거래일·provider 재수집은 새 행을 만들지 않고 갱신함.
- 미매핑 가격은 저장하지 않고 `UNMATCHED_ISSUE_CODE` 품질로그를 남김.
- 기준일 단위 증분수집 CLI와 검색 화면의 최근 확정종가 표시를 추가함.
- 가격 출처, 기준일, 수집시각, 전일종가 상태를 함께 표시함.

### 데이터 진실성

- KRX 계약에는 수정주가 여부가 없으므로 `is_adjusted=NULL`,
  `adjustment_status=NOT_VERIFIED`로 저장함.
- 수정주가가 검증되지 않아 RSI·이동평균·기간수익률은 계산하지 않음.
- 요청 `basDd`와 응답 `BAS_DD`가 다르면 전체 응답을 실패로 처리함.
- 키 미설정·HTTP 오류·스키마 오류·빈 응답을 정상 가격으로 저장하지 않음.
- 휴장일 또는 빈 응답에서 다른 날짜를 임의로 선택하지 않음.

### 생성·수정 파일

- `app/models/price.py`
- `app/providers/krx_price.py`
- `app/repositories/price_repository.py`
- `app/services/price_service.py`
- `scripts/update_daily_prices.py`
- `app/ui/stock_search.py`
- `app/main.py`
- `tests/test_phase_1b_prices.py`
- `tests/test_migration_and_schema.py`
- `migrations/versions/f2a5b6c7d8e9_clear_unverified_krx_currency.py`
- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/CHANGELOG.md`
- `docs/DECISIONS.md`
- `docs/KNOWN_LIMITATIONS.md`

### 실제 실행한 명령

- Phase 1B 파일 대상 Ruff 전체 규칙 검사
- 전체 application 대상 Ruff 핵심 검사(`F`, `E9`, `I`)
- Phase 1B provider·repository·UI 대상 pytest
- 전체 `pytest -q`(권한이 있는 작업공간 `--basetemp`, cacheprovider 비활성화)
- `python -m compileall -q app scripts migrations tests`
- `python -m alembic current`
- `python -m alembic check`
- `python -m scripts.update_daily_prices --as-of 2026-07-29`
- `python -m pip check`

### 테스트 결과

- Phase 1B 대상 테스트: 9 passed, 0 failed.
- 전체 pytest: 55 passed, 0 failed.
- Phase 1B 파일 Ruff 전체 규칙: 통과.
- 전체 Ruff 핵심 검사: 통과.
- compileall: 통과.
- Alembic: `f2a5b6c7d8e9 (head)`, schema drift 없음.
- pip check: `No broken requirements found`.
- 무키 가격 CLI: `NOT_CONFIGURED`, 종료코드 2, 수신·저장·미매핑 0건.
- Pyright: bundled Node와 명시적 가상환경을 사용한 운영 코드·script·migration
  검사에서 0 errors, 0 warnings. 테스트까지 포함하면 Pydantic Settings의 런타임
  전용 `_env_file` 인자를 정적 signature가 인식하지 못하는 14건이 남음.

### 실제 API 상태

| 기관·기능 | 상태 | 실제 호출 |
|---|---|---|
| KRX 종목기본정보 | 키 미설정 | 미수행 |
| KRX 일별매매정보 | 키 미설정 | 미수행 |
| OpenDART 고유번호 | 키 미설정 | 미수행 |
| 데이터베이스 | 연결됨 | migration·upsert·조회 성공 |

### 남은 기능

- 실제 KRX 키로 최소 일별가격 호출 후 HTTP 상태·스키마·수치 단위·응답 크기 검증
- KIS 현재가와 공식 수정주가 provider
- 수정주가가 확보된 뒤 RSI·이동평균·기간수익률
- 거래일 달력 기반 과거 구간 백필
- Phase 1의 재무제표·배당·감사의견

### 마지막 갱신시각

- 2026-07-29 11:45:00 KST (Asia/Seoul)

### Phase 판정

- 코드 작성 및 격리 테스트 완료·실제 API 연결 미검증

---

## Phase 1B 독립 검수 결과 (2026-07-29)

### 발견한 문제

#### Critical

- 없음.

#### High

- 공식 계약에서 통화·수치 단위를 확인하지 않았는데 가격을 `KRW`로 저장하고
  UI에 `원`을 표시하고 있었음.
- 누락 가능한 거래량·거래대금·시가총액을 조회할 때 `0`으로 변환해 실제 0과
  데이터 누락을 구분할 수 없었음.
- 활성 종목 여러 개가 같은 KRX `ISU_CD`를 공유하면 마지막 종목 하나에 가격을
  임의 저장할 수 있었음.

#### Medium

- 이미 저장된 Phase 1B 행의 검증되지 않은 `KRW` 값을 정정하는 데이터
  migration이 없었음.
- 구현 상태와 알려진 제약 문서의 현재 Phase·정적 분석 상태가 실제 코드보다
  뒤처져 있었음.

#### Low

- 전체 Ruff 기본 규칙에는 과거 Phase 코드와 생성 migration의 현대화·스타일
  지적 13건이 남아 있음. 미사용 import나 실행 불능 오류는 아니며 이번 Phase
  동작 변경 없이 정리할 수 있는 후속 유지보수 항목임.
- 테스트 소스까지 포함한 Pyright는 Pydantic Settings의 런타임 전용
  `_env_file` 인자를 정적 signature가 인식하지 못해 14건을 보고함.

### 수정한 내용

- `app/models/price.py`: 최근가격 모델의 통화와 누락 가능 수치 필드를 nullable로
  변경함.
- `app/repositories/price_repository.py`: 검증되지 않은 `KRW` 저장과 누락값의
  0 변환을 제거하고, 중복 `issue_code`를 충돌로 기록해 저장을 차단함.
- `app/ui/stock_search.py`: 검증된 KRW일 때만 `원`을 표시하고 그 외에는
  `단위 미검증`을 표시함.
- `migrations/versions/f2a5b6c7d8e9_clear_unverified_krx_currency.py`:
  KRX 일별가격 중 수정가격·단위가 미검증인데 `KRW`로 저장된 값을 NULL로
  보정함.
- `tests/test_phase_1b_prices.py`: 단위 표시, 누락과 0 구분, 중복 식별자 충돌,
  HTTP 500 원자료·정규화 저장 차단 회귀 테스트를 추가함.
- `tests/test_migration_and_schema.py`: 기존 잘못된 통화값 보정 migration
  회귀 테스트와 새 head 확인을 추가함.
- `docs/IMPLEMENTATION_STATUS.md`, `docs/KNOWN_LIMITATIONS.md`: 실제 검수 결과와
  잔여 위험으로 갱신함.

### 실행한 명령

- `git status --short`, `git rev-parse --show-toplevel`
- `Get-Content`로 지정 문서 5개와 관련 소스·테스트·migration 확인
- `Get-ChildItem`, `rg`, `Select-String`으로 최근 수정 파일, 금지 패턴,
  endpoint, 예외 처리, 샘플 데이터, 숫자 타입 검사
- Python AST parse·전체 application module import·import cycle 검사
- `python -m pip check`
- `python -m ruff check`(Phase 1B 전체 규칙, 전체 코드 `F,E9,I`, 전체 기본 규칙)
- bundled Node와 가상환경을 지정한 Pyright 검사
- `python -m compileall -q app scripts migrations tests`
- 빈 SQLite DB에서 `python -m alembic upgrade head`, `current`, `check`
- 빈 DB·무키 환경 Streamlit `AppTest`
- 무키 환경 `python -m scripts.update_daily_prices --as-of 2026-07-29`
- Streamlit server를 8521 포트에서 시작해 HTTP 200 확인 후 종료
- 결함 재현 대상 pytest, 수정 후 Phase 1B pytest, 최종 전체 pytest

### 테스트 결과

- 수정 전 회귀 테스트: 가격 진실성 4건 실패. 원인은 `KRW` 추정, 누락값 0
  변환, 중복 식별자 임의 매핑이었음.
- 데이터 보정 migration 테스트: migration 추가 전 1건 실패로 기존 `KRW`
  잔존을 재현함. 최초 fixture 작성 오류로 `created_at` 누락 실패가 1회 있었고
  fixture를 바로잡은 뒤 실제 결함을 확인함.
- 수정 후 Phase 1B 테스트: 9 passed, 0 failed.
- 최종 전체 pytest: 55 passed, 0 failed.
- Ruff Phase 1B 전체 규칙과 전체 코드 `F,E9,I`: 통과.
- Pyright 운영 코드·script·migration: 0 errors, 0 warnings.
- 전체 module import 44개 성공, import cycle 0건, compileall 성공.
- 빈 DB migration: `f2a5b6c7d8e9 (head)`, 15개 테이블, domain row 0,
  schema drift 없음.
- 빈 DB·무키 AppTest: 예외 0, 금지된 가짜 UI 값 0.
- 실제 Streamlit 진입점: HTTP 200 응답 확인.

### 실제 API 상태

| provider | 실제 연결 결과 |
|---|---|
| KRX 종목기본정보 | `KRX_API_KEY` 미설정, 실제 HTTP 미수행 |
| KRX 일별매매정보 | `KRX_API_KEY` 미설정, CLI `NOT_CONFIGURED`, 저장 0건 |
| OpenDART 고유번호 | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| 한국투자증권 | 키 미설정, adapter·실제 HTTP 미구현 |
| NAVER | 키 미설정, adapter·실제 HTTP 미구현 |
| ECOS | 키 미설정, adapter·실제 HTTP 미구현 |
| KIND | 공식 공개 API 계약 미확인으로 지원 보류 |
| SQLite | 새 빈 DB migration·초기화·조회 성공 |
| PostgreSQL | 실제 서버 미제공으로 미수행 |

### 남아 있는 위험

- 실제 KRX 인증 호출이 없어 HTTP 성공, 실제 응답 필드 집합, 수치 단위,
  종목 식별자 충돌·미매핑 비율을 확인하지 못함.
- 공식 단위를 확인할 때까지 UI는 가격에 `단위 미검증`을 표시함.
- 계약형 synthetic fixture는 실제 응답 snapshot을 대신할 수 없음.
- PostgreSQL에서 migration과 timezone·NUMERIC 동작을 검증하지 못함.
- 원자료 파일과 DB transaction은 원자적이지 않아 DB 실패 시 고아 파일이
  남을 수 있음.
- 공식 수정주가가 없어 기술지표와 미래정보 차단 검증은 구현·실행 대상이 아님.

### Phase 판정

- 조건부 진행 가능

---

## Phase 2 독립 검수 및 수정 결과 (2026-07-29)

### 발견한 문제

#### Critical

- 없음.

#### High

- `FinancialRepository`의 재무·배당·감사 조회가 `data_state`를 제한하지
  않아 `MISSING` 행을 최신 정상 자료처럼 Phase 2 입력에 사용할 수 있었다.
- 최신 재무 보고기간에 없는 계정을 이전 보고기간에서 가져와 서로 다른
  기간의 재무값을 하나의 최신 입력처럼 혼합할 수 있었다.
- Phase 2 가격 조회가 기준시각 이후 수집된 과거 가격을 사용할 수 있었고,
  기술지표는 KIS 수정가격으로 계산하면서 진입가격은 다른 KRX 원가격을
  사용할 수 있었다.
- 미확인 시장 분류와 임의 시장상태 문자열이 각각 확정 배제 또는 안전한
  상태로 오인될 수 있었다.
- 공백을 제거한 `감사의견 거절` 문자열이 배제 집합과 일치하지 않아
  `FAIL` 대신 `MISSING`이 됐고, 기본 550일 최신성 기준이 12개월을 넘긴
  감사보고서를 통과시킬 수 있었다.

#### Medium

- 단일 TTM 이자보상비율 1배 미만을 “지속” 증거 없이 즉시 `FAIL`로
  처리했다.
- 금융업 별도 모형의 존재 여부만 참이면 실제 판정값 없이 재무위험 필터를
  통과시킬 수 있는 모델 경로가 있었다.
- 데이터 신뢰도의 산업 표본이 유효 PER/PBR 표본이 아닌 전체 peer 수를
  사용해 표본 품질을 과대 표시할 수 있었다.
- 계속기업 위험이 `VERIFIED=False`로 확인됐어도 UI에서 “확인 불가”로
  표시했다.

#### Low

- `stock_analysis_service.py`, `financial_repository.py`,
  `stock_search.py`의 책임과 행 수가 큰 상태다. 현재 import cycle이나
  provider/service 책임 혼합은 없었으나 유지보수 위험으로 남겼다.

### 수정한 내용

- `app/models/scoring.py`, `app/config.py`
  - 감사 최신성 기본값을 365일로 보정하고 기본 규칙 버전을
    `phase2-rule-v2`로 올렸다.
- `app/services/forced_filter_service.py`
  - 미확인 시장 분류를 `MISSING`으로 처리하고 공백 정규화된
    감사의견 거절을 확정 배제한다.
  - 단일 저이자보상 TTM은 지속 여부 확인 전 `REVIEW_REQUIRED`로 차단한다.
  - 금융업 모형 존재 여부만으로 통과시키지 않는다.
- `app/repositories/financial_repository.py`
  - `AVAILABLE`·`MAPPED` 재무만 사용하고 최신 보고기간 밖 계정의
    자동 fallback을 제거했다.
  - 배당과 감사 조회도 `AVAILABLE` 행만 사용한다.
- `app/repositories/phase2_input_repository.py`,
  `app/repositories/price_repository.py`
  - Phase 2 가격·밸류에이션·기술 입력에 `collected_at <= as_of_at`
    시점 게이트를 적용했다.
  - 반복 영업손실 조회에 정상 상태와 정확 매핑 조건을 적용했다.
- `app/services/phase2_input_service.py`
  - 확인된 시장상태 값 집합만 정상·위험 boolean으로 변환한다.
  - 진입가격을 기술지표와 동일한 검증된 수정가격 시계열에서 가져온다.
  - 데이터 신뢰도 산업 표본을 유효 양수 PER/PBR 표본의 보수적 최소값으로
    계산한다.
- `app/ui/stock_search.py`
  - 계속기업 위험의 검증된 부재를 “중대한 불확실성 없음”으로 표시한다.
- `tests/test_phase_2_scoring.py`, `tests/test_streamlit_app.py`
  - 위 결함을 먼저 실패로 재현하고 수정 후 회귀 테스트를 추가했다.
- `docs/scoring_rules.md`, `docs/DECISIONS.md`,
  `docs/KNOWN_LIMITATIONS.md`, `docs/IMPLEMENTATION_STATUS.md`
  - 실제 규칙·검수 결과·잔여 제약을 반영했다.

### 실행한 명령

- `git status --short`, `git rev-parse --show-toplevel`
- `Get-Content -Encoding utf8`로 지정 문서 5개 전체 확인
- `Get-ChildItem`, `rg`로 최근 수정 파일, 예외, datetime, 누락값 변환,
  하드코딩 숫자, endpoint, 인증정보 사용 패턴 검사
- `.\.venv\Scripts\python.exe --version`
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m pip show sqlalchemy alembic httpx pydantic
  pydantic-settings streamlit pytest ruff pyright`
- `.\.venv\Scripts\python.exe -m ruff check app scripts migrations tests`
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- bundled Node와 가상환경 Python을 명시한 Pyright 전체 검사
- `pkgutil` 기반 `app`·`scripts` 전체 module import
- Python AST 기반 전체 parse·내부 import cycle 검사
- 수정 전 기준선, 결함별 대상 테스트, 수정 후 대상 테스트와
  `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
  --basetemp work\pytest-phase2-audit-final-code`
- 기본 DB와 새 빈 SQLite DB에서 `alembic upgrade head`, `current`, `check`
- 빈 DB 테이블·종목 행 수 검사
- 빈 DB·API 키 미설정 Streamlit `AppTest`와 금지 문자열 검사
- 무키 상태의 provider 연결상태 조회
- `python -m scripts.update_phase2_score --help`
- 빈 DB에서 `python -m scripts.update_phase2_score --symbol 005930
  --as-of 2026-07-29 --planned-order-amount 1000000`
- `Start-Process`를 이용한 Streamlit 기동 시도
- Python subprocess로 Streamlit을 8766 포트에서 기동해 HTTP 200과
  종료 후 포트 해제를 확인한 명령

### 테스트 결과

- 수정 전 전체 기준선: 97 passed, 0 failed.
- 수정 전 Phase 2 신규 회귀: 10 failed, 17 passed.
  - 미확인 분류·상태, 감사 거절·최신성, 이자보상 지속성, 금융업 모형,
    미래 수집 가격, 가격원천 혼합, 비정상 재무 상태, 보고기간 혼합을
    각각 재현했다.
- UI 계속기업 표시 테스트는 helper 추가 전 collection error 1건,
  유효 산업 표본과 규칙 버전 테스트는 각각 추가 전 import/assert 실패
  1건으로 재현했다.
- 수정 후 최종 전체 pytest: 110 passed, 0 failed.
- Ruff 전체: 통과.
- Pyright 전체: 0 errors, 0 warnings.
- compileall: 통과.
- 전체 module import: 67개 성공.
- AST parse: application·script 69개 성공, import cycle 0건.
- Alembic: `j6e9f0a1b2c3 (head)`, schema drift 없음.
- 새 빈 DB: Alembic 포함 19개 테이블, 종목 0행, 초기화 성공.
- 빈 DB·무키 AppTest: 예외 0, 금지 가짜 값 0, 구체적인 키 미설정·
  지원 보류 이유 표시.
- Phase 2 CLI: 활성 종목 없음 `MISSING`, 종료코드 2, 가짜 점수 미생성.
- Streamlit 실제 진입점: 포트 8766 HTTP 200, 종료 후 포트 해제.
- Pyright 첫 wrapper 실행은 nodeenv 외부 다운로드가 네트워크 제한으로
  실패했고, Node 직접 실행 1회는 Python 경로가 잘못 해석돼 환경 오류를
  보고했다. 올바른 번들 Node·절대 Python 경로 재실행은 통과했다.
- `Start-Process` Streamlit 시도는 PowerShell `Path`/`PATH` 중복 오류로
  시작 전에 실패했고, Python subprocess 재실행은 성공했다.

### 실제 API 상태

| provider | 실제 연결 결과 |
|---|---|
| KRX | `KRX_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| 한국투자증권 | 앱키·시크릿 미설정, 실제 HTTP 미수행 |
| KIND | 공식 공개 API 계약·자동수집 권한 미확인, 지원 보류 |
| NAVER | API HUB 키 미설정, 실제 HTTP 미수행 |
| ECOS | 키 미설정, 실제 HTTP 미수행 |
| SQLite | 빈 DB migration·초기화·연결상태 검사 성공 |
| PostgreSQL | 서버 미제공, 미수행 |

### 남아 있는 위험

- 실제 공식 API 호출과 실제 종목 결과가 없어 실제 값 집합·단위·산업 표본·
  성능을 확인하지 못했다.
- 단일 TTM 이자보상 저하는 안전하게 `REVIEW_REQUIRED`로 차단하지만,
  연속 기간 이자보상비율을 구조화한 자동 지속성 판정은 아직 없다.
- 금융업 별도 규제지표 모형, 공식 시장상태·산업분류·기업 이벤트 writer,
  공식 수정가격 운영 입력이 없다.
- 최신 종목 마스터 하나만 유지하므로 완전한 과거 유니버스·상장폐지 종목을
  포함한 point-in-time 백테스트 저장소가 아니다.
- 실제 PostgreSQL migration·timezone·NUMERIC 동작은 미검증이다.

### 마지막 갱신시각

- 2026-07-29 15:01 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 실제 데이터 완료 판정 전 KRX·OpenDART·공식 수정가격 원천으로
  종목 한 개 이상의 강제필터·배당·재무·산업 밸류에이션·RSI를 검증하고,
  연속 기간 이자보상비율 및 금융업 별도 모형 입력이 필요한 종목은
  자동 통과시키지 않는다.

---

## Phase 3 시장충격·반도체·시장국면 구현 결과 (2026-07-29)

### 시작 상태

- 지정된 `PROJECT_SPEC.md`, `IMPLEMENTATION_STATUS.md`, `DECISIONS.md`,
  `KNOWN_LIMITATIONS.md`를 전체 확인했다.
- 실제 프로젝트 디렉터리에 `.git` 메타데이터가 없어 `git status`,
  최근 commit과 tracked diff는 확인할 수 없었다.
- 기존 Phase 2 독립 검수 결과는 110 passed, Alembic
  `j6e9f0a1b2c3`, 외부 API 키 미설정 상태였다.
- 기존 `price_daily`, `stock_classifications`, `dividends`,
  `api_raw_responses`를 재사용하고 같은 저장·수집 기능을 다시 작성하지
  않았다.

### 구현 범위

- KRX KOSPI 지수:
  - 공식 `KOSPI 시리즈 일별시세정보` endpoint와 확인된 응답 필드만 사용
  - 요청 기준일·응답 `BAS_DD` 일치, 필수값·숫자·OHLC 검증
  - 키 미설정·HTTP·schema·빈 응답을 정상 지수로 저장하지 않음
  - 원자료와 분리된 `index_daily` 증분 upsert와 기준일 CLI
- 시장충격:
  - 21·63·126·252거래일 고점, 고점일, 현재 종가 대비 낙폭
  - 기간 KOSPI 수익률, KOSPI 동일가중·중앙수익률, 상승·하락 종목 수
  - 20일선·60일선 위 종목 비율
  - 반도체 주도 하락·시장 전반 투매·혼합형·불확실 config 규칙
- 반도체·비반도체:
  - 공식 반도체 지수가 설정·저장된 경우 공식 기간수익률 우선
  - 공식 지수가 없으면 설정된 공식 산업분류 정확 코드로
    `SELF_CALCULATED_PROXY` 구성
  - 반도체 시가총액가중·동일가중, 비반도체 시가총액가중·동일가중·
    중앙수익률
  - 전일 시가총액 비중×당일 수익률의 종목별·삼성전자·SK하이닉스·
    반도체 전체 설명 기여도 추정치
  - 종목명, `SECT_TP_NM`, 삼성전자·SK하이닉스 두 종목만으로
    반도체 구성종목을 추측하지 않음
- 배당주·시장국면:
  - 기준일 이전 OpenDART 확정 DPS 종목의 동일가중 수익률과
    KOSPI·비반도체 대비 상대수익률
  - 적색·주황·황색·녹색·불확실 국면
  - 반도체 회복, KOSPI 회복, 비반도체 시장 확산,
    배당주 상대강도 회복을 별도 판정
  - 비반도체 확산과 배당주 상대강도 없이 두 대형 반도체주 상승만으로
    녹색 판정하지 않음
- 진실성·재현성:
  - 단일 provider의 검증된 수정가격만 허용
  - 가격·분류 구성종목 커버리지가 설정 기준보다 낮으면 `UNCERTAIN`
  - 숫자별 출처·기준시각·수집시각·계산방법·품질·공식/자체 프록시 저장
  - `phase3-rule-v1`, config 임계값, 결정적 입력 해시와 데이터 신뢰도
  - 동일 입력·규칙·기준시각 재실행 시 동일 snapshot 재사용

### 생성·수정한 주요 파일

- `app/models/market_analysis.py`
- `app/providers/krx_index.py`
- `app/repositories/index_repository.py`
- `app/repositories/phase3_input_repository.py`
- `app/repositories/market_analysis_repository.py`
- `app/services/index_service.py`
- `app/services/market_shock_analyzer.py`
- `app/services/semiconductor_contribution_analyzer.py`
- `app/services/dividend_contagion_analyzer.py`
- `app/services/market_regime_service.py`
- `app/services/market_metric_builder.py`
- `app/db/models/market_analysis.py`
- `app/ui/market_dashboard.py`
- `scripts/update_daily_index.py`
- `scripts/update_phase3_market.py`
- `migrations/versions/k7f0a1b2c3d4_phase_3_market_analysis.py`
- `tests/test_phase_3_market.py`
- `docs/market_regime_rules.md`
- `.env.example`, `README.md`, 상태·결정·제약 문서

### 실제 실행한 명령

- `git status --short`, `git rev-parse --show-toplevel`
- `Get-Content -Encoding utf8`로 필수 문서 4개 전체 확인
- `rg --files`, `rg`, `Get-ChildItem`으로 기존 구현·최근 파일·금지 패턴·
  파일별 행 수 검사
- `.\.venv\Scripts\python.exe --version`
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- `.\.venv\Scripts\python.exe -m ruff check app scripts migrations tests`
- bundled Node와 가상환경 Python을 지정한 Pyright 전체 검사
- AST parse, `app`·`scripts` 전체 module import, 내부 import cycle 검사
- Phase 3 대상 pytest와
  `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
  --basetemp work\pytest-phase3-final-refactored`
- 기존 DB와 새 빈 SQLite DB에서 `alembic upgrade head`, `current`, `check`
- `python -m scripts.update_daily_index --help`
- 무키 환경 `python -m scripts.update_daily_index --as-of 2026-07-29`
- `python -m scripts.update_phase3_market --help`
- 빈 DB·무키 환경
  `python -m scripts.update_phase3_market --as-of 2026-07-29`
- 빈 DB·무키와 저장된 누락 snapshot의 Streamlit AppTest
- Streamlit을 8773 포트에서 시작해 HTTP 200을 확인하고 종료한 명령
- provider 연결상태와 핵심 Phase 3 테이블 행 수를 조회한 명령

### 테스트·실행 결과

- Phase 3 대상 테스트 최초 실행: 2 failed, 22 passed.
  - 음의 기여도 비중 테스트 기대값이 비반도체 음의 기여도를 누락한 1건
  - 연결상태의 한국어 enum 표시를 영문 enum으로 기대한 1건
  - 계산·UI 코드는 바꾸지 않고 테스트 기대값을 실제 공식 의미에 맞게 수정
- 수정 후 Phase 3·migration·UI 대상 테스트: 24 passed, 0 failed.
- 전체 최종 pytest: 121 passed, 0 failed.
- Ruff 전체: 통과.
- Pyright 전체: 0 errors, 0 warnings.
- compileall: 통과.
- AST parse·전체 module import: 83개 성공.
- 내부 import cycle: 0건.
- 새 Phase 3 orchestration과 provenance builder를 343행·512행으로 분리해
  807행 단일 파일 집중을 해소함.
- Alembic: `k7f0a1b2c3d4 (head)`, 기존 DB·빈 DB 적용 성공,
  schema drift 없음.
- 새 빈 DB: Alembic 포함 23개 테이블, 종목 0행.
- 무키 지수 CLI: `NOT_CONFIGURED`, 종료코드 2, 수신·저장 0건.
- 무데이터 Phase 3 CLI: `MISSING`, 종료코드 2, 시장충격·시장국면
  `UNCERTAIN`, 누락 핵심 입력 5개를 구체적으로 출력.
- 검증용 DB: 누락 snapshot 1건, provenance metric 38건,
  기여도 0건, 실제 원응답 0건.
- 저장된 누락 snapshot 대시보드: 예외 0, 요약 metric 3개와 provenance
  표 1개, 누락 사유 표시.
- 실제 Streamlit 진입점: 포트 8773 HTTP 200.

### 실제 API 상태

| provider·기능 | 실제 결과 |
|---|---|
| KRX KOSPI 시리즈 일별시세 | `KRX_API_KEY` 미설정, CLI `NOT_CONFIGURED`, HTTP 미수행 |
| KRX 종목기본정보·일별가격 | `KRX_API_KEY` 미설정, 실제 HTTP 미수행 |
| OpenDART | `DART_API_KEY` 미설정, 실제 HTTP 미수행 |
| 한국투자증권 수정가격 | 키 미설정, provider 미구현, 실제 HTTP 미수행 |
| KIND | 공식 공개 API 계약 미확인으로 지원 보류 |
| NAVER·ECOS | 키 미설정, 실제 HTTP 미수행 |
| SQLite | 기존 DB·빈 DB migration, 저장·조회 성공 |
| PostgreSQL | 서버 미제공, 미수행 |

### 현재 확인된 데이터 기준일

- 실제 KRX 지수·종목·가격·OpenDART 배당 데이터 기준일: 없음.
- CLI의 `2026-07-29`는 요청 기준일이며 실제 API 데이터 기준일이 아니다.
- 실제 시장국면, 반도체 기여도와 시장 숫자: 없음.
- 코드·migration·격리 실행 검증일: 2026-07-29 KST.

### 남아 있는 위험·미완료

- 실제 KRX KOSPI 호출이 없어 실제 `IDX_NM`, 수치 단위, 응답 크기와
  시계열을 확인하지 못했다.
- 공식 산업분류 공개 계약·writer와 반도체 지수 구성종목 계약이 없다.
- KIS 수정가격 provider가 없어 운영 시장 폭·바스켓·기여도는 계산 보류다.
- 배당 미지급 공식 음의 관측이 없어 확정 DPS 표본은 전체 배당주 모집단의
  완전한 대체가 아니다.
- 설명 기여도는 공식 KOSPI 포인트 기여도나 인과관계가 아니다.
- 산업조정 상대수익률과 과거 베타 회귀는 검증된 시점 입력이 없어
  숫자를 만들지 않았다.
- 실제 KOSPI 전체 배치 성능과 PostgreSQL migration은 미검증이다.
- 추천·포트폴리오·뉴스·수급·백테스트는 다음 Phase 기능으로 구현하지 않았다.

### 마지막 갱신시각

- 2026-07-29 15:36 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 실제 데이터 완료 판정 전 KRX 키로 KOSPI 지수를 수집하고,
  공식 산업분류 또는 공식 반도체 지수 구성, KIS 검증 수정가격과
  OpenDART 확정 배당 표본으로 실제 기준일 한 건 이상의 시장 숫자·
  출처·수집시각·분류를 확인해야 한다.

---

## Phase 3 독립 검수 및 수정 결과 (2026-07-29)

### 발견한 문제

#### Critical

- 입력 해시가 종목별 이동평균 가격 이력, 공식 반도체 지수, 유니버스·
  분류 개수와 다수의 시장국면 임계값을 포함하지 않았다. 계산 결과가
  바뀌어도 같은 해시로 기존 스냅샷을 재사용할 수 있었다.

#### High

- 공식 반도체 지수의 계산 시작·종료 거래일을 KOSPI와 맞추지 않아
  오래된 공식 지수 수익률을 현재 반도체 수익률로 사용할 수 있었다.
- KRX 전일 시가총액이 없으면 KIS 수정가격 행의 계약상 확인되지 않은
  `market_cap`을 기여도와 바스켓에 대신 사용할 수 있었다.
- 배당주 판정이 최신 정정본보다 과거 양수 DPS 한 건의 존재를 우선해,
  최신 정정 DPS가 0이어도 배당주로 포함할 수 있었다.
- 미분류 종목을 기여도 분모와 종목별 기여도에서 제외해, 분류 커버리지가
  100%보다 낮을 때 전체 KOSPI 대비 비중을 과대 표시할 수 있었다.
- 동일 지수명 다른 provider와 `DELAYED` 지수·가격을 확정 종가 시계열에
  섞을 수 있었고, 화면에는 시세구분을 저장·표시하지 않았다.
- 공식 반도체 지수를 쓴 경우 동일가중·비반도체·종목 기여도까지 공식
  프록시로 표시했고, 공식 지수 수익률도 `KRX·KIS` 원천으로 표시했다.
- 종목별 기여도에 시가총액·산업분류 출처, 수집시각, 시세구분,
  계산방법, 품질, 공식/자체 구분이 없었다.
- 저장된 누락 스냅샷 화면에는 핵심 누락만 보이고 KRX·OpenDART·KIS
  연결상태와 구체적인 키 미설정 사유가 보이지 않았다.

#### Medium

- 동일 유효시작일에 서로 다른 공식 산업분류 코드가 활성화돼도
  최신 DB id 하나를 임의로 선택할 수 있었다.

#### Low

- `market_metric_builder.py`가 588행으로 커졌다. 현재는 지표 provenance
  조립만 담당하고 provider/service 책임 혼합이나 순환 import는 없지만
  유지보수 시 지표군별 분리를 검토할 필요가 있다.

### 수정한 내용

- `app/services/market_regime_service.py`
  - 전체 계산 입력·원천·임계값을 입력 해시에 포함했다.
  - KOSPI와 정확히 정렬된 공식 반도체 지수 구간만 허용하고 그렇지 않으면
    공식 분류 자체 프록시 또는 계산 불가로 처리했다.
- `app/repositories/phase3_input_repository.py`
  - KRX `PREVIOUS_CLOSE` 시가총액을 강제하고 수정가격 행 fallback을 제거했다.
  - 최신 정정 배당을 사업연도·주식종류·배당유형별로 선택했다.
  - 동일 유효시작일 분류 충돌을 임의 선택하지 않고 미분류로 처리했다.
  - 지수·가격·시가총액의 확정 종가 시세구분을 강제했다.
- `app/repositories/index_repository.py`
  - KRX·`PREVIOUS_CLOSE` 지수만 분석 시계열로 읽도록 제한했다.
- `app/services/semiconductor_contribution_analyzer.py`
  - 전체 비교 유니버스 시가총액을 기여도 분모로 사용하고 미분류 종목도
    nullable 분류 상태로 종목별 기여도에 보존했다.
- `app/models/market_analysis.py`,
  `app/db/models/market_analysis.py`,
  `app/repositories/market_analysis_repository.py`
  - 지표 시세구분과 종목별 기여도 provenance 필드를 추가·저장했다.
- `app/services/market_metric_builder.py`
  - 공식 반도체 지수는 공식 시총가중 수익률에만 표시하고 자체
    동일가중·비반도체·기여도는 자체 프록시로 분리했다.
  - KOSPI·배당 등 반도체 프록시 비적용 지표는 `NOT_APPLICABLE`로 표시했다.
- `app/ui/market_dashboard.py`
  - 시세구분과 종목별 기여도 provenance를 표시하고, 저장된 누락
    스냅샷에도 KRX·OpenDART·KIS 연결 사유를 표시했다.
- `app/config.py`, `docs/market_regime_rules.md`, `docs/DECISIONS.md`
  - 보정 규칙을 `phase3-rule-v2`로 올리고 계산 규칙을 문서화했다.
- `migrations/versions/l8a1b2c3d4e5_phase_3_audit_provenance.py`
  - 지표·기여도 provenance와 nullable 미분류 상태를 추가했다.
- `migrations/versions/m9b2c3d4e5f6_phase_3_legacy_timing_truth.py`
  - 구버전 Phase 3 지표·기여도의 검증되지 않은 시세구분을
    `UNKNOWN`으로 보정했다.
- `tests/test_phase_3_market.py`, `tests/test_migration_and_schema.py`,
  `tests/test_streamlit_app.py`
  - 발견 결함을 먼저 실패로 재현한 회귀 테스트를 추가했다.

### 실행한 명령

- `git status --short`, `git rev-parse --show-toplevel`
  - 프로젝트에 `.git` 메타데이터가 없어 두 명령 모두 실패했다.
- `Get-Content -Encoding utf8`로 지정 문서 5개 전체 확인
- `rg`, `Get-ChildItem` 기반 예외·datetime·누락값 변환·하드코딩·
  endpoint·인증정보·파일 행 수 검사
- 결함 재현 대상 pytest와 수정 후 Phase 3·migration·UI pytest
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m pip show sqlalchemy alembic httpx
  pydantic pydantic-settings streamlit pytest ruff pyright`
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- `.\.venv\Scripts\python.exe -m ruff check app scripts migrations tests`
- bundled Node와 가상환경 Python을 지정한 Pyright 전체 검사
- `pkgutil` 기반 `app`·`scripts` 전체 module import
- Python AST 기반 전체 parse·내부 import cycle 검사
- 기본 DB와 새 빈 SQLite DB에서 `alembic current`, `upgrade head`,
  `current`, `check`
- 빈 DB 테이블·domain 행 수와 무데이터 numeric metric 수 검사
- 빈 DB·API 키 미설정 Streamlit `AppTest`와 금지 문자열 검사
- 무키 `python -m scripts.update_daily_index --as-of 2026-07-29`
- 무데이터 `python -m scripts.update_phase3_market --as-of 2026-07-29`
- `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
  --basetemp work\pytest-phase3-audit-final`
- Streamlit을 포트 8774에서 시작해 HTTP 200을 확인하고 종료한
  Python subprocess 명령

### 테스트 결과

- 수정 전 신규 회귀: 고유 테스트 11건에서 결함을 재현했다.
  지수 provider·시세구분 혼합 테스트는 서로 다른 두 결함을 순차 재현해
  실패 실행은 총 12건이었다.
- 수정 후 Phase 3·migration·UI 대상: 35 passed, 0 failed.
- 최종 전체 pytest: 131 passed, 0 failed.
- Ruff 전체: 통과.
- Pyright 전체: 0 errors, 0 warnings.
- compileall: 통과.
- 전체 module import: 82개 성공.
- AST parse: 84개 파일, import cycle 0건.
- Alembic: 기본 DB `k7f0a1b2c3d4`에서 `m9b2c3d4e5f6 (head)`로
  두 audit migration upgrade 성공, schema drift 없음.
- 새 빈 DB: Alembic 포함 23개 테이블, domain row 0.
- 빈 DB·무키 AppTest: 예외 0, 저장된 누락 스냅샷에서도 provider별
  구체적인 키 미설정 사유 표시, 금지 가짜 값 0건.
- 무키 지수 CLI: `NOT_CONFIGURED`, 수신·저장 0, 종료코드 2.
- 무데이터 Phase 3 CLI: `MISSING`, 시장충격·시장국면 `UNCERTAIN`,
  핵심 누락 5개, numeric metric 0, 종료코드 2.
- Streamlit 진입점: 포트 8774 HTTP 200, 종료 성공.

### 실제 API 상태

| provider·기능 | 실제 연결 결과 |
|---|---|
| KRX KOSPI 시리즈 일별시세 | `KRX_API_KEY` 미설정, CLI `NOT_CONFIGURED`, HTTP 미수행 |
| KRX 종목기본정보·일별가격 | `KRX_API_KEY` 미설정, HTTP 미수행 |
| OpenDART 재무·배당·감사·공시 | `DART_API_KEY` 미설정, HTTP 미수행 |
| 한국투자증권 수정가격 | 앱키·시크릿 미설정, provider 미구현, HTTP 미수행 |
| KIND | 공식 공개 API 계약 미확인, 지원 보류 |
| NAVER·ECOS | 인증정보 미설정, HTTP 미수행 |
| SQLite | 기본 DB·빈 DB migration, 초기화, 저장·조회 성공 |
| PostgreSQL | 서버 미제공, 미수행 |

### 남아 있는 위험

- 실제 외부 API 입력이 없어 실제 KOSPI 시장 숫자·반도체 분류·배당 표본과
  `phase3-rule-v2` 결과를 검증하지 못했다.
- migration 전 기여도 행의 시가총액 원천은 사후 추정하지 않아
  `UNKNOWN`일 수 있으므로 v2 재계산이 필요하다.
- 공식 산업분류 writer, 공식 반도체 지수 구성종목 계약, KIS 수정가격
  provider가 없다.
- 산업조정 배당주 상대수익률과 과거 베타 회귀는 검증된 시점 입력이 없어
  계산하지 않는다.
- 최신 종목 마스터·일별가격 upsert 구조는 완전한 point-in-time
  백테스트 이력 저장소가 아니다.
- 실제 PostgreSQL migration과 KOSPI 전체 배치 성능은 미검증이다.

### 마지막 갱신시각

- 2026-07-29 16:20:08 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 다음 Phase의 실제 데이터 완료 판정 전에 KRX 지수, 공식
  산업분류 또는 공식 반도체 지수, KIS 검증 수정가격, OpenDART 최신
  정정 배당으로 실제 기준일 한 건 이상의 원응답·수치·출처·수집시각·
  시세구분·계산 결과를 확인해야 한다.

---

## Phase 4 추천·분할매수·포트폴리오 구현 결과 (2026-07-29)

### 시작 상태

- 작업 전 `PROJECT_SPEC.md`, `IMPLEMENTATION_STATUS.md`, `DECISIONS.md`,
  `KNOWN_LIMITATIONS.md`를 전부 확인했다.
- 이 디렉터리에는 `.git` 메타데이터가 없어 `git status`와
  `git rev-parse`는 실행했지만 저장소 상태를 조회할 수 없었다.
- Phase 2 강제필터·점수와 Phase 3 시장충격·시장국면은 이미 구현·검수된
  상태였으므로 이를 다시 만들지 않고 기존 서비스와 저장 스냅샷을
  조합했다.

### 구현 범위

- 활성 KOSPI 유니버스를 기준일 고정 상태로 순회하고 Phase 2를 다시
  계산한 뒤 같은 기준일의 Phase 3 시장 스냅샷과 결합한다.
- 강제필터 `FAIL`은 `EXCLUDED`, 누락·검토필요·신뢰도 미달은
  `INSUFFICIENT_DATA`로 분리하여 점수로 상쇄하지 않는다.
- 회복 준비 완료, 우량하지만 관망, 과도할인 후보, 일반 검토, 투자배제,
  데이터 부족의 6개 추천 그룹과 긍정·위험·제외·누락 근거를 저장한다.
- Phase 5 수급 15점은 0점으로 대체하지 않고 확인 가능한 85점만
  `PHASE4_NO_FLOW_ENTRY_85`로 정규화한다.
- 과도할인 후보는 비반도체 동일가중 수익률 대비 상대하락만 설명
  추정치로 사용하며, 숨은 악재 검토 대상으로 두고 즉시 배분하지 않는다.
- 종목·산업·확인된 기업집단 최대비중과 시장국면별 배당주·성장주·현금
  목표를 적용한다.
- 분할매수는 15/25/35/25 비중, 회차별 실행 조건, 전체 취소 조건을
  제공하되 검증된 수정종가만 참고가격으로 저장한다. 목표가격은 만들지
  않으며 모든 계획은 읽기 전용이다.
- 사용자가 설정과 보유종목을 입력할 수 있고, 투자배제 종목의 즉시
  재검토와 계산 가능한 종목한도 초과 보유의 부분 비중축소 검토를
  표시한다.
- 같은 데이터 스냅샷·config·score/rule version은 결정적 hash로 기존
  추천 실행을 재사용한다.
- 추천하기 버튼, 진행률, 주요 제외 종목과 정확한 사유, 종목별 계산
  근거·분할매수 상세, 포트폴리오 설정·보유 판단 화면을 추가했다.
- 자동주문, 주문 API, 계좌이체와 Phase 5 기능은 구현하지 않았다.

### 생성·수정한 주요 파일

- `app/services/recommendation_rules.py`
- `app/services/recommendation_service.py`
- `app/services/portfolio_service.py`
- `app/repositories/recommendation_repository.py`
- `app/models/recommendation.py`
- `app/db/models/analysis.py`
- `app/db/models/portfolio.py`
- `app/ui/recommendations.py`
- `app/ui/portfolio.py`
- `app/main.py`
- `app/config.py`
- `scripts/update_phase4_recommendations.py`
- `migrations/versions/n0c3d4e5f6a7_phase_4_recommendations.py`
- `tests/test_phase_4_recommendations.py`
- `tests/test_migration_and_schema.py`
- `tests/test_streamlit_app.py`
- `docs/recommendation_rules.md`

### 실제 실행한 명령

- `git status --short`
- `git rev-parse --show-toplevel`
- `.\.venv\Scripts\python.exe -m pip check`
- `.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests`
- `.\.venv\Scripts\python.exe -m ruff check app scripts migrations tests`
- bundled Node 실행파일로 `python -m pyright app scripts migrations tests`
- `pkgutil` 기반 `app`·`scripts` 전체 module import
- Phase 4·migration·Streamlit 대상 pytest
- `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
- 기존 SQLite DB와 별도 빈 SQLite DB에서 `alembic upgrade head`,
  `alembic current`, `alembic check`
- 빈 DB에서 `python -m scripts.update_phase4_recommendations
  --as-of 2026-07-29`
- `python -m scripts.update_phase4_recommendations --help`
- 빈 DB Streamlit `AppTest` 추천 버튼 실행
- Streamlit 서버를 포트 8784에서 실행하고 HTTP 200 확인 후 종료

### 테스트·실행 결과

- 전체 pytest: 139 passed, 0 failed.
- Ruff: 통과.
- Pyright: 0 errors, 0 warnings.
- compileall: 통과.
- 전체 import: `app`·`scripts` 91개 module 성공.
- `pip check`: broken requirement 없음.
- Alembic: 기존 DB와 빈 DB 모두 `n0c3d4e5f6a7 (head)`, schema drift 없음.
- 빈 DB CLI: `MISSING`, run 1건, 추천 0건, 활성 KOSPI·Phase 3 snapshot
  누락 사유 표시, 종료코드 2.
- 빈 DB 확인: 종목 0건, 추천 실행 1건, 추천 0건으로 가짜 결과 없음.
- Streamlit: 포트 8784에서 HTTP 200 확인, 종료 후 포트 닫힘.

### 실제 API 상태

| provider·기능 | 실제 연결 결과 |
|---|---|
| KRX 종목·가격·KOSPI 지수 | `KRX_API_KEY` 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| OpenDART 재무·배당·감사·공시 | `DART_API_KEY` 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| 한국투자증권 수정가격 | 앱키·시크릿 미설정, provider 미구현, HTTP 미수행 |
| KIND | 공식 공개 API 계약 미확인, 지원 보류 |
| NAVER | 인증정보 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| 한국은행 ECOS | 인증정보 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| SQLite | migration·빈 DB 초기화·추천 누락 실행·저장/조회 성공 |
| PostgreSQL | 서버 미제공, 미수행 |

### 현재 확인된 데이터 기준일

- 실제 외부 API 데이터 기준일: 없음.
- CLI 요청 기준일 `2026-07-29`는 실제 수집 데이터 기준일이 아니다.
- 실제 추천 종목·가격·점수·시장국면·목표비중: 없음.
- 코드·migration·격리 실행 검증일: 2026-07-29 KST.

### 남아 있는 위험·미완료

- 실제 KOSPI 전체 유니버스와 공식 외부 입력을 이용한 추천 결과·제외
  사유 분포·처리시간은 검증하지 못했다.
- 공식 산업분류 writer, 기업집단 writer, KIS 검증 수정가격 provider가
  없어 실제 산업·기업집단 한도와 가격 기반 보유비중을 검증하지 못했다.
- 과도할인 점수는 비반도체 동일가중 대비 상대하락이며 인과관계,
  산업조정, 과거 베타 또는 기업 고유 악재 검토를 대체하지 않는다.
- 최신 종목 마스터 구조는 완전한 과거 시점 유니버스 저장소가 아니다.
- 실제 PostgreSQL migration과 KOSPI 전체 배치·동시 실행 성능은
  검증하지 못했다.
- 공시·뉴스·애널리스트·수급·백테스트는 다음 Phase 범위로 남겼고
  이번 작업에서는 구현하지 않았다.

### 마지막 갱신시각

- 2026-07-29 17:17 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 실제 완료 판정 전에 KRX·OpenDART·KIS와 공식 산업분류를 연결해
  최소 한 기준일의 실제 KOSPI 유니버스에서 추천 그룹, 제외 사유,
  수정가격, 점수 범위, 시장국면, 출처·수집시각과 한도 적용 결과를
  확인해야 한다.

---

## Phase 4 독립 검수 및 수정 결과 (2026-07-29)

### 발견한 문제

- Critical
  - 종목 추천의 재현성 unique key에 `config_hash`가 없어 동일 종목·
    기준시각·입력이라도 포트폴리오 config가 다르면 두 번째 추천 저장이
    실패했다.
- High
  - 반복소수 종목 한도를 반올림하면서 저장 목표비중이 설정 한도를
    미세하게 초과할 수 있었다.
  - 목표 종목 수가 작으면 비중이 0보다 큰 성장 또는 배당 전략군 전체가
    우선순위 정렬에서 탈락할 수 있었다.
  - 보유종목 통화와 기준가격 통화가 달라도 곱해 현재 비중을 계산했다.
  - 비반도체 동일가중 수익률이 없을 때 KOSPI 지수 수익률을 과도할인
    비교 기준으로 대체해 서로 다른 모집단을 혼용했다.
- Medium
  - 모든 종목이 `INSUFFICIENT_DATA`여도 시장 데이터만 있으면 실행을
    `AVAILABLE`로 저장할 수 있었다.
  - 기준가격 통화·수집시각·시세구분이 추천 입력 hash와 분할매수
    provenance에 포함되지 않았다.
  - 의미가 같은 포트폴리오 mapping도 dict 삽입 순서가 다르면 다른
    profile hash가 됐고, 과거 설정을 다시 저장해도 최신 선택으로
    복원되지 않았다.
  - Streamlit의 원화 자금·평균매입가 입력이 binary float를 사용했다.
- Low
  - `recommendation_service.py`, `recommendation_repository.py`,
    Phase 4 migration은 책임은 분리돼 있으나 파일 크기가 커 후속
    유지보수 시 기능군별 분리를 검토할 필요가 있다.

### 수정한 내용

- `app/db/models/analysis.py`
  - 추천 재현성 unique key에 `config_hash`를 포함했다.
- `migrations/versions/o1d4e5f6a7b8_phase_4_audit_fixes.py`
  - 추천 unique key를 보정하고, 포트폴리오 최근 선택시각과 기준가격
    수집시각·시세구분 컬럼을 추가했다.
- `app/services/portfolio_service.py`
  - 종목·1차 비중을 한도 안쪽으로 내림 처리하고, 활성 배당·성장
    전략군이 목표 종목 수 범위에서 각각 최소 한 종목을 확보하게 했다.
- `app/services/recommendation_service.py`
  - 통화가 확인되고 일치할 때만 보유비중을 계산한다.
  - 과도할인 비교 기준은 비반도체 동일가중 수익률만 허용한다.
  - 전 종목 데이터 부족 실행을 `MISSING`으로 저장한다.
  - 기준가격 전체 provenance를 canonical 입력 snapshot에 포함했다.
- `app/repositories/recommendation_repository.py`
  - profile hash를 key 정렬 JSON으로 만들고 재선택 시각을 갱신한다.
  - 분할매수 기준가격 provenance를 저장·복원한다.
- `app/models/recommendation.py`, `app/db/models/portfolio.py`,
  `app/services/recommendation_rules.py`
  - 기준가격 수집시각·시세구분 모델, DB, 원시 지표 계약을 일치시켰다.
- `app/ui/recommendations.py`, `app/ui/portfolio.py`
  - 기준가격 수집시각·시세구분을 표시하고 원화 입력을 정수형으로 바꿨다.
- `app/config.py`, `.env.example`
  - 보정된 규칙을 `phase4-rule-v2`로 올렸다.
- `tests/test_phase_4_recommendations.py`,
  `tests/test_migration_and_schema.py`, `tests/test_streamlit_app.py`
  - 위 결함을 먼저 재현하는 회귀 테스트를 추가했다.

### 실행 검증

- 결함 재현 1차: 5 failed.
- 1차 수정 후 Phase 4·migration 대상: 20 passed.
- 결함 재현 2차: 6 failed.
- 2차 수정 직후: 6 passed.
- Phase 4·migration·Streamlit 대상: 34 passed.
- 전체 pytest: 148 passed, 0 failed.
- Ruff: 전체 통과.
- Pyright: 0 errors, 0 warnings.
- compileall: 통과.
- `app`·`scripts` 전체 91개 module import 성공.
- `pip check`: broken requirement 없음.
- 기본 DB와 새 빈 DB 모두 Alembic `o1d4e5f6a7b8 (head)`,
  `alembic check` drift 없음.
- 빈 DB·무키 Streamlit AppTest: 초기화와 추천·포트폴리오 메뉴 예외 0,
  예시 종목·가짜 숫자 없음.
- 빈 DB Phase 4 CLI: `MISSING`, 추천 0건,
  `ACTIVE_KOSPI_UNIVERSE` 포함 구체적 누락 사유, 종료코드 2.
- Streamlit 실제 진입점: headless 포트 8799에서 Uvicorn 서버 시작 확인.
  장기 실행 명령은 검증 도구의 120초 제한으로 종료했다.

### 실제 API 상태

- KRX: `KRX_API_KEY` 미설정, 실제 HTTP 미수행.
- OpenDART: `DART_API_KEY` 미설정, 실제 HTTP 미수행.
- 한국투자증권: 앱키·시크릿 미설정, 실제 HTTP 미수행.
- KIND: 공개 API 계약 미확인으로 지원 보류.
- NAVER API HUB: 인증정보 미설정, 실제 HTTP 미수행.
- ECOS: 인증정보 미설정, 실제 HTTP 미수행.
- SQLite: 실제 연결, 기본 DB·빈 DB migration·schema 검증 성공.
- 기본 DB 실제 건수: 활성 KOSPI 0, 검증 수정가격 0, 원응답 0,
  Phase 4 실행 0, 추천 0.

### 남아 있는 위험

- 실제 API·실제 KOSPI 입력이 없어 추천 그룹, 가격, 점수, 시장국면,
  목표비중과 전체 배치 성능은 검증하지 못했다.
- 공식 산업분류·기업집단 writer와 KIS 검증 수정가격 provider가 없다.
- `risk_profile`, 목표 배당수익률, 현재 현금, 우선주·리츠 선택값은
  재현성 config로 저장되지만 현재 추천 규칙을 별도로 변화시키지 않는다.
  UI는 공식 분류 모형이 없으면 우선주·리츠를 자동 추천하지 않는다고
  명시한다.
- 최신 종목 마스터는 완전한 point-in-time 유니버스가 아니다.
- PostgreSQL migration과 실제 KOSPI 전체 배치·동시 실행은 미검증이다.
- 큰 Phase 4 service/repository 파일은 기능 오류는 없으나 유지보수
  분리 위험이 남아 있다.

### 마지막 갱신시각

- 2026-07-29 23:08 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 실제 완료 판정 전에 KRX·OpenDART·KIS와 공식 산업분류를
  연결하여 실제 KOSPI 종목 한 건 이상에서 추천·제외 근거, 수정가격
  provenance, 점수 범위, 시장국면과 한도 적용을 확인해야 한다.

---

## Phase 5 공시·뉴스·애널리스트·수급 구현 결과 (2026-07-30)

### 시작 상태

- 작업 전에 `PROJECT_SPEC.md`, `IMPLEMENTATION_STATUS.md`, `DECISIONS.md`,
  `KNOWN_LIMITATIONS.md`를 전부 확인했다.
- 기존 OpenDART 공시검색·원응답 저장·종목 repository와 Phase 0~4
  데이터 진실성 구조를 재사용했고 정상 구현을 다시 만들지 않았다.
- 프로젝트 디렉터리에 `.git` 메타데이터가 없어 `git status --short`는
  저장소 상태를 반환하지 못했다.

### 구현 범위

- OpenDART 공시검색을 최근 저장 접수일과 config lookback 중 늦은 날부터
  증분 호출하고, 구조화된 중요 이벤트 규칙에 해당하는 공시만
  `IMPORTANT_EVENT`로 정규화한다.
- 원·정정공시를 접수번호별로 보존하며, 정정 제목과 선후관계가 일치하는
  원본 후보가 정확히 하나일 때만 연결한다. 모호·미발견 상태를 별도로
  저장한다.
- NAVER API HUB 뉴스 검색의 공식 `title`, `description`, `originallink`,
  `link`, `pubDate`만 사용한다. HTML 표시를 정규화하고 기사 본문을
  수집·분석한 것으로 표현하지 않는다.
- canonical URL, 내용 hash, 2일 내 유사제목으로 중복을 제거하고
  종목명이 제목 또는 제공 요약에 없는 검색 결과는 정규화에서 제외한다.
- 미래 기준일은 거부하고, NAVER 검색 결과 중 요청 기준일 이후 기사는
  원응답에만 보존한 뒤 정규화·분류에서 제외한다.
- 중요 기업 이벤트 규칙은 부정 규칙을 우선해 긍정·중립·부정·미분류,
  신뢰도, 일치 규칙, 판단근거, 사용 텍스트, 텍스트 범위, rule version,
  비확정적 주가 반영 설명을 보존한다.
- 한국투자증권 공식 예제로 계약을 확인한 종목투자의견·목표주가,
  외국인·기관·개인 순매수 수량, KOSPI 프로그램매매 전체 위탁 순매수
  수량, 종목 공매도만 수집한다.
- KIS OAuth 토큰은 메모리에만 두며 raw 저장 요청 파라미터와 로그에는
  앱키·시크릿·토큰을 포함하지 않는다.
- KIS 값은 Decimal로 파싱하고 빈 문자열·`-`는 `NULL`, 실제 `0`은
  0으로 보존한다. 공식 응답에 없는 통화·수량 단위는 `NULL`로 둔다.
- 증권사 투자의견과 실제 기관 매매를 별도 모델·테이블·UI로 표시한다.
- KIND, EPS, 대차·신용은 숫자를 추정하지 않고 정확한 미지원·미검증
  사유를 provider 상태 화면에 표시한다.
- Phase 5 구현 당시에는 UI와 한 종목 CLI까지만 추가했고 Phase 6 기능은
  미구현이었다. 현재 상태는 문서 최상단 Phase 6 결과를 따른다.

### 생성·수정한 주요 파일

- `app/models/events.py`
- `app/db/models/event.py`
- `app/db/models/disclosure.py`
- `app/providers/naver_news.py`
- `app/providers/kis_reference.py`
- `app/services/event_rules.py`
- `app/services/event_service.py`
- `app/repositories/event_repository.py`
- `app/repositories/disclosure_repository.py`
- `app/ui/events.py`
- `app/main.py`
- `app/config.py`
- `scripts/update_phase5_events.py`
- `migrations/versions/p2e5f6a7b8c9_phase_5_events.py`
- `tests/test_phase_5_events.py`
- `tests/test_migration_and_schema.py`
- `tests/test_streamlit_app.py`
- `docs/api_contract.md`

### 실행 검증

- `pip check`: broken requirement 없음.
- `compileall`: `app`, `scripts`, `migrations`, `tests` 통과.
- Ruff 전체 통과.
- bundled Node로 가상환경 Python을 지정한 Pyright:
  0 errors, 0 warnings.
- `pkgutil` 기반 `app`·`scripts` 전체 import:
  100개 module 성공, 실패 0.
- 전체 pytest: 160 passed, 0 failed.
- 기본 DB와 별도 빈 SQLite DB 모두 `alembic upgrade head`,
  `alembic current`, 빈 DB `alembic check` 통과.
- 두 DB 모두 migration head `p2e5f6a7b8c9`; 빈 DB schema drift 없음.
- 빈 DB에 검증용 종목 메타데이터 한 건만 넣고 Phase 5 CLI를 무키로
  실행한 결과 `NOT_CONFIGURED`, 종료코드 2, 원응답·이벤트·뉴스·
  애널리스트·수급·프로그램·공매도 모두 0건이었다.
- 무키 검증 DB의 Streamlit 실제 진입점을 포트 8805에서 실행해
  HTTP 200을 확인한 뒤 해당 프로세스를 종료했다.

### 실제 API 상태

| provider·기능 | 실제 연결 결과 |
|---|---|
| OpenDART 중요공시 | `DART_API_KEY` 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| NAVER API HUB 뉴스 | NCP 키 2종 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| KIS 투자의견·수급·프로그램·공매도 | 앱키·시크릿 미설정, `NOT_CONFIGURED`, HTTP 미수행 |
| KIND | 공식 공개 API 계약·자동수집 권한 미확인, `UNSUPPORTED` |
| KIS EPS·대차·신용 | 안전한 정규화 필드 계약 미확정, 숫자 미생성 |
| SQLite | 기본 DB·빈 DB migration, schema, 무키 CLI·UI 성공 |
| PostgreSQL | 서버 미제공, 미수행 |

### 현재 확인된 데이터

- 기본 DB 활성 KOSPI 0건, Phase 5 원응답 0건, 중요공시 0건, 뉴스 0건,
  이벤트 0건, 애널리스트 의견 0건, 수급 0건, 프로그램매매 0건,
  공매도 0건이다.
- 외부 API 실제 데이터 기준일과 실제 이벤트·기사·수급 수치는 없다.
- CLI의 요청 기준일 `2026-07-29`는 실제 수집 성공 기준일이 아니다.

### 남아 있는 위험·미완료

- 실제 API 키와 실제 KOSPI 종목으로 응답 schema, 호출 제한, 단위,
  원문 링크, 정정 연결, 중복제거 결과를 검증하지 못했다.
- DART 정정공시 검색 응답에는 원본 접수번호가 없어 제목·선후관계가
  정확히 하나로 결정되는 경우만 연결한다. 모호한 후보를 임의 선택하지
  않는다.
- KIS 프로그램매매는 공식 의미가 확인된 KOSPI
  `whol_entm_ntby_qty`만 저장하며 공식 응답 단위 메타가 없어 단위를
  추정하지 않는다.
- 이벤트 분류는 설명 가능한 키워드 규칙이며 기사 사실 검증, 인과관계,
  주가 선반영 여부 또는 투자점수를 의미하지 않는다.
- KIND 자동수집과 KIS EPS·대차·신용 정규화는 미구현이다.
- Phase 5 데이터를 Phase 4 점수에 결합하는 작업은 현재 Phase 범위에
  포함하지 않았으며 수급 15점 전체 점수는 여전히 계산하지 않는다.
- 실제 PostgreSQL migration과 대량 증분수집·동시 실행은 미검증이다.

### 마지막 갱신시각

- 2026-07-30 00:03 KST (Asia/Seoul)

### Phase 판정

- 조건부 진행 가능
- 조건: 실제 완료 판정 전에 OpenDART·NAVER API HUB·KIS 인증정보를
  연결해 실제 KOSPI 종목 한 건 이상에서 원응답, 정정공시 연결 상태,
  뉴스 중복제거, 투자의견과 실제 수급 분리, 프로그램·공매도 값,
  출처·기준일·수집시각·단위를 확인해야 한다.
