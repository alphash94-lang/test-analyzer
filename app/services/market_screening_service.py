from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from itertools import pairwise

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models.financial import (
    FinancialAccount,
    FinancialMetric,
    FinancialStatement,
)
from app.db.models.market import PriceDaily, Stock, StockClassification
from app.models.metadata import DataState
from app.models.scoring import ComponentState, ScoreComponent
from app.services.score_component_common import quantize_score

SCREEN_SCORE_SCOPE = "KOSPI_MARKET_SCREEN_V1"
SCREEN_SCORE_VERSION = "market-screen-score-v3"
SCREEN_RULE_VERSION = "market-screen-rule-v3"

_REPORT_PERIOD_ORDER = {
    "11013": 1,
    "11012": 2,
    "11014": 3,
    "11011": 4,
}


def _statement_period_end(statement: FinancialStatement) -> date:
    if statement.period_end is not None:
        return statement.period_end
    month_day = {
        "11013": (3, 31),
        "11012": (6, 30),
        "11014": (9, 30),
        "11011": (12, 31),
    }[statement.report_code]
    return date(statement.business_year, *month_day)


@dataclass(frozen=True)
class MarketScreenScore:
    stock_id: int
    symbol: str
    investment_score: Decimal
    individual_entry_score: Decimal
    data_confidence: Decimal
    industry_code: str
    components: tuple[ScoreComponent, ...]
    explanation: str
    input_data_hash: str


@dataclass(frozen=True)
class LatestProfitability:
    net_income: Decimal
    period_end: date
    receipt_no: str


def _rank_score(
    value: Decimal | None,
    population: list[Decimal],
    *,
    lower_is_better: bool,
) -> Decimal:
    if value is None or not population:
        return Decimal(0)
    less = sum(item < value for item in population)
    equal = sum(item == value for item in population)
    percentile = (
        (Decimal(less) + Decimal(equal) / Decimal(2))
        / Decimal(len(population))
        * Decimal(100)
    )
    return quantize_score(
        Decimal(100) - percentile if lower_is_better else percentile
    )


def _return(start: Decimal, end: Decimal) -> Decimal | None:
    return end / start - Decimal(1) if start > 0 else None


def _display_decimal(value: Decimal) -> str:
    return f"{value:f}".rstrip("0").rstrip(".")


