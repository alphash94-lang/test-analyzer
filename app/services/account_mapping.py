from __future__ import annotations

_XBRL_ACCOUNT_MAP = {
    "ifrs-full_Revenue": "REVENUE",
    "ifrs-full_OperatingProfitLoss": "OPERATING_PROFIT",
    "dart_OperatingIncomeLoss": "OPERATING_PROFIT",
    "ifrs-full_ProfitLoss": "NET_INCOME",
    "ifrs-full_ProfitLossAttributableToOwnersOfParent": ("PARENT_OWNERS_NET_INCOME"),
    "ifrs-full_Assets": "ASSETS",
    "ifrs-full_Liabilities": "LIABILITIES",
    "ifrs-full_Equity": "EQUITY",
    "ifrs-full_EquityAttributableToOwnersOfParent": "PARENT_OWNERS_EQUITY",
    "ifrs-full_CashAndCashEquivalents": "CASH_AND_CASH_EQUIVALENTS",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": ("OPERATING_CASH_FLOW"),
    "ifrs-full_PurchaseOfPropertyPlantAndEquipment": "CAPEX_TANGIBLE",
    "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": (
        "CAPEX_TANGIBLE"
    ),
    "ifrs-full_PurchaseOfIntangibleAssets": "CAPEX_INTANGIBLE",
    "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": (
        "CAPEX_INTANGIBLE"
    ),
    "ifrs-full_FinanceCosts": "FINANCE_COSTS",
}


def map_xbrl_account(
    account_id: str | None,
    account_detail: str | None = None,
) -> str | None:
    if account_id is None or (account_detail and account_detail.strip()):
        return None
    return _XBRL_ACCOUNT_MAP.get(account_id.strip())
