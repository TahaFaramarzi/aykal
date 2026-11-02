ACTION_RULES = {
    "engagement_drop": "message",
    "low_activity": "like",
    }
    
class RetargetingService:
    """انتخاب اکشن مدنظر برای انجام
    """
    def choose_action(self, candidate : dict) -> dict:
        action = ACTION_RULES.get(candidate["reason"], "no_action")
        result = {"inactive_id" : candidate["inactive_id"], "user_id" : candidate["user_id"], "action" : action}
        return result