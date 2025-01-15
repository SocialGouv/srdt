import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def start():
    uvicorn.run(
        "srdt_analysis.api.main:app",
        host=os.getenv("API_HOST", "localhost"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True,
    )


if __name__ == "__main__":
    start()
