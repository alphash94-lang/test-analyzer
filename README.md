# KOSPI Dividend & Semiconductor Rotation Analyzer

한국어 표시명은 **코스피 배당주 저평가·시장회복 분석기**다.

현재 구현 범위는 Phase 7 통합 검증과 배포 준비다. 기존 종목·가격·OpenDART 재무·배당·감사와
Phase 2 강제필터·점수에 KRX KOSPI 일별지수, 시장 폭, 공식 산업분류 기반
반도체·비반도체 바스켓, 기여도 설명 추정치, 배당주 동반하락과 시장국면을
결합해 읽기 전용 추천·분할매수 검토안·포트폴리오 목표비중을 저장하고,
OpenDART 중요공시·네이버 API HUB 뉴스·검증된 KIS 참고 데이터를 서로
구분해 표시하고, 검증된 시점정보 입력에 한해서 워크포워드 백테스트를
계산·저장한다.
실제 인증키가 없거나 공식 산업분류·검증된 수정가격이 확인되지 않으면
숫자를 만들지 않고 데이터 부족과 정확한 제외 사유를 표시한다.
Phase 7은 새 투자 기능을 추가하지 않고 보안, 최신성 경고, 실행 검증,
운영 문서와 최종 완료 기준을 정리한다. 외부 API 실제 성공과 실제 투자
결과가 없는 현재 상태를 운영 완료로 주장하지 않는다.

## 요구 환경

- Python 3.12
- Windows PowerShell 기준 명령
- SQLite 기본 사용
- PostgreSQL은 `DATABASE_URL`을 변경해 사용

## 초보자 빠른 시작

1. Python 3.12를 설치하고 이 디렉터리에서 PowerShell을 연다.
2. 아래 **설치** 명령으로 가상환경과 의존성을 준비한다.
3. `example`을 `.env`로 복사한다. API 키가 없으면 값은 비워 둔다.
4. `python -m alembic upgrade head`로 DB를 만든다.
5. `python -m streamlit run app/main.py`로 앱을 시작한다.
6. 먼저 **데이터 연결상태** 화면에서 DB, 키 설정, 마지막 성공 수집시각과
   최신성 경고를 확인한다.

API 키가 없는 첫 실행은 정상적으로 동작하지만 실제 종목 숫자를 보여 주지
않는다. 예시 종목이나 가짜 점수를 채우는 오프라인 데모 모드는 없다.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

시스템에 Python 3.12가 PATH로 등록되지 않았다면 설치된 Python 3.12 실행 파일의 전체 경로를 사용한다.

## 환경변수

```powershell
Copy-Item .env.example .env
```

`.env`에 발급받은 값만 입력한다. 인증정보가 없으면 빈 값으로 유지한다. `.env`와 API 키, 토큰, 계좌번호는 커밋하거나 로그에 출력하지 않는다.

기본 DB는 `sqlite:///./data/kospi_analyzer.db`다. PostgreSQL 예시는 다음 형식이다.

```text
postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
```

실제 접속정보는 문서나 저장소에 기록하지 않는다.

## DB migration

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

현재 revision 확인:

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

## 앱 실행

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/main.py
```

브라우저에서 표시된 로컬 주소를 연 뒤 **데이터 연결상태** 메뉴를 확인한다.

- 인증정보 없음: `키 미설정`
- 인증정보는 있으나 실제 호출 전: `연결 미검증`
- KIND: 공개 API 계약 확인 전 `지원 보류`
- 데이터베이스 `SELECT 1` 성공: `연결됨`

API 키가 없는 상태에서는 종목, 가격, 배당수익률, RSI, 점수, 추천, 시장국면, 백테스트 숫자를 표시하지 않는다.

## Phase 1A 종목 마스터 갱신

먼저 KRX Open API에서 인증키를 발급받고 **유가증권 종목기본정보** API 이용신청을 완료한다. OpenDART 인증키도 별도로 발급받는다.

- KRX: `https://openapi.krx.co.kr`
- OpenDART: `https://opendart.fss.or.kr`

