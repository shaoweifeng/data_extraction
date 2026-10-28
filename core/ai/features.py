"""Single mapping for shared AI task, billing and concurrency boundaries."""
AI_TASK_FEATURES = {'ai_screen': 'ai_screen', 'qa_eval': 'qa_eval', 'rescreen_ai': 'ai_rescreen'}
AI_TASK_TYPES = frozenset(AI_TASK_FEATURES)
AI_FEATURE_LABELS = {'ai_screen': 'AI初筛', 'qa_eval': 'AI质量评价', 'ai_rescreen': 'AI全文复筛'}
