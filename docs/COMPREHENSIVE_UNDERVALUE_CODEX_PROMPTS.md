# 종합 저평가 분석 기능: 단계별 Codex 실행 프롬프트

## 1. 문서 목적

이 문서는 기존 KOSPI 추천 프로그램의 구조와 데이터 진실성 원칙을 보존하면서
`종합 저평가 분석`을 단계적으로 추가하기 위한 실행 지침이다. 각 단계의
`구현 프롬프트`와 `검수 프롬프트`는 Codex에 그대로 복사해 사용할 수 있다.

전체 단계는 반드시 다음 순서로 진행한다.

1. 현황 분석
2. 설계 문서
3. 데이터 모델
4. 종합 점수 엔진
5. 상대가치 평가
6. 성장성·품질
7. 시장국면
8. 뉴스·공시 이벤트
9. 최종 판정
10. UI
11. 테스트·검수

## 2. 현재 저장소 기준선

현재 저장소에는 다음 계층이 이미 존재한다.

- 종목·가격·재무·배당: `app/db/models`, `app/repositories`
- 엄격 Phase 2 필터와 점수: `phase2_input_service.py`,
  `scoring_service.py`, `forced_filter_service.py`
- KOSPI 전 종목 PER·PBR 스크리닝: `market_screening_service.py`
- Phase 3 시장국면: `market_regime_service.py`
- 뉴스·공시·수급 이벤트: `event_service.py`
- Phase 4 추천·목표비중: `recommendation_service.py`,
  `recommendation_rules.py`, `portfolio_service.py`
- 추천 UI: `app/ui/recommendations.py`
- 통합 갱신: `scripts/update_all.py`

현재 `RecommendationService.run_universe()`는 엄격 Phase 2 결과를 만든 다음
이를 `KOSPI_MARKET_SCREEN_V1` 결과로 치환한다. 이 방식은 전 종목 순위 계산에는
유용하지만 다음 의미가 섞일 수 있다.

- 강제필터를 통과한 엄격 분석
- 결측값을 보수적으로 처리한 전체시장 스크리닝
- 최종 투자 판정

종합 분석을 구현할 때는 세 결과를 별도 스냅샷과 별도 타입으로 보존하고,
최종 판정 단계에서 명시적으로 결합해야 한다.

## 3. 모든 단계에 적용할 공통 규칙

아래 규칙은 각 단계의 프롬프트에도 포함되어 있지만, 작업 시작 전에 항상
Codex에 함께 전달하는 것이 좋다.

```text
이 저장소에서 작업할 때 다음 원칙을 항상 지켜라.

1. 먼저 PROJECT_SPEC.md, IMPLEMENTATION_STATUS.md, DECISIONS.md,
   KNOWN_LIMITATIONS.md와 이번 단계 관련 문서를 읽어라.
2. 기존 Phase 2~5 서비스와 DB 데이터를 삭제하거나 의미를 바꾸지 마라.
3. 엄격 강제필터, 종합 저평가 점수, 진입준비도, 시장국면, 이벤트 점수를
   서로 다른 필드와 타입으로 유지하라.
4. 결측값을 0으로 처리할 수 있는 것은 전체시장 순위를 위한 명시적
   보수적 점수뿐이다. 원자료의 결측은 NULL과 MISSING으로 보존하라.
5. float 대신 Decimal/NUMERIC을 사용하고, 기준시각 이후 수집된 데이터를
   참조하지 마라.
6. 모든 계산 결과에 score_version, rule_version, config hash,
   input_data_hash, as_of_at, collected_at과 출처를 남겨라.
7. 외부 API 값, 단위, 분류 또는 기업 이벤트를 추정하지 마라.
8. 기존 사용자의 변경사항을 덮어쓰거나 관련 없는 파일을 정리하지 마라.
9. 구현 후 ruff와 관련 pytest를 실행하고 결과를 보고하라.
10. 자동 주문 기능을 만들지 말고 모든 결과를 읽기 전용 투자 검토 자료로
    유지하라.
```

---

## 단계 1. 현황 분석

### 구현 프롬프트