`.env`에 `KRX_API_KEY`, `DART_API_KEY`를 설정한 뒤 migration과 수집 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.update_stock_master --as-of YYYY-MM-DD
```

`--as-of`를 생략하면 실행일의 `Asia/Seoul` 날짜를 사용한다. KRX 기준일에 자료가 제공되지 않으면 다른 날짜를 임의 선택하지 않고 실패 또는 빈 데이터 상태로 기록한다.

종료코드:

- `0`: KRX와 OpenDART 모두 수집·검증 성공
- `1`: 호출·응답·DB 처리 실패 또는 부분 완료
- `2`: 필수 인증키 미설정

원응답은 `data/raw/<provider>/YYYY/MM/DD/` 아래에 응답 해시 기반 파일명으로 저장하며, 인증키는 파일명·요청 해시·로그에 포함하지 않는다.

수집 후 앱의 **개별 종목 검색** 메뉴에서 종목명 또는 6자리 코드를 검색한다. 관리종목·거래정지 공식 계약이 아직 확인되지 않았으므로, 보통주라도 최종 유니버스 상태는 `REVIEW_REQUIRED`로 유지될 수 있다.

## Phase 1B KRX 일별가격 갱신

종목 마스터를 먼저 수집한 뒤 거래일별로 실행한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_daily_prices --as-of YYYY-MM-DD
```

명시한 날짜의 KRX `유가증권 일별매매정보`만 요청한다. 휴장일이나 빈 응답에서 다른 날짜를 임의 선택하지 않는다. 원응답과 요청 해시를 보존하고, 종목 마스터의 KRX 종목 식별자와 정확히 일치하는 행만 `price_daily`에 저장한다.

KRX 계약에는 수정주가 여부가 없으므로 저장 행의 수정상태는 `NOT_VERIFIED`다. 따라서 이 데이터만으로 RSI나 수정주가 수익률을 계산하지 않는다.

## Phase 1C 개별 종목 분석 갱신

종목 마스터와 OpenDART 고유번호 매핑을 먼저 완료한 뒤 한 종목씩 실행한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_stock_analysis `
  --symbol 6자리종목코드 `
  --as-of YYYY-MM-DD `
  --years 5
```

이 명령은 OpenDART 공시검색, 단일회사 전체 재무제표, 배당에 관한 사항,
회계감사인의 명칭 및 감사의견을 읽기 전용으로 호출한다. 연결재무제표가
`013 조회된 데이터 없음`일 때만 별도재무제표를 요청한다. API 오류는
별도재무제표 fallback의 근거로 사용하지 않는다.

원·정정 공시는 접수번호별로 보존하며 재무 응답 접수번호의 제출일을
공시검색에서 확인하지 못하면 정규화 저장하지 않는다. XBRL 핵심 계정 매핑에
실패한 금액은 0으로 바꾸지 않는다. OpenDART `배당에 관한 사항`에서 단위가
라벨에 명시된 확정 DPS만 정규화하며 추정 DPS는 생성하지 않는다.

종료코드:

- `0`: 하나 이상의 Phase 1C 데이터 수집·검증 성공
- `1`: 호출·응답·DB 처리 실패
- `2`: `DART_API_KEY` 미설정
- `3`: 종목 또는 OpenDART 매핑·공식 데이터 없음

기술지표 계산 함수는 `is_adjusted=True`와
`adjustment_status=VERIFIED`인 단일 가격 원천만 허용한다. 현재 KRX
일별가격은 이 조건을 충족하지 않으므로 화면에 구체적인 계산 보류 사유가
표시된다.

## Phase 2 강제필터·점수 계산

종목 마스터, Phase 1B 가격과 Phase 1C 공시 데이터를 먼저 수집한 뒤
저장된 한 종목을 계산한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_phase2_score `
  --symbol 6자리종목코드 `
  --as-of YYYY-MM-DD `
  --planned-order-amount KRW금액
```

