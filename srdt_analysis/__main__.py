from dotenv import load_dotenv
from .data import get_data

load_dotenv()


def main():
    result = get_data()
    print(result[1][0]["text"])


if __name__ == "__main__":
    main()
