from enum import StrEnum


# 当前汇率源（Frankfurter）实际抓取的币种 + 本币；资产/流水币种必须在此集合内，
# 否则清算时 fx_to_cny 抛 MissingPriceError，该用户每日清算永久失败
SUPPORTED_CURRENCIES = ("CNY", "USD", "HKD")


class AssetClass(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    WEALTH = "WEALTH"
    CASH = "CASH"


class Market(StrEnum):
    CN = "CN"
    HK = "HK"
    US = "US"
    GLOBAL = "GLOBAL"


class ValuationType(StrEnum):
    MARKET = "MARKET"
    FIXED_YIELD = "FIXED_YIELD"
    MANUAL_NAV = "MANUAL_NAV"
    CASH = "CASH"


class TransType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    DIVIDEND = "DIVIDEND"


class RuleType(StrEnum):
    DAILY_PCT_CHANGE = "DAILY_PCT_CHANGE"
    DAILY_GAIN = "DAILY_GAIN"
    DAILY_LOSS = "DAILY_LOSS"
    DRAWDOWN = "DRAWDOWN"


# 按资产评估的单日涨跌幅类规则（PCT_CHANGE 为 ±对称，GAIN/LOSS 为单方向）
DAILY_RULE_TYPES = (
    RuleType.DAILY_PCT_CHANGE,
    RuleType.DAILY_GAIN,
    RuleType.DAILY_LOSS,
)


# 组合级外部现金流符号：买入/入金为正（外部资金进入），卖出/出金为负；
# 分红属于组合内部收益，不计入外部现金流（不改变份额）。
FLOW_SIGN: dict[str, int] = {
    "DEPOSIT": 1,
    "WITHDRAW": -1,
    "BUY": 1,
    "SELL": -1,
    "DIVIDEND": 0,
}