강제필터가 하나라도 실패하거나 핵심 데이터가 없으면 투자매력 점수를
생성하지 않는다. `--planned-order-amount`를 생략하면
`PHASE2_PLANNED_ORDER_AMOUNT_KRW`를 사용하며, 둘 다 없으면 유동성 필터가
`MISSING`이다.

이번 Phase의 투자매력은 배당·재무·밸류에이션 70점 구성만
`PHASE2_CORE_ONLY`로 명시해 100점 척도로 정규화한다. 전체 진입준비와
최종 추천은 생성하지 않는다. 상세 규칙은 `docs/scoring_rules.md`를 참조한다.

종료코드:

- `0`: Phase 2 입력 게이트 통과
- `1`: 실행·DB·검증 오류
- `2`: 종목 또는 핵심 입력 누락
- `3`: 강제필터 실패 또는 데이터 신뢰도 기준 미달

## Phase 3 시장충격·시장국면

KRX 종목 마스터와 일별가격을 수집한 뒤 거래일마다 KOSPI 시리즈
일별지수를 수집한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_daily_index --as-of YYYY-MM-DD
```

KRX endpoint는 한 기준일의 KOSPI 계열 지수를 모두 저장한다. 분석에서
사용할 실제 `IDX_NM`이 기본값 `코스피`와 다르면
`PHASE3_KOSPI_INDEX_NAME`에 실제 원문 값을 설정한다.

Phase 3 종목 수익률과 이동평균은 `is_adjusted=True`,
`adjustment_status=VERIFIED`인 단일 가격 원천만 사용한다. 기본 가격
원천은 `KIS`다. 공식 산업분류 계약으로 수집한 분류 코드 중 반도체에
해당하는 정확한 코드만 쉼표로 설정한다.

```text
PHASE3_SEMICONDUCTOR_CLASSIFICATION_SYSTEM=KRX_INDUSTRY
PHASE3_SEMICONDUCTOR_CLASSIFICATION_CODES=공식코드1,공식코드2
```

공식 산업분류 writer와 실제 코드가 확보되기 전에는 값을 임의로 입력하지
않는다. `SECT_TP_NM`이나 종목명으로 반도체를 추정하지 않으며 분석 결과는
`불확실`이다.

입력이 준비되면 저장된 데이터만으로 시장 분석을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_phase3_market --as-of YYYY-MM-DD
```

종료코드:

- `0`: Phase 3 핵심 입력 충족 및 계산 성공
- `1`: 실행·DB·검증 오류
- `2`: 지수 이력, 수정가격 커버리지, 공식 분류 또는 확정 배당 표본 부족

임계값은 `.env`의 `PHASE3_*` 설정으로 관리하며 규칙 버전과 입력 해시를
스냅샷에 저장한다. 공식 반도체 지수명이 검증되면
`PHASE3_OFFICIAL_SEMICONDUCTOR_INDEX_NAME`을 설정할 수 있다. 공식 지수가
없고 공식 산업분류 구성종목으로 계산한 경우 화면에
`자체 반도체 프록시 지수`라고 표시한다. 종목별 기여도는 공식 지수 포인트나
인과관계가 아니라 전일 시가총액 비중×당일 수정가격 수익률의 설명 추정치다.

## Phase 4 추천·분할매수·포트폴리오

앱의 **포트폴리오** 메뉴에서 총 투자 가능자금, 종목·산업·기업집단
최대비중과 시장국면별 배당주·성장주·현금 목표를 저장한다. 설정과 추천은
버전형 레코드로 보존되며 과거 추천에 사용된 config를 덮어쓰지 않는다.

**추천종목** 메뉴의 **추천하기** 버튼 또는 다음 CLI는 저장된 실제 KOSPI
유니버스 전체를 동일 기준시각으로 계산한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_phase4_recommendations `
  --as-of YYYY-MM-DD
```