```text
현재 저장소의 종합 저평가 분석 기능 도입 가능성을 분석해라. 이 단계에서는
애플리케이션 동작을 바꾸지 말고 읽기 전용 조사와 문서 작성만 수행해라.

반드시 확인할 파일:
- docs/PROJECT_SPEC.md
- docs/IMPLEMENTATION_STATUS.md
- docs/DECISIONS.md
- docs/KNOWN_LIMITATIONS.md
- docs/scoring_rules.md
- docs/recommendation_rules.md
- app/config.py
- app/db/models 전체
- app/models/scoring.py
- app/models/recommendation.py
- app/services/scoring_service.py
- app/services/market_screening_service.py
- app/services/market_regime_service.py
- app/services/event_service.py
- app/services/recommendation_service.py
- app/ui/recommendations.py
- scripts/update_all.py
- 관련 tests

다음 내용을 docs/comprehensive_undervalue_current_state.md에 작성해라.
1. 현재 데이터 흐름과 서비스 의존관계
2. 현재 각 점수의 목적, 범위, 가중치, 결측 처리
3. 현재 806개인 KOSPI 전체 유니버스의 동적 분석 경로
4. DB에 이미 저장되는 재무·밸류·시장·뉴스·공시 데이터
5. 재사용 가능한 컴포넌트와 새로 필요한 컴포넌트
6. 현재 RecommendationService가 strict Phase 2를 market screen으로
   치환하는 구조의 장점과 위험
7. point-in-time, 단위, 정정공시, 수정주가, 산업분류 관련 위험
8. 최소 변경 경로와 예상 마이그레이션 목록
9. 단계별 테스트 영향 범위

코드를 수정하지 않았는지 git diff로 확인하고, 문서에 파일과 클래스 단위의
근거를 남겨라.
```

### 검수 프롬프트

```text
docs/comprehensive_undervalue_current_state.md를 독립 검수해라.

다음을 확인해라.
- 실제 코드에 없는 서비스나 DB 필드를 문서가 있다고 가정하지 않는가?
- strict Phase 2, KOSPI market screen, Phase 3, Phase 4, Phase 5의 경계가
  정확하게 설명됐는가?
- 결측값 0점 처리와 원자료 MISSING 보존을 구분했는가?
- 현재 806개인 전 종목 분석 경로를 repository query부터 UI까지 추적했으며,
  종목 수를 상수로 고정하지 않았는가?
- 기술부채와 재사용 지점을 파일·함수 근거로 제시했는가?
- 이 단계에서 코드 동작 변경이 없는가?

문제가 있으면 문서만 수정하고, 검수 결과를 PASS/FAIL 표로 남겨라.
```

---

## 단계 2. 설계 문서

### 구현 프롬프트

```text
현황 분석 문서를 바탕으로 종합 저평가 분석의 상세 설계를 작성해라.
아직 DB migration이나 애플리케이션 코드는 구현하지 마라.

docs/comprehensive_undervalue_design.md에 다음을 확정해라.

1. 점수 계층
   - hard_filter_result: 투자배제/검토필요/통과
   - value_score: 상대가치 0~100
   - growth_score: 성장성 0~100
   - quality_score: 재무품질 0~100
   - shareholder_return_score: 배당·자사주 등 0~100
   - event_score: 공시·뉴스 촉매/위험 0~100과 별도 위험 플래그
   - fundamental_score: 위 구성요소를 결합한 0~100
   - entry_score: 가격·수급·시장국면 기반 0~100
   - data_confidence: 데이터 완전성·최신성·공식성 0~100
   - final_attractiveness_score: 최종 순위용 0~100

2. 기본 가중치 초안
   - 상대가치 40
   - 성장성 20
   - 재무품질 20
   - 주주환원 10
   - 뉴스·공시 이벤트 10
   시장국면과 진입준비도는 기업의 내재가치 점수를 바꾸지 말고 최종 판정과
   편입비중에 별도 오버레이로 적용해라.

3. 값이 없는 구성요소의 처리
   - 원자료는 NULL/MISSING 유지
   - 전체시장 순위에서는 해당 구성요소 0점과 confidence 차감을 명시
   - 필수 안전데이터 누락은 점수와 무관하게 REVIEW_REQUIRED
   - 실제 hard filter FAIL은 점수로 상쇄 금지

4. 금융업, 지주회사, 리츠, 적자기업의 별도 규칙
5. 산업·역사·시장 전체 비교의 fallback 순서
6. winsorization/IQR, 최소 표본, 백분위 계산 방식
7. 최종 판정 카테고리와 임계값
8. 버전·입력 해시·재현성 계약
9. 신규 클래스·서비스·repository·table의 책임
10. 기존 Phase 2~5와의 호환·마이그레이션 전략
11. 추천 근거와 위험 근거를 사람이 이해할 수 있는 문장으로 생성하는 계약
12. 성능 목표: KOSPI 1,000개 이하를 로컬 SQLite에서 합리적인 시간 안에 계산

설계 선택마다 대안과 채택 이유를 기록하고 docs/DECISIONS.md에 추가할
결정 초안을 별도 부록으로 작성해라.
```

