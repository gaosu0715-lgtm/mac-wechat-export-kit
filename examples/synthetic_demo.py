"""Generate an offline sample from fabricated SQLite data, without SQLCipher."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

# Reuse only the project's synthetic fixture generator, never a real DB adapter.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from fixtures import CONTACT, SELF, USERNAME, PlainFixtureDB, make_fixtures
from mac_wechat_export_kit.exporter import export_conversation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="wechat-kit-synthetic-") as temporary:
        root = make_fixtures(Path(temporary).resolve() / "fabricated")
        summary = export_conversation(lambda name: PlainFixtureDB(root / name), contact_name=CONTACT,
                                      expected_username=USERNAME, self_username=SELF, output=args.output, page_size=2)
    print(json.dumps({"synthetic_only": True, **summary}))


if __name__ == "__main__":
    main()
