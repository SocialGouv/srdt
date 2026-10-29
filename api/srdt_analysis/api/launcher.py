import uvicorn

from srdt_analysis.core.constants import API_TIMEOUT
from srdt_analysis.core.settings import get_settings


def start():
    settings = get_settings()
    uvicorn.run(
        "srdt_analysis.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        timeout_keep_alive=API_TIMEOUT,
    )


if __name__ == "__main__":
    start()