### 검수 프롬프트

```text
종합 저평가 설계를 투자모형, 데이터 엔지니어링, 기존 코드 호환성 관점에서
독립 검수해라.

특히 다음 실패를 찾아라.
- PER/PBR이 낮다는 이유만으로 부실·적자 기업이 상위권이 되는가?
- 성장주와 금융업을 제조업 가치지표로 잘못 비교하는가?
- 시장국면이 기업의 내재가치 점수를 임의로 변경하는가?
- 뉴스 감성이 hard filter를 상쇄하는가?
- 데이터가 없는 종목이 데이터가 있는 종목보다 유리해지는가?
- 동일 입력으로 같은 결과를 재현할 수 없는가?
- 기존 Phase 2 스냅샷의 의미를 바꾸는가?

각 항목을 PASS/FAIL로 평가하고, FAIL이면 설계 문서만 수정해라.
가중치 합계와 모든 점수 범위도 기계적으로 검산해라.
```

---

## 단계 3. 데이터 모델

### 구현 프롬프트

```text
승인된 종합 저평가 설계에 필요한 데이터 모델과 migration을 구현해라.
기존 table과 column은 삭제하거나 의미를 변경하지 마라.

요구사항:
1. 종합 분석 실행, 종목별 점수, 구성요소, 판정 근거를 정규화해 저장한다.
2. 기존 scoring snapshot과 recommendation run을 재사용할 수 있으면
   foreign key로 연결하되 종합 점수를 Phase 2 필드에 덮어쓰지 않는다.
3. 각 실행에 as_of_at, analyzed_at, basis_date, score_version,
   rule_version, config_hash, input_data_hash, source snapshot hash를 저장한다.
4. 종목별로 value/growth/quality/shareholder/event/fundamental/entry/
   confidence/final score를 nullable NUMERIC으로 저장한다.
5. 구성요소에는 code, state, raw_value, raw_text, normalized_value,
   weight, contribution, source_provider, evidence_date, explanation을 저장한다.
6. hard filter와 missing data를 점수와 별도 JSON 또는 정규화 table로 보존한다.
7. 동일 입력·설정·버전의 중복 실행을 막는 unique constraint를 추가한다.
8. SQLite와 PostgreSQL 양쪽을 고려하고 cascade 정책을 명시한다.
9. app/db/models/__init__.py와 docs/data_dictionary.md를 갱신한다.
10. migration upgrade와 빈 DB 전체 migration 테스트를 추가한다.

모델 이름은 기존 명명 규칙에 맞춰라. 구현 후 migration head까지 올린 새
임시 DB에서 schema와 constraint를 검사하고 관련 pytest를 실행해라.
```

### 검수 프롬프트

```text
신규 종합 분석 DB 모델과 migration을 독립 검수해라.

확인 항목:
- 기존 테이블을 파괴하거나 기존 column 의미를 바꾸지 않았는가?
- 금액·비율·점수에 float가 사용되지 않았는가?
- 점수와 MISSING/FAIL 상태가 분리돼 있는가?
- 동일 실행 재현성 unique key가 충분한가?
- source, as-of, collected-at, version, hash가 빠짐없이 저장되는가?
- upgrade from base와 기존 최신 DB upgrade가 모두 성공하는가?
- foreign key 및 delete 정책이 의도대로 작동하는가?

빈 DB migration, 기존 fixture migration, schema inspection 테스트를 실행하고
PASS/FAIL 및 발견된 위험을 보고해라. 실패가 있으면 모델과 migration만 수정해라.
```

---

## 단계 4. 종합 점수 엔진

### 구현 프롬프트

