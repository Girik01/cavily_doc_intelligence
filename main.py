"""Start the app:   uv run main.py     then open http://127.0.0.1:8002
(HOST and PORT can be set as environment variables.)"""
import os

import uvicorn

from docint.server import app

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8002")))