처리 순서는 Phase 2 강제필터·핵심점수, Phase 3 시장국면, 데이터 신뢰도,
종목·산업 한도, 분할매수 조건 순이다. 강제필터 실패는 점수로 상쇄하지
않고, 신뢰도 기준 미달과 핵심 입력 누락은 `데이터 부족`으로 분리한다.
Phase 3 종목수익률과 비반도체 동일가중 수익률을 같은 기간으로 비교할 수
없으면 `과도할인 후보`를 만들지 않는다. 이 차이는 인과관계가 아니라
추가 공시 검토가 필요한 상대적 과도하락 후보 지표다.

현재 진입준비는 Phase 5 수급 15점을 0으로 넣지 않고, 확인 가능한
시장국면 25·반도체 20·비반도체 폭 20·개별 종목 20의 85점 범위만
`PHASE4_NO_FLOW_ENTRY_85`로 정규화한다. 투자매력도 기존
`PHASE2_CORE_ONLY` 범위를 그대로 명시한다.

분할매수 계획은 검증된 수정종가가 있을 때 그 값을 기준가격으로만 보존한다.
검증된 지지구간이 없으면 회차별 목표가격을 만들지 않으며, 실행·취소 조건을
함께 표시한다. DB 제약으로 모든 계획의 `is_order_executable`은 `false`다.
자동주문, 주문 API, 계좌이체는 구현하지 않았다.

종료코드:

- `0`: 실제 유니버스와 Phase 3 핵심 입력으로 추천 실행 완료
- `1`: 실행·DB·검증 오류
- `2`: 실제 유니버스 또는 Phase 3 핵심 입력 부족

규칙과 재현성 필드는 `docs/recommendation_rules.md`를 참조한다.

## Phase 5 공시·뉴스·애널리스트·수급

종목 마스터와 OpenDART 고유번호를 먼저 준비하고, 필요한 provider 키를
`.env`에 설정한 뒤 한 종목씩 증분 수집한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_phase5_events `
  --symbol 6자리종목코드 `
  --as-of YYYY-MM-DD
```

수집기는 OpenDART 공시검색, NAVER API HUB 뉴스 검색, 한국투자증권의
종목투자의견·투자자매매동향·KOSPI 프로그램매매·공매도 기능만 사용한다.
원응답과 정규화 레코드를 분리하고, 정정공시는 제목 기준 원본 후보가 정확히
하나일 때만 연결한다. 후보가 여러 개거나 없으면 각각 `AMBIGUOUS`,
`ORIGINAL_NOT_FOUND`로 보존한다.

뉴스 분류는 기사 본문이 아니라 API가 제공한 제목과 요약만 사용하며
사용 텍스트 범위와 규칙 버전을 저장한다. 목표주가·수급·공매도·프로그램
수치는 공식 응답 필드만 Decimal로 저장하고, 응답에 없는 통화·단위는
추정하지 않는다. EPS, 대차·신용, KIND 자동수집은 계약이 충분히 검증되지
않아 제공 가능 상태만 표시하고 숫자를 만들지 않는다.

종료코드:

- `0`: 하나 이상의 Phase 5 공식 데이터 수집·검증 성공
- `1`: 호출·응답·DB 처리 실패
- `2`: 필요한 provider 인증정보 미설정
- `3`: 종목 또는 공식 데이터 없음

## Phase 6 시점정보 기반 백테스트

Phase 6는 현재 종목 마스터를 과거 전체 기간에 소급하지 않는다. 시점별
유니버스와 상장폐지 포함 여부, 제출일 기준 재무·정정공시 이력, 검증된
수정가격, 확정 현금배당, 벤치마크와 같은 버전의 추천 스냅샷을 포함하는
`BacktestDataset` JSON만 계산한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.run_phase6_backtest `
  --start YYYY-MM-DD `
  --end YYYY-MM-DD `
  --input 검증된-시점정보.json
