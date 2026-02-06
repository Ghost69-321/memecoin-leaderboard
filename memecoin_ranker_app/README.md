# Memecoin Leaderboard (Streamlit)

A tiny Streamlit app that ranks memecoin candidates using LunarCrush v4 metrics (Galaxy Score™ / AltRank™).

## Local run

1. Create `.streamlit/secrets.toml`:
```toml
LUNARCRUSH_TOKEN = "paste-your-token"
# optional overrides
# LUNARCRUSH_BASE_URL = "https://lunarcrush.com/api4/public"
# HTTP_TIMEOUT_S = 30
# CACHE_TTL_S = 300
```
2. Install deps and run:
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repo.
2. Go to https://share.streamlit.io → Create app → select repo & `streamlit_app.py`.
3. In **Advanced settings → Secrets**, paste your `secrets.toml` content from above.
4. Deploy and you’ll get a public `*.streamlit.app` URL.