class MarketScreeningService:
    """Build a comparable score for every listed KOSPI common stock."""

    def build(
        self,
        session: Session,
        stocks: list[Stock],
        *,
        as_of_at: datetime,
    ) -> dict[int, MarketScreenScore]:
        stock_ids = [stock.id for stock in stocks]
        if not stock_ids:
            return {}

        price_rows = session.scalars(
            select(PriceDaily)
            .where(
                PriceDaily.stock_id.in_(stock_ids),
                PriceDaily.trade_date <= as_of_at.date(),
                PriceDaily.source_provider == "KRX",
                PriceDaily.data_state == DataState.AVAILABLE.value,
                PriceDaily.close_price.is_not(None),
                PriceDaily.collected_at <= as_of_at,
            )
            .order_by(
                PriceDaily.stock_id,
                PriceDaily.trade_date.desc(),
                PriceDaily.id.desc(),
            )
        ).all()
        histories: dict[int, list[PriceDaily]] = {}
        seen_dates: dict[int, set[object]] = {}
        for row in price_rows:
            dates = seen_dates.setdefault(row.stock_id, set())
            if row.trade_date in dates or len(dates) >= 61:
                continue
            dates.add(row.trade_date)
            histories.setdefault(row.stock_id, []).append(row)
        for rows in histories.values():
            rows.reverse()

        metrics = session.scalars(
            select(FinancialMetric)
            .where(
                FinancialMetric.stock_id.in_(stock_ids),
                FinancialMetric.metric_code.in_(("CURRENT_PER", "CURRENT_PBR")),
                FinancialMetric.period_end <= as_of_at.date(),
                FinancialMetric.data_state == DataState.AVAILABLE.value,
                FinancialMetric.value.is_not(None),
                FinancialMetric.collected_at <= as_of_at,
            )
            .order_by(
                FinancialMetric.stock_id,
                FinancialMetric.metric_code,
                FinancialMetric.period_end.desc(),
                FinancialMetric.id.desc(),
            )
        ).all()
        metric_map: dict[tuple[int, str], Decimal] = {}
        for row in metrics:
            if row.value is not None:
                metric_map.setdefault((row.stock_id, row.metric_code), row.value)

        profitability = self._latest_profitability(
            session,
            stock_ids,
            as_of_at=as_of_at,
        )

        classifications = session.scalars(
            select(StockClassification)
            .where(
                StockClassification.stock_id.in_(stock_ids),
                StockClassification.classification_system.in_(
                    ("KIS_INDUSTRY_NAME", "DART_PARENT_INDUSTRY")
                ),
                StockClassification.data_state == DataState.AVAILABLE.value,
                StockClassification.collected_at <= as_of_at,
            )
            .order_by(
                StockClassification.stock_id,
                StockClassification.classification_system.desc(),
                StockClassification.valid_from.desc(),
                StockClassification.id.desc(),
            )
        ).all()
        industry_map: dict[int, str] = {}
        for row in classifications:
            industry_map.setdefault(row.stock_id, row.classification_code)

        per_values = [
            value
            for (stock_id, code), value in metric_map.items()
            if stock_id in stock_ids
            and code == "CURRENT_PER"
            and value > 0
            and (
                stock_id not in profitability
                or profitability[stock_id].net_income > 0
            )
        ]
        pbr_values = [
            value
            for (stock_id, code), value in metric_map.items()
            if stock_id in stock_ids and code == "CURRENT_PBR" and value > 0
        ]
        liquidities = [
            rows[-1].trading_value
            for rows in histories.values()
            if rows and rows[-1].trading_value is not None
        ]
        volatilities = [
            value
            for rows in histories.values()
            if (value := self._volatility(rows)) is not None
        ]
        returns_60 = [
            value
            for rows in histories.values()
            if (value := self._period_return(rows, 60)) is not None
        ]

        return {
            stock.id: self._score(
                stock,
                histories.get(stock.id, []),
                per=metric_map.get((stock.id, "CURRENT_PER")),
                pbr=metric_map.get((stock.id, "CURRENT_PBR")),
                industry=industry_map.get(stock.id),
                per_values=per_values,
                pbr_values=pbr_values,
                liquidities=[value for value in liquidities if value is not None],
                volatilities=volatilities,
                returns_60=returns_60,
                as_of_at=as_of_at,
                latest_net_income=(
                    profitability[stock.id].net_income
                    if stock.id in profitability
                    else None
                ),
                latest_profit_period=(
                    profitability[stock.id].period_end
                    if stock.id in profitability
                    else None
                ),
            )
            for stock in stocks
        }

    @staticmethod
    def _latest_profitability(
        session: Session,
        stock_ids: list[int],
        *,
        as_of_at: datetime,
    ) -> dict[int, LatestProfitability]:
        """Return the latest officially filed net income for each stock.

        Parent-owner profit is preferred to total profit, and consolidated
        statements are preferred when both scopes exist for the same period.
        """
        rows = session.execute(
            select(FinancialStatement, FinancialAccount)
            .join(
                FinancialAccount,
                FinancialAccount.statement_id == FinancialStatement.id,
            )
            .where(
                FinancialStatement.stock_id.in_(stock_ids),
                FinancialStatement.filing_date <= as_of_at.date(),
                FinancialStatement.collected_at <= as_of_at,
                FinancialStatement.data_state == DataState.AVAILABLE.value,
                FinancialAccount.canonical_metric_code.in_(
                    ("PARENT_OWNERS_NET_INCOME", "NET_INCOME")
                ),
            )
            .order_by(
                FinancialStatement.stock_id,
                FinancialStatement.business_year.desc(),
                case(
                    *(
                        (FinancialStatement.report_code == code, rank)
                        for code, rank in _REPORT_PERIOD_ORDER.items()
                    ),
                    else_=0,
                ).desc(),
                FinancialStatement.filing_date.desc(),
                case((FinancialStatement.fs_div == "CFS", 0), else_=1),
                case(
                    (
                        FinancialAccount.canonical_metric_code
                        == "PARENT_OWNERS_NET_INCOME",
                        0,
                    ),
                    else_=1,
                ),
                FinancialStatement.id.desc(),
            )
        ).all()
        result: dict[int, LatestProfitability] = {}
        for statement, account in rows:
            if statement.stock_id in result:
                continue
            amount = (
                account.current_cumulative_amount
                if account.current_cumulative_amount is not None
                else account.current_amount
                if account.current_amount is not None
                else account.amount
            )
            period_end = _statement_period_end(statement)
            if amount is None or period_end > as_of_at.date():
                continue
            result[statement.stock_id] = LatestProfitability(
                net_income=amount,
                period_end=period_end,
                receipt_no=statement.receipt_no,
            )
        return result

    def _score(
        self,
        stock: Stock,
        rows: list[PriceDaily],
        *,
        per: Decimal | None,
        pbr: Decimal | None,
        industry: str | None,
        per_values: list[Decimal],
        pbr_values: list[Decimal],
        liquidities: list[Decimal],
        volatilities: list[Decimal],
        returns_60: list[Decimal],
        as_of_at: datetime,
        latest_net_income: Decimal | None = None,
        latest_profit_period: date | None = None,
    ) -> MarketScreenScore:
        reported_loss = latest_net_income is not None and latest_net_income <= 0
        positive_per = (
            per if per is not None and per > 0 and not reported_loss else None
        )
        positive_pbr = pbr if pbr is not None and pbr > 0 else None
        liquidity = rows[-1].trading_value if rows else None
        volatility = self._volatility(rows)
        return_60 = self._period_return(rows, 60)
        normalized = {
            "SCREEN_PER": _rank_score(
                positive_per, per_values, lower_is_better=True
            ),
            "SCREEN_PBR": _rank_score(
                positive_pbr, pbr_values, lower_is_better=True
            ),
            "SCREEN_LIQUIDITY": _rank_score(
                liquidity, liquidities, lower_is_better=False
            ),
            "SCREEN_STABILITY": _rank_score(
                volatility, volatilities, lower_is_better=True
            ),
            "SCREEN_PULLBACK": _rank_score(
                return_60, returns_60, lower_is_better=True
            ),
        }
        weights = {
            "SCREEN_PER": Decimal(30),
            "SCREEN_PBR": Decimal(30),
            "SCREEN_LIQUIDITY": Decimal(15),
            "SCREEN_STABILITY": Decimal(10),
            "SCREEN_PULLBACK": Decimal(15),
        }
        raw_values = {
            "SCREEN_PER": per,
            "SCREEN_PBR": pbr,
            "SCREEN_LIQUIDITY": liquidity,
            "SCREEN_STABILITY": volatility,
            "SCREEN_PULLBACK": return_60,
        }
        explanations = {
            "SCREEN_PER": (
                f"최신 공시({latest_profit_period}) 순이익이 "
                f"{latest_net_income:,.0f}원으로 0 이하이므로, "
                f"시세 PER {per}배는 기간 불일치 가능성이 있어 "
                "저평가 점수에서 제외했습니다."
                if reported_loss and per is not None and per > 0
                else
                f"현재 PER {_display_decimal(positive_per)}배로 KOSPI 내 저평가 점수 "
                f"{normalized['SCREEN_PER']}/100입니다."
                if positive_per is not None
                else "공식 흑자 PER가 없어 이 항목은 보수적으로 0점 처리했습니다."
            ),
            "SCREEN_PBR": (
                f"현재 PBR {_display_decimal(positive_pbr)}배로 KOSPI 내 저평가 점수 "
                f"{normalized['SCREEN_PBR']}/100입니다."
                if positive_pbr is not None
                else "공식 양(+)의 PBR가 없어 이 항목은 보수적으로 0점 처리했습니다."
            ),
            "SCREEN_LIQUIDITY": (
                f"최근 거래대금 {liquidity:,.0f}원, KOSPI 유동성 점수 "
                f"{normalized['SCREEN_LIQUIDITY']}/100입니다."
                if liquidity is not None
                else "공식 거래대금이 없어 유동성 항목은 0점 처리했습니다."
            ),
            "SCREEN_STABILITY": (
                f"최근 60거래일 평균 일간 변동폭 {volatility * 100:.2f}%, "
                f"가격 안정성 점수 {normalized['SCREEN_STABILITY']}/100입니다."
                if volatility is not None
                else "가격 이력이 부족해 안정성 항목은 0점 처리했습니다."
            ),
            "SCREEN_PULLBACK": (
                f"최근 60거래일 수익률 {return_60 * 100:.2f}%, "
                f"가격 조정 매력 점수 {normalized['SCREEN_PULLBACK']}/100입니다."
                if return_60 is not None
                else "60거래일 가격 이력이 부족해 조정 매력 항목은 0점 처리했습니다."
            ),
        }
        components = tuple(
            ScoreComponent(
                score_name="MARKET_SCREEN",
                code=code,
                state=ComponentState.AVAILABLE,
                raw_value=raw_values[code],
                raw_text=(
                    None
                    if raw_values[code] is not None
                    else "공식 값 없음: 보수적으로 0점"
                ),
                normalized_value=normalized[code],
                weight=weight,
                contribution=quantize_score(
                    normalized[code] * weight / Decimal(100)
                ),
                explanation=explanations[code],
                source_kind="OFFICIAL_API_OR_SELF_CALCULATED",
            )
            for code, weight in weights.items()
        )
        investment = quantize_score(
            sum(
                (item.contribution or Decimal(0) for item in components),
                start=Decimal(0),
            )
        )
        entry = self._entry_score(rows)
        confidence = quantize_score(
            min(Decimal(len(rows)) / Decimal(61), Decimal(1)) * Decimal(50)
            + (Decimal(20) if positive_per is not None else Decimal(0))
            + (Decimal(20) if positive_pbr is not None else Decimal(0))
            + (Decimal(10) if industry is not None else Decimal(0))
        )
        payload = {
            "stock_id": stock.id,
            "symbol": stock.symbol,
            "as_of_at": as_of_at.isoformat(),
            "per": str(per) if per is not None else None,
            "pbr": str(pbr) if pbr is not None else None,
            "industry": industry,
            "latest_net_income": (
                str(latest_net_income) if latest_net_income is not None else None
            ),
            "latest_profit_period": (
                str(latest_profit_period)
                if latest_profit_period is not None
                else None
            ),
            "history": [
                (row.trade_date.isoformat(), str(row.close_price)) for row in rows
            ],
            "components": {
                code: str(value) for code, value in normalized.items()
            },
        }
        return MarketScreenScore(
            stock_id=stock.id,
            symbol=stock.symbol,
            investment_score=investment,
            individual_entry_score=entry,
            data_confidence=confidence,
            industry_code=industry or "UNCLASSIFIED",
            components=components,
            explanation=(
                f"KOSPI 보통주 전체와 비교한 저평가 매력은 {investment}/100, "
                f"개별 가격 기준 진입 시점은 {entry}/100입니다. "
                f"PER "
                f"{_display_decimal(positive_per) if positive_per is not None else '공식 값 없음'}, "
                f"PBR "
                f"{_display_decimal(positive_pbr) if positive_pbr is not None else '공식 값 없음'}, "
                f"60거래일 수익률 "
                f"{f'{return_60 * 100:.2f}%' if return_60 is not None else '확인 불가'}를 "
                "같은 기준일의 전체 종목과 비교했습니다."
            ),
            input_data_hash=sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        )

    @staticmethod
    def _period_return(rows: list[PriceDaily], days: int) -> Decimal | None:
        if len(rows) < days + 1:
            return None
        start = rows[-(days + 1)].close_price
        end = rows[-1].close_price
        if start is None or end is None:
            return None
        return _return(start, end)

    @staticmethod
    def _volatility(rows: list[PriceDaily]) -> Decimal | None:
        closes = [
            row.close_price
            for row in rows[-61:]
            if row.close_price is not None and row.close_price > 0
        ]
        if len(closes) < 20:
            return None
        changes = [
            abs(current / previous - Decimal(1))
            for previous, current in pairwise(closes)
        ]
        return sum(changes, start=Decimal(0)) / Decimal(len(changes))

    @staticmethod
    def _entry_score(rows: list[PriceDaily]) -> Decimal:
        closes = [
            row.close_price
            for row in rows
            if row.close_price is not None and row.close_price > 0
        ]
        if len(closes) < 20:
            return Decimal(0)
        current = closes[-1]
        return_20 = _return(closes[-20], current) or Decimal(0)
        pullback = (
            Decimal(90)
            if return_20 <= Decimal("-0.10")
            else Decimal(75)
            if return_20 <= Decimal("-0.05")
            else Decimal(55)
            if return_20 <= Decimal("0.05")
            else Decimal(35)
            if return_20 <= Decimal("0.15")
            else Decimal(20)
        )
        sma20 = sum(closes[-20:], start=Decimal(0)) / Decimal(20)
        sma60 = (
            sum(closes[-60:], start=Decimal(0)) / Decimal(60)
            if len(closes) >= 60
            else sma20
        )
        trend = (
            Decimal(70)
            if current >= sma60 and current <= sma20 * Decimal("1.05")
            else Decimal(55)
            if current >= sma60
            else Decimal(35)
        )
        return quantize_score((pullback + trend) / Decimal(2))