```text
종합 저평가 점수의 공통 계산 엔진을 구현해라. 이 단계에서는 각 재무 도메인의
세부 공식보다 조합·상태·설명·재현성 프레임워크에 집중해라.

요구사항:
1. app/models에 immutable한 입력·구성요소·결과 Pydantic 모델을 추가한다.
2. app/services에 CompositeUndervalueScoringService 또는 저장소 명명 규칙에
   맞는 동등 서비스를 추가한다.
3. 구성요소 provider 인터페이스를 정의해 value/growth/quality/shareholder/
   event 점수를 독립적으로 공급할 수 있게 한다.
4. Decimal만 사용하고 0~100 clamp와 일관된 quantize 규칙을 적용한다.
5. 가중치 합계를 검증하고 중복 component code를 거부한다.
6. AVAILABLE, MISSING, NOT_APPLICABLE, REVIEW_REQUIRED를 구분한다.
7. 원자료 결측을 0으로 바꾸지 않는다. 전체시장용 보수적 contribution을
   적용한 경우 raw state와 penalty reason을 동시에 남긴다.
8. hard filter FAIL은 final decision 입력으로 전달하되 점수로 상쇄하지 않는다.
9. input_data_hash에 모든 구성요소 원자료, 버전, 가중치, 기준시각을 포함한다.
10. 계산과 DB 저장을 분리하고 pure function 단위 테스트가 가능해야 한다.
11. 기존 MarketScreeningService를 바로 삭제하지 말고 adapter로 연결한다.

경계값, 전부 결측, 일부 결측, 가중치 오류, 중복 코드, 동일 입력 재현성,
입력 변경 시 hash 변경 테스트를 추가하고 실행해라.
```

### 검수 프롬프트

```text
종합 점수 엔진을 property와 불변조건 중심으로 검수해라.

검증할 불변조건:
- 모든 출력 점수는 0~100이다.
- 사용된 contribution 합은 표시된 fundamental score와 일치한다.
- 가중치 합이 잘못되면 조용히 계산하지 않고 실패한다.
- hard filter FAIL은 높은 점수로 사라지지 않는다.
- 결측이 많을수록 confidence가 높아지지 않는다.
- 동일 입력은 동일 hash와 동일 결과를 만든다.
- 기준일 이후 데이터가 입력 hash와 계산에 포함되지 않는다.
- 계산 함수가 DB나 외부 API에 숨은 의존성을 갖지 않는다.

ruff, pyright가 설정돼 있으면 pyright, 관련 pytest를 실행하고 결과를
수치와 함께 보고해라. 실패가 있으면 엔진 범위 안에서 수정해라.
```

---

## 단계 5. 상대가치 평가

### 구현 프롬프트

```text
종합 점수 엔진에 상대가치 평가 모듈을 구현해라.

사용 가능한 공식 데이터와 기존 repository를 먼저 조사하고, 없는 지표를
추정하지 마라. 우선순위는 다음과 같다.
- PER, PBR
- EV/EBITDA 또는 이를 공식 데이터로 정확히 계산할 수 있을 때만 사용
- 배당수익률
- FCF yield
- PEG는 공식 성장률과 양(+)의 PER가 모두 있을 때만 사용

규칙:
1. 현재 종목을 같은 공식 세부 산업과 비교한다.
2. 최소 표본 미달이면 공식 상위 산업, 그 다음 KOSPI 전체로 fallback한다.
3. 양수 유효 표본, IQR/winsorization, 동률 백분위 규칙을 문서화한다.
4. 현재값과 3~5년 자기 역사 분포를 별도 점수로 계산한다.
5. 음수·0 PER는 N/M이며 저평가 점수를 주지 않는다.
6. 금융업·리츠·지주회사는 적용 가능한 지표와 가중치를 별도 설정한다.
7. 낮은 배수만 보지 말고 이익 감소·자본잠식·일회성 이익 위험 플래그를
   quality 모듈과 결합할 수 있게 출력한다.
8. 모든 비교에 classification system, sample size, median, percentile,
   fallback level과 설명을 저장한다.
9. MarketScreeningService의 PER/PBR 백분위를 새 모듈 adapter로 이전하되
   기존 호출은 당장 깨지지 않게 한다.

표본 부족, 극단값, 음수 PER, 금융업, 동률, 산업 fallback,
look-ahead 방지 테스트를 추가해라.
```

### 검수 프롬프트

```text
상대가치 평가를 독립적으로 수학 검수해라.

작은 고정 표본을 손으로 계산해 다음을 비교해라.
- 백분위 방향: 낮은 PER/PBR가 더 높은 점수인가?
- 동률 처리 결과
- IQR 또는 winsorization 경계
- 세부 산업→상위 산업→KOSPI fallback
- 음수·0·NULL 값 처리
- 종목 자신의 값이 비교집단에 포함될 때의 정책
- 과거 시점 데이터만 사용하는지

삼성전자처럼 유동성과 품질은 높지만 배수가 높은 종목, 저PBR 건설주,
적자 저PBR 종목, 금융주 fixture를 포함해 결과가 설명 가능한지 검수해라.
오류가 있으면 상대가치 모듈과 문서만 수정해라.
```

---

## 단계 6. 성장성·품질

### 구현 프롬프트

