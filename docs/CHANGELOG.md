# 변경 이력

## 2026-07-30 Phase 7

- 실제 credential 형태와 설정 secret 값을 가리는 공통 log·CLI 예외
  마스킹 강화
- 마지막 성공 원응답의 config 기반 최신성 경고와 `데이터 지연` UI 추가
- 같은 transaction의 동일 원응답 중복 저장·unique 충돌 방지
- 데이터 사전, 투자 논리, 20개 완료 기준 점검표와 실제 fixture 미확보
  상태 문서 추가
- README에 초보자 설치, 초기수집, 증분갱신, 백업·복구, 문제 해결과
  배포 전 검증 절차 추가
- Ruff·Pyright를 dev dependency에 포함하고 Phase 7 보안·운영 회귀
  테스트 추가
- 전체 pytest 210건, Ruff, Pyright, compileall, 109개 module import,
  SQLite migration·backup/restore, 무키 CLI·AppTest와 Streamlit HTTP 200
  검증
- 외부 API 키·실제 원응답·실제 fixture·공식 수정가격·산업분류가 없어
  전체 판정은 조건부 배포 준비

## 2026-07-29 Phase 4

- 기존 Phase 2 강제필터·점수와 Phase 3 시장국면을 결합하는 전체 KOSPI
  추천 서비스 추가
- 6개 추천 그룹, 정확한 제외·위험·긍정·누락 근거와 데이터 신뢰도 저장
- 동일 snapshot·config·version의 결정적 hash와 추천 실행 재사용 추가
- 종목·산업·기업집단 한도와 시장국면별 배당·성장·현금 목표 추가
- 검증된 수정종가만 참고하는 읽기 전용 분할매수 계획과 취소 조건 추가
- 사용자 포트폴리오 설정·보유 판단, 추천 버튼·진행률·제외 종목 UI 추가
- Phase 4 migration `n0c3d4e5f6a7`과 전체 유니버스 CLI 추가
- 전체 pytest 139건, Ruff, Pyright, migration, 무키 CLI·빈 DB UI,
  Streamlit HTTP 200 검증
- 실제 외부 API 입력이 없어 실제 KOSPI 추천 결과는 조건부 미검증

## 2026-07-29 Phase 3 독립 검수

- 불완전한 입력 해시를 전체 계산 입력·임계값·원천 메타데이터 해시로 보정
- 공식 반도체 지수의 KOSPI 계산 구간 시작·종료일 정렬 검증 추가
- KRX 확정 종가 시가총액만 허용하고 수정가격 행 시가총액 fallback 제거
- 최신 정정 배당과 충돌 산업분류를 보수적으로 처리
- 기여도 분모를 전체 비교 유니버스로 보정하고 미분류 종목 보존
- 지수 원천·시세구분 혼합 차단과 지표·종목 기여도 provenance 확장
- 저장된 누락 스냅샷 화면에도 KRX·OpenDART·KIS 연결 사유 표시
- `phase3-rule-v2`, migration `l8a1b2c3d4e5`·`m9b2c3d4e5f6`,
  결함 회귀 테스트 추가
- 전체 pytest 131건, Ruff, Pyright, migration, 무키 CLI·AppTest,
  Streamlit HTTP 200 검증

## 2026-07-29 Phase 3

- KRX KOSPI 시리즈 일별지수 provider·원자료·정규화·CLI 추가
- 21·63·126·252거래일 고점·낙폭과 시장 폭 계산 추가
- 반도체·비반도체 바스켓, 종목별 설명 기여도, 배당주 동반하락 분석 추가
- 적색·주황·황색·녹색 시장국면과 네 회복조건 독립 판정 추가
- 숫자별 provenance, config 규칙 버전·입력 해시·데이터 신뢰도 저장 추가
- 시장국면 대시보드와 Phase 3 migration `k7f0a1b2c3d4` 추가
- 실제 공식 입력이 없으면 `UNCERTAIN`과 구체적 누락 원인만 표시

## 2026-07-29 — Phase 2 강제필터·품질·밸류에이션·점수

### 추가

