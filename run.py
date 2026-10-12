import os
import sys

from fetch import OpenFdaError, build_search, count_reports


def main():
    if len(sys.argv) < 2:
        print("usage: python run.py DRUG [REACTION]")
        return 1

    drug = sys.argv[1]
    reaction = sys.argv[2] if len(sys.argv) > 2 else None
    api_key = os.environ.get("OPENFDA_API_KEY")

    if reaction:
        print(f"reports with {drug} and {reaction}:")
    else:
        print(f"reports with {drug}:")

    try:
        total = count_reports(build_search(drug, reaction), api_key=api_key)
    except OpenFdaError as exc:
        print(f"failed: {exc}")
        return 1

    print(f"  {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
