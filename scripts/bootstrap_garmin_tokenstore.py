"""Interactively create a Garmin garth token blob for deployment secrets."""

from __future__ import annotations

import getpass
import os
from argparse import ArgumentParser
from pathlib import Path

from src.services.garmin_sync import GarminConnectClient, GarminCredentials


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-output",
        type=Path,
        help="Optional path to write GARMIN_TOKENSTORE and GARMIN_TOKENSTORE_B64 lines.",
    )
    args = parser.parse_args()

    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    tokenstore = Path(
        os.path.expanduser(os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect"))
    )

    client = GarminConnectClient(
        GarminCredentials(
            email=email,
            password=password,
            tokenstore=tokenstore,
        )
    )
    garmin = client.login()
    token_blob = garmin.client.dumps()

    print(f"GARMIN_TOKENSTORE={tokenstore}")
    if args.env_output:
        args.env_output.write_text(
            f"GARMIN_TOKENSTORE={tokenstore}\nGARMIN_TOKENSTORE_B64={token_blob}\n",
            encoding="utf-8",
        )
        print(f"GARMIN_TOKENSTORE_B64 written to {args.env_output}")
    else:
        print(f"GARMIN_TOKENSTORE_B64={token_blob}")


if __name__ == "__main__":
    main()
