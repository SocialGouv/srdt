import json
import os
from datetime import datetime

from dotenv import load_dotenv

from srdt_analysis.clients.judilibre_client import JudilibreClient
from srdt_analysis.core.logger import Logger

load_dotenv()

logger = Logger("Judilibre download")

OUTPUT_DIR = "judilibre"
START_YEAR = 2000


def start():
    logger.info("Read decisions from API")

    client = JudilibreClient()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    end_year = datetime.now().year
    for year in range(START_YEAR, end_year + 1):
        date_start = f"{year}-01-01"
        date_end = f"{year}-12-31"

        logger.info(f"Fetching decisions for {year}")
        decisions = client.get_decisions_between_dates(date_start, date_end)

        output_path = os.path.join(OUTPUT_DIR, f"{year}.json")
        with open(output_path, "w") as f:
            json.dump(decisions, f)

        logger.info(f"Saved {len(decisions)} decisions to {output_path}")


if __name__ == "__main__":
    start()
