"""初筛最终决定的稳定应用服务端口。"""

from core.screening.domain.decisions import final_decision, is_included


class ScreeningDecisionService:
    """供初筛导出和质量评价导入共同使用的最终决定规则。"""

    @staticmethod
    def resolve(result, manual_review=None):
        return final_decision(result, manual_review)

    @staticmethod
    def is_included(result, manual_review=None):
        return is_included(result, manual_review)
