from dotenv import load_dotenv
from srdt_analysis.llm import get_llm
from srdt_analysis.exploit_data import exploit_data


load_dotenv()


def main():
    # exploit_data()
    get_llm()


if __name__ == "__main__":
    main()