- 6개 강제필터와 금융업 별도 처리 골격
- 배당·비금융업 재무 품질, 산업·자체 역사 PER/PBR 비교
- 데이터 신뢰도와 수정가격 기반 개별 종목 진입 구성요소
- 구성요소 원시값·정규화값·가중치·기여점·설명 저장
- 점수·규칙 버전, 입력 해시와 Phase 2 저장 테이블 3개
- `update_phase2_score` CLI와 개별 종목 강제필터·점수 UI
- `docs/scoring_rules.md` 계산 규칙 문서

### 데이터 진실성

- 강제필터 실패·누락 시 점수 계산 차단
- 누락 핵심값과 구버전 누락 신뢰도의 0점 변환 차단
- 음수 PER/PBR 저평가 기여 차단
- 기준일 이후 수집된 종목·시장상태·산업분류·역사값 차단
- 원가격 0은 보존하되 진입가격으로 사용하지 않음
- 재무·가격 원자료 자체가 없을 때 매핑률·수정가격 확인을 0점으로
  변환하지 않고 `MISSING`으로 유지
- 주문규모를 명세대로 최근 20일 중앙 거래대금과 비교

### 검증

- 전체 pytest 97 passed
- Ruff 전체와 Pyright 전체 0 errors
- Alembic `j6e9f0a1b2c3 (head)`, schema drift 없음
- 빈 DB·무키·저장된 누락 판정 UI와 Streamlit HTTP 200 확인

### 보류

- 외부 API 키 부재로 실제 종목 Phase 2 결과 미검증
- 공식 시장상태·산업분류·기업 이벤트 writer
- 금융업 별도 규제지표 모형
- 전체 투자매력·진입준비와 최종 추천

## 2026-07-29 — Phase 1C 개별 종목 핵심 분석

### 추가

- OpenDART 공시검색·전체 재무제표·배당·감사의견 provider
- 연결재무제표 우선, 공식 데이터 없음일 때만 별도 fallback
- 원·정정 접수번호와 제출일을 보존하는 재무·배당·감사 repository
- XBRL 표준계정 exact mapping과 미매핑 상태
- 누적 분기 단독값 변환과 TTM 계산 함수
- 최근 5개 사업연도 확정 DPS와 현금·현물배당결정 공시 조회
- 감사의견·감사인·강조사항·계속기업 확인 상태
- 수정가격 검증을 강제하는 Wilder RSI 14, SMA 20·60·120·200,
  ATR 14, 52주 고점 대비 낙폭 계산
- 개별 종목 분석 세부 탭과 `update_stock_analysis` CLI
- Phase 1C schema migration과 계산·provider·repository 테스트

### 보류

- API 키가 없어 실제 OpenDART 응답과 실제 종목 결과는 미검증
- 공식 수정가격 원천이 없어 운영 기술지표 계산은 보류
- 현금·현물배당결정 원문 금액 파싱과 계속기업 위험 자동 판정은
  구조화 계약 부족으로 보류
- 추천·점수·시장국면·포트폴리오·백테스트는 다음 Phase 범위

이 문서는 KOSPI Dividend & Semiconductor Rotation Analyzer 프로젝트의 변경 사항을 기록한다.

## 2026-07-29 — Phase 1B KRX 확정 일별가격

### 추가

- KRX `유가증권 일별매매정보` 응답 모델과 읽기 전용 provider
- 기준일 일치, 공식 숫자 파싱, OHLC 관계, 음수 수량·금액 검증
- 종목 마스터의 KRX 종목 식별자와 정확히 매핑하는 가격 repository
- 동일 종목·거래일·provider 기준 결정적 upsert와 미매핑 품질로그
- 원응답·응답 해시·요청 해시를 보존하는 가격 수집 service
- `scripts.update_daily_prices` 기준일 단위 증분수집 CLI
- 개별 종목 검색 화면의 최근 KRX 확정종가·기준일·수집시각·출처 표시
- Phase 1B provider·repository·UI 회귀 테스트

### 데이터 진실성

- KRX 계약에서 수정주가 여부를 확인할 수 없으므로 `is_adjusted=NULL`,
  `adjustment_status=NOT_VERIFIED`로 저장한다.