```

`--input`을 생략하면 운영 DB의 최신 종목 목록으로 대체하지 않고
`MISSING` 결과만 저장한다. 결과는 다음 거래일 수정시가로 진입하고
1·3·6·12개월 수정종가 또는 공식 상장폐지 정산값으로 청산하며, 보유기간
중 지급된 확정 현금배당과 매수·매도 거래비용을 반영한다. 기간별·시장국면별·
산업별 성과, 회전율과 KOSPI 벤치마크를 저장한다.

종료코드:

- `0`: 모든 시점정보 게이트를 통과한 백테스트 계산·저장 성공
- `1`: 입력 계약·DB·실행 오류
- `2`: 시점정보 또는 핵심 이력 부족으로 숫자 없이 `MISSING` 저장

## 초기수집

초기수집은 공식 API 이용신청과 키 설정 후 실행한다. 한 번에 모든 기능을
무조건 성공으로 간주하는 통합 수집기는 없다. 각 단계의 종료코드와
**데이터 연결상태** 화면을 확인하면서 다음 순서로 실행한다.

```powershell
$AsOf = "YYYY-MM-DD"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.update_stock_master --as-of $AsOf
.\.venv\Scripts\python.exe -m scripts.update_daily_prices --as-of $AsOf
.\.venv\Scripts\python.exe -m scripts.update_daily_index --as-of $AsOf
```

저장된 실제 종목별로 공시·점수·이벤트를 수집한다.

```powershell
$Symbol = "6자리종목코드"
.\.venv\Scripts\python.exe -m scripts.update_stock_analysis `
  --symbol $Symbol --as-of $AsOf --years 5
.\.venv\Scripts\python.exe -m scripts.update_phase2_score `
  --symbol $Symbol --as-of $AsOf
.\.venv\Scripts\python.exe -m scripts.update_phase5_events `
  --symbol $Symbol --as-of $AsOf
```

