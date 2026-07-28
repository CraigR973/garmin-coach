"""Interactively create a Garmin garth token blob for deployment secrets."""

from __future__ import annotations

import getpass
import os
from argparse import ArgumentParser
from pathlib import Path

from secure_artifacts import write_secret_file
from src.services.garmin_sync import GarminConnectClient, GarminCredentials


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-output",
        type=Path,
        help="Optional path to write GARMIN_TOKENSTORE and GARMIN_TOKENSTORE_B64 lines.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help=(
            "Print GARMIN_TOKENSTORE_B64 to stdout. Use only in a private shell; "
            "stdout may be captured by terminal, CI, or remote-session logs."
        ),
    )
    args = parser.parse_args()
    if not args.env_output and not args.stdout:
        parser.error("choose --env-output FILE for a 0600 file, or explicit --stdout")

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
        write_secret_file(
            args.env_output,
            f"GARMIN_TOKENSTORE={tokenstore}\nGARMIN_TOKENSTORE_B64={token_blob}\n",
        )
        print(f"GARMIN_TOKENSTORE_B64 written to {args.env_output} (0600)")
    else:
        print(f"GARMIN_TOKENSTORE_B64={token_blob}")


if __name__ == "__main__":
    main()