- 수정주가가 검증되지 않은 KRX 종가로 RSI나 수정주가 수익률을 계산하지 않는다.
- API 키 미설정, HTTP 오류, 스키마 오류, 기준일 불일치, 빈 응답을 정상 가격으로 저장하지 않는다.
- 휴장일 또는 빈 응답에서 다른 거래일을 임의 선택하지 않는다.

### 검증

- Phase 1B 대상 테스트 5개와 전체 회귀 테스트 통과
- Ruff 핵심 검사, compileall, Alembic current/check, pip check 통과
- 무키 가격 CLI가 `NOT_CONFIGURED`, 종료코드 2, 저장 0건으로 종료됨

### 미검증

- `KRX_API_KEY` 미설정으로 실제 일별가격 HTTP 응답·수치 단위·응답 크기는 미검증
- 실시간 가격과 KIS 수정주가 연동은 미구현

## 2026-07-29 — Phase 1A 코스피 종목 유니버스

### 추가

- KRX 유가증권 종목기본정보 provider
- OpenDART 고유번호 ZIP/XML provider
- 공식 상품·주식종류 분류와 `REVIEW_REQUIRED`
- 종목·분류 repository, 원자료 저장, 품질 로그
- 종목코드·기업 고유번호 정확 일치 매핑
- 종목 마스터 증분갱신 CLI
- 종목명·6자리 코드 검색 UI
- Phase 1A migration과 테스트

### 검증

- pytest 37건 통과
- Alembic `d0e3f4a5b6c7 (head)`, schema drift 없음
- 무키 CLI `NOT_CONFIGURED`, 종목 0건
- 실제 Streamlit 무데이터 검색 화면에서 가짜 종목·가격 미표시

### 미검증

- KRX·OpenDART 실제 인증 호출과 실제 종목 데이터 기준일

## 2026-07-29 — Phase 0B 독립 검수

### 수정

- 빈 `.env` 값이 안전한 설정 기본값을 덮어쓰지 않도록 수정
- `AVAILABLE` API 응답은 HTTP 2xx여야 한다는 Pydantic 검증 추가
- 동일 불변조건을 `api_raw_responses` CHECK constraint와 Alembic revision에 반영
- 결함 재현 테스트를 먼저 추가한 뒤 전체 22개 테스트 통과
- 실제 Streamlit 서버 시작을 10초 이내 검증하고 종료

### 미구현

- 외부 API provider와 실제 데이터 수집
- 분석·추천·점수·백테스트

## 2026-07-29 — Phase 0B 프로젝트 기반 구조 구축

### 추가

- Python 3.12 `pyproject.toml`, `.env.example`, `.gitignore`, README
- 설정·민감정보 마스킹 로깅·`Asia/Seoul` 시간 유틸리티
- SQLAlchemy 2 DB 연결과 SQLite 기본값·PostgreSQL URL 지원
- Alembic 환경과 초기 revision `7f491f98f46e`
- 필수 DB 테이블 14개와 데이터 진실성 메타데이터
- 공통 provider 추상 인터페이스와 검증된 API 응답 envelope
- Streamlit 기본 메뉴, API·DB 연결상태 화면, 미래 Phase 보류 화면
- 설정·시간·provider·schema·migration·연결상태·import·Streamlit 테스트 16건

### 수정

- 첫 migration 생성에서 발견한 SQLite 상위 디렉터리 미생성 문제 수정
- SQLite PRAGMA가 연 transaction 때문에 `alembic_version` 행이 롤백되던 문제를 회귀 테스트로 재현하고 수정
- 이미 생성된 빈 기본 DB를 revision `7f491f98f46e`로 정상 stamp
- Phase 0A의 실행 자산 부재 제약을 Phase 0B 실제 결과로 갱신

### 검증

- Python 3.12.13 가상환경 의존성 설치 및 `pip check` 통과
- 전체 애플리케이션 모듈 import와 bytecode compile 통과
- 기본 SQLite `upgrade head`와 필수 14개 table 생성 확인
- `alembic current`의 head revision과 `alembic check`의 schema drift 없음 확인
- 모든 필수 table이 빈 상태임을 확인
- pytest `16 passed`
- Streamlit AppTest로 무키 상태, DB 연결, 미래 Phase 보류, 가짜 운영 숫자 부재 확인
- 사용자 지시에 따라 장시간 Streamlit 서버 대기는 종료하고 AppTest·import 결과로 앱 초기화를 판정

