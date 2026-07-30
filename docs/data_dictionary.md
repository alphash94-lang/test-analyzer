# 데이터 사전

## 범위와 원칙

이 문서는 Alembic revision `r4g7h8i9j0k1`의 애플리케이션 테이블을
기준으로 한다. 실제 원응답은 `api_raw_responses`와 `data/raw`에 보존하고,
정규화·계산 결과는 도메인 테이블에 분리한다.

- 금액·수량·비율은 SQLAlchemy `Numeric`/Python `Decimal`을 사용한다.
- `NULL`은 미제공·미확인·계산 불가이고 숫자 0과 다르다.
- 시각은 애플리케이션 경계에서 timezone-aware `Asia/Seoul`로 검증한다.
- `as_of_at`은 데이터 기준시각, `collected_at`은 프로그램 수집시각이다.
- `data_state=AVAILABLE`은 검증된 정상 데이터만 뜻한다. 오류 응답은
  `FETCH_FAILED`, 누락은 `MISSING`, 충돌은 `CONFLICT` 등으로 분리한다.
- `data_timing`은 `REALTIME`, `DELAYED`, `PREVIOUS_CLOSE`, `UNKNOWN`,
  `NOT_APPLICABLE` 같은 시세·가용 시점 구분이다.
- 접수번호, 원접수번호와 `is_correction`은 정정공시의 시점 진실성을
  보존한다. 정정본을 원본 위에 덮어쓰지 않는다.
- `source_provider`, `source_function`, hash와 rule/version 필드는
  출처·재현성 증거다.

## 공통 필드

| 필드 | 의미 |
|---|---|
| `id` | 내부 surrogate primary key |
| `stock_id` | `stocks.id` 외래키 |
| `source_provider` | KRX, OpenDART, KIS, 자체 계산 등 원천 |
| `source_function` | 공식 기능명 또는 계산 기능명 |
| `data_state` | 정상·누락·실패·충돌·미검증 상태 |
| `as_of_at` | 자료가 의미하는 기준일 또는 기준시각 |
| `collected_at` | 프로그램이 자료를 수집한 시각 |
| `data_timing` | 실시간·지연·전일종가·해당없음 구분 |
| `created_at` | DB 레코드 생성시각 |
| `input_data_hash` | 정렬된 입력 계약의 SHA-256 |
| `config_hash` | 계산에 사용한 설정의 SHA-256 |
| `rule_version` | 판정 규칙 버전 |
| `score_version` | 점수 계약 버전 |

## 원자료와 품질

### `api_raw_responses`

외부 HTTP 응답의 메타데이터와 작은 텍스트 응답을 보존한다.

- 핵심 필드: `provider`, `function_name`, `endpoint`,
  `request_params_hash`, `received_at`, `as_of_at`, `http_status`,
  `response_hash`, `normalized_success`, `data_state`, `error_code`,
  `error_message`, `raw_storage_path`, `content_type`
- 인증키는 endpoint, 요청 hash 입력, 저장 경로에 포함하지 않는다.
- 같은 provider·기능·요청 hash·응답 hash는 중복 저장하지 않는다.

### `data_quality_logs`

정규화 거부, 미매핑, 충돌과 검토 필요 사유를 기록한다.

- 핵심 필드: `entity_type`, `entity_id`, `provider`, `issue_code`,
  `severity`, `data_state`, `message`, `detected_at`, `resolved_at`,
  `context`

## 종목·분류·시장상태

### `stocks`

KRX 종목 마스터와 OpenDART 고유번호 정확 일치 결과다.

- 핵심 필드: `symbol`, `name_ko`, `issue_code`, `market_name`,
  `security_group_name`, `certificate_type_name`, `security_type`,
  `share_class`, `listed_on`, `delisted_on`, `listing_status`,
  `universe_status`, `quality_state`, `is_kospi`, `is_active`,
  `dart_corp_code`, `dart_modified_on`, `dart_collected_at`,
  `dart_data_state`

### `stock_classifications`

공식 분류 체계별 이력을 저장한다.

- 핵심 필드: `classification_system`, `classification_code`,
  `classification_name`, `valid_from`, `valid_to`
