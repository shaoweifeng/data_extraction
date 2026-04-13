import os

base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
api_key = os.getenv("DEEPSEEK_API_KEY", "sk-f9652b9622494e9cbcd9c43a7d25eff7")
max_workers = int(os.getenv("SCREENING_MAX_WORKERS", "16"))
