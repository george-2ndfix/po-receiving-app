# Gunicorn config for Render
import os

timeout = 120
workers = 2
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