- KRX `SECT_TP_NM` 소속부를 산업분류로 바꾸지 않는다.

### `market_status`

거래정지, 관리, 투자주의·경고·위험 등 공식 상태를 위한 시점 테이블이다.

- 핵심 필드: `status_type`, `status_value`, `effective_from`,
  `effective_to`
- 공식 writer가 없는 상태값은 정상으로 가정하지 않는다.

## 가격과 지수

### `price_daily`

종목별 일별 OHLCV와 수정가격 검증 상태다.

- 핵심 필드: `trade_date`, `currency`, `open_price`, `high_price`,
  `low_price`, `close_price`, `volume`, `trading_value`, `market_cap`,
  `listed_shares`, `is_adjusted`, `adjustment_status`
- `adjustment_status=VERIFIED`가 아니면 기술지표·백테스트 입력으로 쓰지
  않는다.

### `index_daily`

KRX KOSPI 시리즈 등 공식 지수의 일별 시계열이다.

- 핵심 필드: `index_class`, `index_name`, `trade_date`, `close`,
  `previous_day_change`, `fluctuation_rate`, `open`, `high`, `low`,
  `volume`, `trading_value`, `market_cap`

## 공시·재무·배당·감사

### `disclosures`

OpenDART 공시 메타데이터와 원·정정 연결 상태다.

- 핵심 필드: `corp_code`, `receipt_no`, `original_receipt_no`,
  `report_name`, `receipt_date`, `filer_name`, `disclosure_type`,
  `correction_note`, `is_correction`, `correction_link_state`,
  `source_url`, `raw_response_id`

### `financial_statements`

보고서 단위 재무제표 헤더다.

- 핵심 필드: `corp_code`, `receipt_no`, `original_receipt_no`,
  `report_code`, `report_name`, `business_year`, `statement_kind`,
  `fs_div`, `period_start`, `period_end`, `period_label`, `filing_date`,
  `is_cumulative`, `is_correction`, `currency`, `source_url`,
  `raw_response_id`
- `fs_div`는 연결(CFS)과 별도(OFS)를 구분한다.

### `financial_accounts`

재무제표 원계정과 정규화 계정 매핑을 함께 보존한다.

- 핵심 필드: `statement_id`, `account_id`, `account_name`,
  `account_detail`, `statement_section`, `raw_label`,
  `current_amount`, `current_cumulative_amount`, `prior_amount`,
  `prior_quarter_amount`, `prior_cumulative_amount`,
  `before_prior_amount`, `unit`, `mapping_status`,
  `canonical_metric_code`
- 매핑 실패는 `UNMAPPED`/`NULL`이며 0이 아니다.

### `financial_metrics`

분기 단독값, TTM 등 공식 입력으로 자체 계산한 재무지표다.

- 핵심 필드: `metric_code`, `value`, `unit`, `period_start`,
  `period_end`, `fs_div`, `rule_version`, `input_data_hash`

### `dividend_facts`

OpenDART 배당 표의 원 라벨과 원 값을 보존한다.

- 핵심 필드: `receipt_no`, `business_year`, `label`, `stock_kind`,
  `current_raw`, `prior_raw`, `before_prior_raw`, `fiscal_date`,
  `filing_date`, `unit_status`, `source_url`, `raw_response_id`

### `dividends`

단위와 확정 여부가 검증된 정규화 배당이다.

- 핵심 필드: `receipt_no`, `original_receipt_no`, `business_year`,
  `stock_kind`, `dividend_type`, `dps`, `currency`, `total_amount`,
  `record_date`, `payment_date`, `fiscal_date`, `filing_date`,
  `is_confirmed`, `is_estimate`, `is_correction`, `source_url`
- 공식 추정 DPS가 없으면 `is_estimate=true` 레코드를 임의 생성하지 않는다.

### `audit_opinions`

최신 감사의견과 강조사항 확인 상태다.

- 핵심 필드: `receipt_no`, `original_receipt_no`, `business_year`,
  `fiscal_date`, `filing_date`, `auditor`, `opinion`, `special_matter`,
  `emphasis_matter`, `core_audit_matter`, `going_concern_risk`,
  `going_concern_status`, `internal_control_issue`, `emphasis_status`,
  `is_correction`, `source_url`

