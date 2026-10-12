import pathlib
import sys
import urllib.request

import pyreadr

# the reference set is only published as an .rda, which needs R to read. pyreadr wraps
# librdata so it can be converted without it
URL = "https://raw.githubusercontent.com/OHDSI/MethodEvaluation/main/data/euadrReferenceSet.rda"
KEEP = ["exposureName", "outcomeName", "groundTruth", "indicationName", "comparatorName"]


def main():
    folder = pathlib.Path(__file__).with_name("fixtures")
    folder.mkdir(exist_ok=True)
    local = folder / "euadrReferenceSet.rda"

    if not local.exists():
        print(f"downloading {URL}")
        local.write_bytes(urllib.request.urlopen(URL, timeout=60).read())
    print(f"{local.name}: {local.stat().st_size:,} bytes")

    result = pyreadr.read_r(str(local))
    if not result:
        print("pyreadr returned nothing")
        return 1
    name, frame = next(iter(result.items()))
    print(f"table {name!r}: {frame.shape[0]} rows, {frame.shape[1]} columns")
    print("columns:", list(frame.columns))

    missing = [column for column in KEEP if column not in frame.columns]
    if missing:
        print("missing expected columns:", missing)
        return 1

    out = frame[KEEP].copy()
    print()
    print("groundTruth counts:")
    print(out["groundTruth"].value_counts().to_string())
    print()
    print("distinct outcomes:", out["outcomeName"].nunique())
    print("distinct exposures:", out["exposureName"].nunique())

    target = folder / "euadr_reference_set.csv"
    out.to_csv(target, index=False)
    print()
    print(f"wrote {target.relative_to(pathlib.Path(__file__).parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
