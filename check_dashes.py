import subprocess
import sys

BAD = {"\u2013": "en dash", "\u2014": "em dash"}


def tracked_files():
    return subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()


def main():
    offenders = []
    for path in tracked_files():
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for character, name in BAD.items():
                if character in line:
                    offenders.append((path, line_number, name, line.strip()[:70]))

    if not offenders:
        print(f"clean: {len(tracked_files())} files, no em or en dashes")
        return 0

    print("found em or en dashes:")
    for path, line_number, name, preview in offenders:
        print(f"  {path}:{line_number}  {name}: {preview}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