## 강제필터·점수·밸류에이션

### `score_snapshots`

한 종목의 기준시점 점수 실행 헤더다.

- 핵심 필드: `score_version`, `rule_version`, `input_data_hash`,
  `investment_score`, `individual_entry_score`, `entry_score`,
  `data_confidence`, `score_scope`, `filter_state`,
  `recommendation_computable`, `missing_core_data`, `explanation`

### `forced_filter_results`

강제필터별 통과·실패·누락·검토 필요 결과다.

- 핵심 필드: `score_snapshot_id`, `filter_code`, `filter_name`,
  `state`, `is_blocking`, `reason`, `raw_value`, `raw_text`,
  `source_provider`, `evidence_date`

### `score_components`

설명 가능한 구성요소별 점수 증거다.

- 핵심 필드: `score_name`, `component_code`, `state`, `raw_value`,
  `raw_text`, `normalized_value`, `weight`, `contribution`,
  `explanation`, `source_kind`

### `valuation_comparisons`

산업·자체 역사 밸류에이션 비교 결과다.

- 핵심 필드: `metric_code`, `state`, `current_value`,
  `industry_median`, `historical_median`, `industry_percentile`,
  `historical_percentile`, `comparison_level`, `classification_code`,
  `sample_size`, `explanation`

## 시장충격·시장국면

### `market_regime_snapshots`

한 기준시점의 Phase 3 실행 헤더다.

- 핵심 필드: `rule_version`, `input_data_hash`, `shock_classification`,
  `market_regime`, `data_confidence`, `proxy_kind`,
  `semiconductor_recovery`, `kospi_recovery`,
  `non_semiconductor_breadth`, `dividend_relative_strength_recovery`,
  `missing_core_data`, `explanation`

### `market_metric_records`

시장국면 숫자·상태와 provenance를 지표 단위로 저장한다.

- 핵심 필드: `metric_code`, `metric_label`, `state`, `value`,
  `text_value`, `unit`, `calculation_method`, `data_quality`,
  `source_kind`, `proxy_kind`

### `market_contribution_records`

종목별 시장수익률 설명 기여도 추정치다.

- 핵심 필드: `symbol`, `name`, `return_rate`, `previous_weight`,
  `contribution`, `is_semiconductor`, `market_cap_source_provider`,
  `classification_source`, `calculation_method`, `data_quality`,
  `source_kind`, `proxy_kind`
- 공식 지수 포인트 기여도나 인과관계가 아니다.

## 추천·분할매수·포트폴리오

### `portfolio_settings`

사용자 포트폴리오 설정의 버전형 레코드다.

- 핵심 필드: `profile_name`, `profile_hash`, `total_capital`,
  `current_cash`, `risk_profile`, `target_dividend_yield`,
  `target_stock_count`, 종목·산업·기업집단 최대비중,
  `include_preferred`, `include_reits`, `minimum_trading_value`,
  `normal_target`, `regime_targets`, `config_payload`, `selected_at`

### `portfolio_positions`

사용자가 입력한 보유종목이다.

- 핵심 필드: `portfolio_setting_id`, `quantity`,
  `average_purchase_price`, `currency`, `as_of_date`, `source`

### `recommendation_runs`

전체 유니버스 추천 실행 헤더다.

- 핵심 필드: `analyzed_at`, `data_basis_date`, `status`,
  `score_version`, `rule_version`, `market_rule_version`,
  `market_regime`, `config_hash`, `input_data_hash`,
  `source_snapshot_hashes`, 처리·추천·제외·누락 건수,
  `missing_core_data`, `explanation`

### `recommendations`

종목별 추천·투자배제·데이터 부족 결과다.

- 핵심 필드: `recommendation_type`, `recommendation_label`, `rank`,
  `score_scope`, `entry_score_scope`, `investment_score`, `entry_score`,
  `data_confidence`, `market_regime`, `portfolio_sleeve`,
  `industry_code`, `company_group_code`, `company_group_check_state`,
  `target_weight`, `initial_buy_weight`, `holding_action`,
  `raw_metrics`, `filter_results`, 긍정·위험·제외·누락 사유

