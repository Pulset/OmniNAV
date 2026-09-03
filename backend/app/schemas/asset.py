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
    pass


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    expected_apr: Decimal | None = Field(default=None, ge=0, le=1)


class AssetOut(AssetBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