### 구현하지 않음

- 외부 API 호출과 실제 데이터 수집
- 종목 검색과 분석
- 추천·점수·포트폴리오·반도체 분석·백테스트

## 2026-07-28 — Phase 0A 독립 검수

### 수정

- KRX `SECT_TP_NM`을 산업분류로 해석한 내용을 공식 설명인 `소속부`로 정정
- 공식 산업분류를 별도 `현재 확인 불가` 항목으로 분리하고 반도체 프록시 계산 보류 조건 명시
- 개별 계약이 미확인인 OpenDART 기업행사와 ECOS 시리즈를 `현재 확인 불가`로 재분류
- KRX 일별매매정보의 갱신주기에서 공식 문서로 확인되지 않은 장 마감 확정값 표현 제거
- 실행 자산과 프로젝트 의존성이 없는 현재 저장소 상태를 알려진 제약으로 추가

### 검증

- 문서 의미 오류 재현 검사: 수정 전 4건 실패, 수정 후 0건 실패
- API 계약 16개 행의 19열 구조와 데이터 소스 61개 행의 허용 분류 검사 통과
- 명세 원문 불변, 비밀값 형태 부재, 실행 자산 부재 확인
- 앱·DB·CLI·pytest·Streamlit 실행 검사는 대상 코드와 의존성 부재로 실행 단계에서 실패

### 구현하지 않음

- provider, service, repository, 데이터베이스와 migration
- Streamlit 화면과 CLI
- 추천·점수·반도체 프록시·백테스트

## 2026-07-28 — Phase 0A 공식 API 계약 검증

### 추가

- `docs/api_contract.md`: KRX, OpenDART, 한국투자증권, KIND, NAVER, 한국은행 ECOS의 공식 계약과 연결 상태
- `docs/data_source_matrix.md`: 프로젝트 요구 데이터 61개 항목의 제공 가능성 분류
- `docs/unsupported_or_difficult_data.md`: 공개 API 미지원, 별도 권한, 원문 파싱, 단위, 라이선스 제약

### 변경

- `docs/IMPLEMENTATION_STATUS.md`: Phase 0A 실행 명령, 테스트, API 상태, 데이터 기준일과 다음 작업 갱신
- `docs/DECISIONS.md`: 계약 채택 기준, 단위 추정 금지, KIND 보류, NAVER API HUB 우선, 호출 증거, Phase 범위 결정 추가
- `docs/KNOWN_LIMITATIONS.md`: 공식 계약 조사 결과와 실제 미검증 범위로 갱신

### 검증

- API 계약 필수 19개 열과 16개 데이터 행 검사
- 데이터 소스 61개 행의 분류값 검사
- 공식 출처 URL 호스트와 비밀값 형태의 할당문 검사
- 모든 인증정보가 미설정임을 값 출력 없이 확인

### 구현하지 않음

- 외부 API 호출과 원자료 저장
- provider, service, repository, 데이터베이스
- Streamlit 화면
- 추천·점수·포트폴리오·반도체 분석·백테스트

## 2026-07-28 — 프로젝트 초기 등록

### 추가

- `docs/PROJECT_SPEC.md`: 사용자가 제공한 프로젝트 명세 원문 등록
- `docs/IMPLEMENTATION_STATUS.md`: Phase, 기능 상태, 명령, 테스트, API 연결 및 데이터 상태 기록
- `docs/DECISIONS.md`: 초기 범위와 데이터 검증 원칙에 관한 결정 기록
- `docs/KNOWN_LIMITATIONS.md`: 구현·API·데이터·테스트 제약 기록
- `docs/CHANGELOG.md`: 변경 이력 문서 생성

### 구현하지 않음

- 애플리케이션 코드
- API provider 및 외부 API 호출
- 데이터베이스
- 추천·점수·포트폴리오·백테스트
- 샘플 종목 또는 가상 데이터