### `recommendation_reasons`

추천별 정렬된 사유 목록이다.

- 핵심 필드: `reason_type`, `sequence`, `reason_code`, `reason_text`

### `split_buy_plans`

읽기 전용 분할매수 검토안이다.

- 핵심 필드: `status`, `reference_price`, `reference_price_date`,
  `reference_price_provider`, `reference_price_currency`,
  `reference_price_collected_at`, `reference_price_timing`, `tranches`,
  `cancellation_conditions`, `is_order_executable`, `explanation`
- DB 제약상 `is_order_executable=false`다.

### `portfolio_allocations`

추천 실행의 종목별 목표비중과 한도 적용 결과다.

- 핵심 필드: `sleeve`, `target_weight`, `initial_buy_weight`,
  `industry_code`, `company_group_code`, `company_group_check_state`,
  `rationale`

## 이벤트·뉴스·애널리스트·수급

### `news_articles`

네이버 API HUB가 제공한 제목과 요약만 저장한다.

- 핵심 필드: `query`, `title`, `summary`, `publisher`,
  `original_url`, `provider_url`, `canonical_url`, `normalized_title`,
  `content_hash`, `published_at`, `used_text_scope`, `raw_response_id`

### `event_records`

구조화 규칙으로 분류한 공시·뉴스 이벤트다.

- 핵심 필드: `source_kind`, `source_record_key`, `title`,
  `event_type`, `event_date`, `published_at`, `source_url`, `sentiment`,
  `confidence`, `rationale`, `matched_rule`, `used_text_scope`,
  `used_text`, `price_reflection_note`, `rule_version`, `is_correction`,
  `original_source_key`, `correction_link_state`

### `analyst_opinions`

증권사 의견·목표주가 참고 데이터다.

- 핵심 필드: `broker`, `opinion`, `target_price`, `currency`,
  `published_date`, `source_url`, `is_estimate`, `raw_response_id`

### `earnings_estimates`

EPS 등 추정치의 확장 테이블이다.

- 핵심 필드: `broker`, `metric_code`, `fiscal_period`,
  `estimate_value`, `unit`, `currency`, `published_date`,
  `source_url`, `is_estimate`
- 현재 안전한 공식 필드 계약이 미확정이어서 운영 숫자는 생성하지 않는다.

### `investor_flows`

외국인·기관·개인 실제 순매수 참고 데이터다.

- 핵심 필드: `trade_date`, `investor_type`, `net_purchase_quantity`,
  `net_purchase_amount`, `currency`, `unit`, `raw_response_id`

### `program_trading`

KOSPI 프로그램매매 참고 데이터다.

- 핵심 필드: `market_code`, `trade_date`, `net_purchase_quantity`,
  `net_purchase_amount`, `currency`, `unit`, `raw_response_id`

### `short_selling`

종목별 공매도 참고 데이터다.

- 핵심 필드: `trade_date`, `short_quantity`, `short_amount`,
  `short_ratio`, `currency`, `unit`, `raw_response_id`

## 백테스트

### `backtest_runs`

시점정보 입력 계약과 결과를 한 실행 단위로 보존한다.

- 핵심 필드: `analyzed_at`, `start_date`, `end_date`, `confidence`,
  `backtest_version`, `rule_version`, `config_hash`, `input_data_hash`,
  score·추천·시장 규칙 버전, `universe_construction_method`,
  `financial_availability_method`, `correction_availability_method`,
  `execution_price_method`, `adjusted_price_source`,
  `dividend_treatment_method`, `transaction_cost_bps`,
  `transaction_cost_assumption`, `benchmark_method`,
  `walk_forward_method`, `known_survival_bias`, `missing_data`,
  `config_payload`, `input_payload`, `result_payload`
- 숫자 결과가 불완전하면 `result_payload`의 성과는 만들지 않고
  `data_state=MISSING`과 누락 사유를 저장한다.

## DB 관리

### `alembic_version`

Alembic이 현재 migration revision을 저장하는 관리 테이블이다. 도메인
데이터가 아니며 애플리케이션이 직접 수정하지 않는다.