공식 산업분류와 검증 수정가격을 포함한 시장 입력이 준비된 뒤에만 시장국면과
추천을 계산한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.update_phase3_market --as-of $AsOf
.\.venv\Scripts\python.exe -m scripts.update_phase4_recommendations --as-of $AsOf
```

현재 공식 산업분류 writer와 KIS 검증 수정가격 writer는 없으므로 관련 입력이
없으면 Phase 2~4는 `MISSING` 또는 `UNCERTAIN`으로 끝난다. 이를 성공 데이터로
대체하지 않는다. 백테스트는 별도로 검증된 시점정보 JSON이 있을 때만 Phase 6
명령을 실행한다.

## 증분갱신

거래일마다 새 기준일로 종목 마스터, 일별가격과 KOSPI 지수를 갱신한다.
같은 요청·응답 hash는 원자료 중복 행을 만들지 않고, 가격·지수는 고유키로
upsert된다.

```powershell
$AsOf = "YYYY-MM-DD"
.\.venv\Scripts\python.exe -m scripts.update_stock_master --as-of $AsOf
.\.venv\Scripts\python.exe -m scripts.update_daily_prices --as-of $AsOf
.\.venv\Scripts\python.exe -m scripts.update_daily_index --as-of $AsOf
```

공시·뉴스·수급은 필요한 종목에 대해 같은 Phase 1C·5 명령을 다시 실행한다.
OpenDART 중요공시는 마지막 저장 접수일과 설정된 lookback을 기준으로
증분수집한다. 그 뒤 Phase 2, Phase 3, Phase 4를 같은 `$AsOf`로 재계산한다.
휴장일의 빈 응답을 직전 거래일 자료로 임의 대체하지 않는다.

## 백업과 복구

SQLite는 쓰기 작업과 Streamlit을 중지한 상태에서 DB와 원자료를 함께
백업한다.

```powershell
New-Item -ItemType Directory -Force backup | Out-Null
Copy-Item data\kospi_analyzer.db backup\kospi_analyzer.db
Copy-Item data\raw backup\raw -Recurse
```

복구 전 현재 파일을 별도 보관하고, 백업 DB를 새 경로에 복사해 먼저
검증한다.

```powershell
Copy-Item backup\kospi_analyzer.db data\restored.db
$env:DATABASE_URL = "sqlite:///./data/restored.db"
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
```

`alembic current`와 앱 초기화가 성공한 뒤에만 운영 `DATABASE_URL`을 복구
DB로 바꾼다. 원자료 `data/raw`도 같은 시점 백업을 사용해야 응답 hash와
DB 메타데이터가 일치한다.

PostgreSQL은 운영 서버의 `pg_dump --format=custom`과 `pg_restore`를 사용한다.
접속 문자열과 비밀번호는 명령 기록, 문서, 로그에 직접 넣지 말고 운영 비밀
관리 수단으로 전달한다. 실제 PostgreSQL 복구는 현재 검증되지 않았다.

## 문제 해결

- `키 미설정`: `.env`의 해당 변수와 API 이용신청 상태를 확인한다.
- `연결 미검증`: 키는 감지됐지만 성공 원응답이 없다. 해당 provider의
  읽기 전용 수집 명령을 최소 한 번 실행한다.
- `데이터 지연`: 마지막 성공 원응답이
  `DATA_FRESHNESS_WARNING_HOURS`를 초과했다. 원인과 API 상태를 확인한 뒤
  증분갱신한다.
- `연결 실패`: 화면에 표시된 HTTP·데이터 상태와 수집시각을 확인한다.
  실패 응답은 정상 데이터로 저장되지 않는다.
- migration 필요: `python -m alembic upgrade head` 후
  `python -m alembic current`와 `python -m alembic check`를 실행한다.
- Windows pytest 임시폴더 권한 오류: 저장소 내부 경로를 사용해
  `--basetemp work\pytest-run -p no:cacheprovider`로 실행한다.
- 수정가격·산업분류 누락: KRX 원가격이나 `SECT_TP_NM`으로 추정하지 않는다.
  관련 계산은 데이터 부족 상태가 정상이다.
- 실제 응답 fixture: 인증키가 없어 아직 확보하지 못했다.
  `tests/fixtures/REAL_RESPONSE_STATUS.md`의 절차를 따른다.

알려진 제약은 `docs/KNOWN_LIMITATIONS.md`, API 계약은
`docs/api_contract.md`, 데이터 필드는 `docs/data_dictionary.md`에서
확인한다.

## 배포 전 검증

아래 명령은 프로젝트 루트에서 직접 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app scripts migrations tests
.\.venv\Scripts\python.exe -m ruff check app scripts migrations tests
.\.venv\Scripts\python.exe -m pyright app scripts migrations tests
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  --basetemp work\pytest-release
```

그 다음 API 키를 모두 제거한 실행, 일부 키만 설정한 실행, 실패·timeout
응답, 빈 DB, 실제 Streamlit HTTP 진입점을 각각 확인한다. 인증키가 있는
환경에서는 provider별 최소 읽기 호출의 HTTP 상태, 응답 hash, 기준일과
수집시각을 보존하되 키·토큰은 출력하지 않는다.

프로젝트 명세의 20개 완료 기준과 현재 판정은
`docs/FINAL_COMPLETION_CHECKLIST.md`에 있다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 데이터 원칙

- 누락과 0을 구분한다.
- API 실패를 정상 데이터로 저장하지 않는다.
- 원자료와 정규화 데이터를 분리한다.
- 금액은 부동소수점이 아닌 DB `NUMERIC`으로 저장한다.
- 모든 시각은 `Asia/Seoul`을 명시한다.
- 연결·별도 재무제표, 누적·단독 기간, 원·정정공시를 구분한다.
- 자동주문과 계좌 쓰기 기능은 구현하지 않는다.
