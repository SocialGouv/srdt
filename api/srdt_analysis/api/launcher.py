import os

import uvicorn
from dotenv import load_dotenv

from srdt_analysis.constants import API_TIMEOUT

load_dotenv()


def start():
    uvicorn.run(
        "srdt_analysis.api.main:app",
        host=os.getenv("API_HOST", "localhost"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True,
        timeout_keep_alive=API_TIMEOUT,
    )


if __name__ == "__main__":
    start()