```text
OpenDART의 point-in-time 재무데이터를 사용해 성장성 및 재무품질 모듈을
구현해라. 기존 account mapping, financial repository, Phase 2 계산을
최대한 재사용하고 같은 공식을 중복 구현하지 마라.

성장성 후보:
- 매출액 YoY 및 3년 CAGR
- 영업이익 YoY 및 3년 CAGR
- 순이익 YoY 및 3년 CAGR
- EPS 성장률
- 최근 성장 가속/감속

품질 후보:
- ROE
- 영업이익률과 안정성
- 영업현금흐름/순이익 현금전환
- FCF와 FCF margin
- 부채비율
- 이자보상비율
- 총자산 대비 발생액 또는 계산 가능한 동등 지표

규칙:
1. 연결재무 우선, 없을 때만 별도재무 fallback이라는 기존 원칙을 지켜라.
2. 누적 분기와 단일 분기를 이중 합산하지 마라.
3. 정정공시의 제출시각을 지키고 미래 정정본을 과거 분석에 사용하지 마라.
4. 일회성 기저효과, 음수에서 양수로의 전환, 분모 0을 별도 상태로 처리한다.
5. 금융업에는 제조업 부채·이자보상 공식을 적용하지 않는다.
6. 성장률과 품질은 산업 내 백분위와 절대 안전기준을 함께 사용한다.
7. 단일 연도 고성장보다 지속성에 더 높은 신뢰도를 준다.
8. 계산식, 사용 계정, 기간, fs_div, receipt_no를 근거로 저장한다.
9. value trap 위험을 별도 플래그로 출력한다.

정정공시, 연결/별도, 누적/단일, 적자전환·흑자전환, 금융업,
불완전 계정매핑 테스트를 추가해라.
```

### 검수 프롬프트

```text
성장성·품질 모듈을 회계 데이터 관점에서 독립 검수해라.

확인 항목:
- CAGR 기간 수와 분모가 올바른가?
- 누적 분기 수치를 단일 분기처럼 비교하지 않는가?
- 흑자전환을 무한 성장률로 표현하지 않는가?
- ROE와 FCF 계산 단위가 일치하는가?
- 일회성 순이익으로 PER와 성장점수가 동시에 과대평가되지 않는가?
- 금융업·지주회사·리츠의 NOT_APPLICABLE 처리가 적절한가?
- 미래 제출 공시가 과거 기준일에 섞이지 않는가?
- value trap 플래그가 저평가 점수와 별도로 유지되는가?

fixture 계산을 손계산과 비교하고 관련 전체 테스트를 실행해라.
발견된 문제는 이 모듈 범위에서 수정해라.
```

---

## 단계 7. 시장국면

### 구현 프롬프트

```text
기존 Phase 3 MarketRegimeService를 종합 저평가 분석에 연결해라.
시장국면이 기업의 fundamental score를 변경하지 않도록 주의해라.

요구사항:
1. 기존 RED/ORANGE/YELLOW/GREEN/UNCERTAIN 정의와 저장 스냅샷을 재사용한다.
2. 시장국면은 다음에만 적용한다.
   - 진입준비도
   - 목표 현금 비중
   - 개별 종목 목표비중 상한
   - 분할매수 상태
   - 최종 판정 문구
3. KOSPI 추세, 시장 폭, 반도체 기여, 배당주 상대강도의 근거를 그대로 보존한다.
4. 시장 데이터 MISSING이면 fundamental rank는 표시할 수 있지만
   진입 판정은 REVIEW_REQUIRED로 둔다.
5. RED에서도 우량 저평가 후보를 목록에서 삭제하지 말고
   QUALITY_WAIT 또는 동등한 관망 카테고리로 표시한다.
6. 동일 기업 점수가 시장국면만 바뀌어도 fundamental score는 동일해야 한다.
7. Phase 3 hash와 rule version을 종합 실행 입력에 포함한다.
8. 기존 portfolio_service의 국면별 비중 설정을 재사용한다.

국면별 동일 종목 점수 불변, 진입준비도 변화, 목표비중 상한,
UNCERTAIN 처리 테스트를 추가해라.
```

### 검수 프롬프트

```text
시장국면 통합을 독립 검수해라.

RED, ORANGE, YELLOW, GREEN, UNCERTAIN fixture에 같은 종목 분석을 넣고:
- fundamental score가 완전히 동일한지
- entry score와 목표비중만 규칙대로 달라지는지
- RED에서 종목이 이유 없이 투자배제로 바뀌지 않는지
- 시장 데이터 누락이 가짜 GREEN 또는 0점으로 처리되지 않는지
- Phase 3의 point-in-time과 수정가격 게이트가 유지되는지
확인해라.

모든 비교 결과를 표로 보고하고 실패 시 시장 오버레이 코드만 수정해라.
```

