from enum import Enum


class LossReason(str, Enum):
    BUDGET_CONSTRAINT = "budget_constraint"
    CHOSE_COMPETITOR = "chose_competitor"
    TIMING = "timing"
    NO_CURRENT_NEED = "no_current_need"
    NO_RESPONSE = "no_response"
    OTHER = "other"
