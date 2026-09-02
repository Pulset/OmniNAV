from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import RuleType


class AlertRuleBase(BaseModel):
    asset_id: str | None = Field(default=None, max_length=32)
    rule_type: RuleType
    threshold: Decimal = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def check_compat(self) -> "AlertRuleBase":
        if self.rule_type == RuleType.DAILY_PCT_CHANGE and not self.asset_id:
            raise ValueError("DAILY_PCT_CHANGE 规则必须指定 asset_id")
        if self.rule_type == RuleType.DRAWDOWN and self.asset_id:
            raise ValueError("DRAWDOWN 规则作用于组合整体，不能指定 asset_id")
        return self


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    threshold: Decimal | None = Field(default=None, gt=0, lt=1)
    is_active: bool | None = None


class AlertRuleOut(AlertRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
