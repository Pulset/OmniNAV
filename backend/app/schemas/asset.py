from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import SUPPORTED_CURRENCIES, AssetClass, Market, ValuationType


class AssetBase(BaseModel):
    asset_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    asset_class: AssetClass
    market: Market
    currency: str = Field(default="CNY")
    valuation_type: ValuationType
    expected_apr: Decimal = Field(default=Decimal("0"), ge=0, le=1)

    @model_validator(mode="after")
    def check_valuation_compat(self) -> "AssetBase":
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"币种 {self.currency} 暂不支持（无汇率源），可选: "
                f"{', '.join(SUPPORTED_CURRENCIES)}"
            )
        cash_like = (self.asset_class == AssetClass.CASH)
        if cash_like and self.valuation_type != ValuationType.CASH:
            raise ValueError("CASH 类资产只能使用 CASH 估值模式")
        if (not cash_like) and self.valuation_type == ValuationType.CASH:
            raise ValueError("非 CASH 资产不能使用 CASH 估值模式")
        if self.valuation_type == ValuationType.FIXED_YIELD and self.expected_apr <= 0:
            raise ValueError("FIXED_YIELD 资产必须配置 expected_apr > 0")
        return self


class AssetCreate(AssetBase):
    @model_validator(mode="after")
    def normalize_market_symbol(self):
        """MARKET 标的裸代码自动补交易所后缀，无法识别的代码直接拒绝。

        行情路由（provider supports）按后缀识别标的，缺后缀会导致行情
        全部缺失且估值静默回退成本价。已带后缀的原样放行（仅统一后缀大小写）。
        """
        if self.valuation_type != ValuationType.MARKET:
            return self
        code = self.asset_id.strip()
        upper = code.upper()
        if upper.endswith((".SH", ".SZ", ".HK", ".US")):
            self.asset_id = code[:-3] + upper[-3:]
            return self
        if self.market == Market.CN and len(code) == 6 and code.isdigit():
            if code[0] in "56":
                self.asset_id = f"{code}.SH"
            elif code[0] in "013":
                self.asset_id = f"{code}.SZ"
            else:
                raise ValueError(
                    f"暂不支持该 A 股代码段（{code}），请带交易所后缀录入（如 510310.SH）"
                )
        elif self.market == Market.HK and code.isdigit():
            self.asset_id = f"{code.zfill(5)}.HK"
        elif self.market == Market.US and any(c.isalpha() for c in upper):
            self.asset_id = f"{upper}.US"
        else:
            raise ValueError(
                "无法识别的 MARKET 标的代码，请带交易所后缀录入"
                "（如 510310.SH / 00700.HK / TSLA.US）"
            )
        return self


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    expected_apr: Decimal | None = Field(default=None, ge=0, le=1)


class AssetOut(AssetBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