---

## 단계 8. 뉴스·공시 이벤트

### 구현 프롬프트

```text
기존 EventService, OpenDART Disclosure, Naver News 데이터를 종합 분석에
연결하는 이벤트 평가 모듈을 구현해라.

공시 이벤트 예:
- 감사의견, 계속기업 불확실성
- 유상증자, CB/BW, 대규모 희석
- 최대주주 변경
- 거래정지·관리·상장폐지 위험
- 대규모 수주·계약
- 배당 확대·축소
- 자사주 취득·소각
- 실적 정정과 대규모 손상

규칙:
1. 감사의견·거래정지 등 안전 관련 hard event는 점수와 분리한다.
2. 촉매와 위험을 별도 목록으로 저장한다.
3. 뉴스는 종목코드, 정식명, 약칭, 사용자 검색어를 사용하되 동명이인
   오탐 방지 근거를 남긴다.
4. 동일 URL·접수번호·제목의 중복을 제거한다.
5. 정정공시는 원공시와 연결하고 최신 정정 내용을 우선한다.
6. 이벤트 점수에 source reliability와 time decay를 적용한다.
7. 단순 키워드만으로 투자배제를 확정하지 말고 REVIEW_REQUIRED로 둔다.
8. 감성분석을 추가한다면 모델·규칙 버전, 입력 제목, 결과 근거를 저장하고
   재현 불가능한 외부 생성 결과를 핵심 점수에 직접 사용하지 않는다.
9. 뉴스가 0건인 것을 긍정 또는 부정으로 해석하지 않는다.
10. 기존 Phase 5 UI와 수집 스크립트의 호환성을 유지한다.

중복, 정정공시, 동명이인, 오래된 뉴스 감쇠, 뉴스 0건,
hard event 우선순위 테스트를 추가해라.
```

### 검수 프롬프트

```text
뉴스·공시 이벤트 모듈을 오탐·누락·상쇄 위험 관점에서 검수해라.

확인 항목:
- 동일 공시/뉴스가 여러 번 점수에 반영되지 않는가?
- 긍정 뉴스가 감사의견 FAIL을 상쇄하지 않는가?
- 종목명 일부 일치로 다른 회사 뉴스가 연결되지 않는가?
- 정정공시가 원공시와 모순된 채 둘 다 활성화되지 않는가?
- 오래된 이벤트의 영향이 설정대로 감소하는가?
- 뉴스 0건이 중립이며 confidence만 정직하게 표시되는가?
- 설명 문장에서 사실, 규칙 기반 해석, 추정이 구분되는가?

fixture와 repository 조회를 함께 검증하고 실패 시 이벤트 계층만 수정해라.
```

---

## 단계 9. 최종 판정

### 구현 프롬프트

```text
종합 점수, hard filter, 시장국면, 이벤트를 결합하는 최종 판정 엔진을 구현해라.
기존 RecommendationCategory와의 하위 호환을 유지하되 필요하면 새 상세
판정 코드를 별도 필드로 추가해라.

최종 판정 예:
- STRONG_VALUE_CANDIDATE: 저평가·품질·데이터 신뢰도 우수
- QUALITY_AT_FAIR_VALUE: 품질·성장은 우수하지만 할인 부족
- DEEP_VALUE_REVIEW: 할인은 크지만 value trap 검토 필요
- TURNAROUND_WATCH: 개선 신호는 있으나 확인 기간 부족
- QUALITY_WAIT: 기업 점수는 우수하나 시장/진입 조건 대기
- GENERAL_REVIEW
- EXCLUDED: 실제 hard filter FAIL
- REVIEW_REQUIRED: 필수 안전데이터 또는 신뢰도 부족

규칙:
1. fundamental score와 final attractiveness score의 공식을 명시한다.
2. final rank는 실행 시점의 KOSPI 전체 유니버스에 부여하되
   EXCLUDED/REVIEW_REQUIRED 상태를 숨기지 않는다.
3. 카테고리, 점수, 순위를 별도 필드로 유지한다.
4. 목표비중 0은 비선정이며 계산불가와 구분한다.
5. 상위 추천 이유는 가장 기여도가 큰 3개 구성요소의 실제 값과 백분위로 쓴다.
6. 위험 이유는 hard filter, value trap, 데이터 신뢰도, 시장국면 순으로 쓴다.
7. 삼성전자처럼 가치점수는 낮지만 품질·성장이 높은 종목을
   QUALITY_AT_FAIR_VALUE로 설명할 수 있어야 한다.
8. 저PER·저PBR이지만 품질이 낮은 종목을 자동 최상위 추천하지 않는다.
9. 동일 점수 tie-break 규칙을 고정하고 symbol을 최종 tie-break로 사용한다.
10. 기존 Phase 4 run 저장과 포트폴리오 한도, 읽기 전용 원칙을 유지한다.
11. update_all.py에서 종합 점수 실행이 데이터 수집 이후, 최종 추천 이전에
    올바른 순서로 실행되게 한다.

카테고리 경계, hard filter 우선, tie-break, 목표비중 0,
삼성전자형/저PBR 부실주형 fixture 테스트를 추가해라.
```

