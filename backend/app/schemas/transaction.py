from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import SUPPORTED_CURRENCIES, AssetClass, TransType

CST = ZoneInfo("Asia/Shanghai")


class TransactionCreate(BaseModel):
    asset_id: str = Field(min_length=1, max_length=32)
    trans_type: TransType
    trans_date: date
    price: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    notes: str | None = None

    @model_validator(mode="after")
    def check_writable(self) -> "TransactionCreate":
        # 业务时区统一 CST，避免部署在非东八区服务器时"今天"漂移
        if self.trans_date > datetime.now(CST).date():
            raise ValueError("交易日期不能晚于今天")
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"币种 {self.currency} 暂不支持（无汇率源），可选: "
                f"{', '.join(SUPPORTED_CURRENCIES)}"
            )
        return self


class TransactionOut(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


def validate_trans_asset_compat(trans: TransactionCreate, asset_class: str) -> None:
    """交易类型与资产类别的匹配校验（服务层调用，返回错误消息或 None）。"""
    cash_like = asset_class == AssetClass.CASH
    if trans.trans_type in (TransType.BUY, TransType.SELL) and cash_like:
        return "BUY/SELL 不能作用于 CASH 类资产（现金增减请使用 DEPOSIT/WITHDRAW/DIVIDEND）"
    if trans.trans_type in (TransType.DEPOSIT, TransType.WITHDRAW, TransType.DIVIDEND) and not cash_like:
        return "DEPOSIT/WITHDRAW/DIVIDEND 只能作用于 CASH 类资产（证券买卖请使用 BUY/SELL）"
    return None
