#!/usr/bin/env python3
"""Launch the Sniper Control GUI (FastAPI + responsive dashboard)."""
import uvicorn

if __name__ == "__main__":
    print("Starting Sniper Control GUI on http://0.0.0.0:8000")
    print("Open on PC or phone browser. Add to home screen for PWA.")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=False)