### 검수 프롬프트

```text
최종 판정 엔진을 반례 중심으로 독립 검수해라.

최소 다음 가상 종목을 비교해라.
1. 매우 싼 우량주
2. 매우 싸지만 적자·부채 위험이 큰 종목
3. 비싸지만 성장·품질이 높은 대형주
4. 데이터가 절반 이상 없는 종목
5. 감사의견 FAIL이지만 다른 점수가 높은 종목
6. 기업 점수는 높지만 시장국면 RED인 종목

각 종목의 fundamental score, final score, rank, category, target weight,
positive reasons, risk reasons를 표로 출력해 논리 모순을 확인해라.
hard filter가 상쇄되거나 결측 종목이 부당하게 상위권이면 FAIL이다.
관련 코드를 수정하고 다시 검수해라.
```

---

## 단계 10. UI

### 구현 프롬프트

```text
Streamlit 추천종목 화면에 종합 저평가 분석 결과를 구현해라.
기존 app/ui/recommendations.py의 전체 KOSPI 분석 버튼, 진행률, 상세 화면,
읽기 전용 안내를 유지해라.

화면 요구사항:
1. 버튼명은 KOSPI 전체 종합 분석·추천으로 명확히 표시한다.
2. 분석 종목 수, 점수 계산 완료 수, 검토 후보, REVIEW_REQUIRED,
   EXCLUDED, 데이터 기준일을 요약한다.
3. 기본 표에 전체 순위, 종목, 최종 판정, 종합 매력점수, 가치, 성장,
   품질, 주주환원, 이벤트, 진입준비도, 신뢰도, 목표비중을 표시한다.
4. 기본 목록은 추천 후보를 보여주되 체크박스로 실행 시점의 전체 순위를
   볼 수 있다.
5. 가치·성장·품질 등 점수별 정렬과 최소 점수 필터를 제공한다.
6. 종목 상세에는 실제 PER/PBR, 산업 중앙값/백분위, 성장률, ROE,
   현금흐름, 주요 공시·뉴스, 시장국면, 긍정 근거, 위험 근거를 표시한다.
7. 점수 없음, 0점, 비선정 0%, REVIEW_REQUIRED를 서로 다르게 표현한다.
8. 삼성전자처럼 가치점수는 낮지만 품질이 높은 종목의 판정 이유가
   한눈에 이해되게 한다.
9. tooltip 또는 caption으로 각 점수의 의미와 가중치를 설명한다.
10. 모바일에서도 표가 깨지지 않도록 핵심 열과 상세 expander를 분리한다.
11. 기존 메뉴, 공시·뉴스 탭과 연결상태 화면을 깨뜨리지 않는다.
12. 자동 주문이 없다는 안내를 유지한다.

AppTest를 사용해 빈 DB, 전체 데이터, 일부 결측, EXCLUDED,
REVIEW_REQUIRED, 상위 후보 상세 화면 테스트를 추가해라.
```

### 검수 프롬프트

```text
종합 추천 UI를 사용자 관점과 데이터 진실성 관점에서 검수해라.

확인 항목:
- 관심종목 수와 무관하게 KOSPI 전체 분석임이 보이는가?
- 기본 표가 3개 종목으로 고정되지 않는가?
- 계산불가와 0점, 비선정 0%를 혼동하지 않는가?
- 추천 이유에 실제 값과 비교 기준이 나오는가?
- 제외 사유와 데이터 부족 사유가 숨겨지지 않는가?
- 시장 RED가 기업 저평가 점수를 낮춘 것처럼 표시되지 않는가?
- 버튼을 연속 클릭해도 동일 입력이면 기존 실행을 재사용하는가?
- 빈 DB나 API 키 미설정 상태에서 가짜 추천이 나오지 않는가?

Streamlit AppTest와 가능하면 실제 로컬 화면을 확인하고, 문제를 UI 계층에서
수정한 뒤 PASS/FAIL 결과를 보고해라.
```

