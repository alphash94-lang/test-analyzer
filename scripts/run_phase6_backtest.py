from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.logging_config import configure_logging, safe_exception_message
from app.models.backtest import BacktestDataset
from app.models.metadata import DataState
from app.services.backtest_service import BacktestService


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "날짜는 YYYY-MM-DD 형식이어야 합니다."
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "검증된 시점정보 입력으로 Phase 6 백테스트를 실행합니다. "
            "입력이 없으면 누락 상태만 저장하고 성과 숫자를 만들지 않습니다."
        )
    )
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument(
        "--input",
        type=Path,
        help="BacktestDataset 계약을 따르는 UTF-8 JSON 파일",
    )
    return parser


def _dataset(args: argparse.Namespace, *, maximum_bytes: int) -> BacktestDataset:
    input_path: Path | None = args.input
    if input_path is None:
        return BacktestDataset(
            start_date=args.start,
            end_date=args.end,
            folds=(),
            source_name="OPERATING_DATABASE_WITHOUT_POINT_IN_TIME_DATASET",
            known_survival_bias=(
                "시점별 유니버스와 상장폐지 포함 이력이 제공되지 않았습니다.",
            ),
        )
    if input_path.stat().st_size > maximum_bytes:
        raise ValueError("백테스트 입력 파일이 설정된 크기 제한을 초과했습니다.")
    dataset = BacktestDataset.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )
    if dataset.start_date != args.start or dataset.end_date != args.end:
        raise ValueError("명령행 기간과 입력 데이터 기간이 일치해야 합니다.")
    return dataset


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings=settings)
    service: BacktestService | None = None
    try:
        dataset = _dataset(
            args,
            maximum_bytes=settings.max_api_response_bytes,
        )
        service = BacktestService(settings)
        result = service.run(dataset)
        print(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if result.state == DataState.AVAILABLE:
            return 0
        if result.state == DataState.MISSING:
            return 2
        return 1
    except (
        OSError,
        SQLAlchemyError,
        ValidationError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "state": "FAILED",
                    "error_type": type(exc).__name__,
                    "message": safe_exception_message(exc, settings=settings),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