---

## 단계 11. 테스트·검수

### 구현 프롬프트

```text
종합 저평가 분석 전체 구현을 최종 검수하고 필요한 수정까지 수행해라.

검수 순서:
1. git status와 diff를 확인해 사용자 기존 변경을 구분한다.
2. migration을 빈 DB와 기존 DB 복사본에 적용한다.
3. ruff check app scripts tests를 실행한다.
4. pyright가 프로젝트에 설정돼 있으면 실행한다.
5. 전체 pytest를 실행한다.
6. update_all.py의 step 순서와 실패 전파를 테스트한다.
7. 외부 API를 다시 호출하지 않고 저장된 fixture/DB로 전체 유니버스 분석을
   실행한다. 현재 운영 DB의 기대값은 806개지만 숫자를 코드에 고정하지 않는다.
8. 다음 불변조건을 DB 쿼리로 확인한다.
   - total_count가 실제 KOSPI 보통주 수와 일치
   - 모든 종목에 rank가 존재
   - 점수는 0~100 또는 명시적 NULL
   - EXCLUDED/REVIEW_REQUIRED 사유가 존재
   - 목표비중 합과 종목·업종·기업집단 한도가 설정을 초과하지 않음
   - 동일 입력 재실행이 같은 결과를 재사용
   - 기준일 이후 데이터 미참조
9. 상위 20개, 삼성전자, 저PBR 건설주, 적자기업, 금융주를 표본 검토한다.
10. Streamlit AppTest와 /_stcore/health를 확인한다.
11. docs/CHANGELOG.md, IMPLEMENTATION_STATUS.md, KNOWN_LIMITATIONS.md,
    DECISIONS.md, scoring_rules.md, recommendation_rules.md를 실제 구현과 맞춘다.

테스트 실패를 숨기거나 제외하지 말고 원인을 수정해라. 외부 연결이나
실제 데이터 때문에 재현할 수 없는 검사는 그 이유와 수동 검수 절차를
명시해라. 최종 보고에는 변경 파일, migration, 점수 공식, 테스트 개수,
현재 운영 DB 전체 유니버스 실행 요약, 상위 후보, 알려진 한계와 실행 명령을
포함해라.
```

### 검수 프롬프트

```text
당신은 구현자가 아닌 독립 감사자다. 종합 저평가 기능의 최종 결과를
승인 또는 반려해라.

다음 증거가 없으면 승인하지 마라.
- 전체 diff와 migration 검토
- 전체 ruff/pytest 통과 결과
- 실행 시점의 KOSPI 전체 종목 결과와 repository universe count의 일치
- 점수 NULL/범위/순위 중복 DB 검산
- hard filter 비상쇄 반례 테스트
- point-in-time 및 정정공시 테스트
- 업종 상대평가 수학 검산
- 시장국면과 fundamental score 분리 테스트
- 뉴스·공시 중복 및 오탐 테스트
- UI의 0점/결측/비선정 구분 테스트
- 포트폴리오 한도 검산

결과를 Critical/High/Medium/Low 심각도로 분류하고, Critical 또는 High가
하나라도 남으면 FAIL로 판정해라. 수정 가능한 항목은 수정 후 전체 검수를
처음부터 다시 실행해라. 마지막에 승인 여부, 남은 한계, 재현 명령을
간결하게 보고해라.
```

## 4. 단계 실행 방법

각 단계는 다음처럼 진행한다.

1. 해당 단계의 `구현 프롬프트`를 Codex에 복사한다.
2. 변경 파일과 테스트 결과를 확인한다.
3. 같은 단계의 `검수 프롬프트`를 새 요청으로 복사한다.
4. 검수가 PASS일 때만 다음 단계로 이동한다.
5. FAIL이면 현재 단계 범위 안에서 수정하고 검수를 반복한다.

기본 검증 명령은 Windows PowerShell 기준으로 다음과 같다.

```powershell
.\.venv\Scripts\ruff.exe check app scripts tests
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe -m scripts.update_all --help
.\.venv\Scripts\python.exe -m streamlit run app/main.py
```

실제 외부 API 전체 수집은 구현 검수와 분리한다. 저장된 데이터로 계산 경로를
먼저 검증하고, 사용자가 승인한 경우에만 KRX, OpenDART, KIS, NAVER, ECOS
호출을 실행한다.
