#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll an HTTP endpoint until it responds.")
    parser.add_argument("url", help="HTTP URL to poll")
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Maximum seconds to wait before failing.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between attempts.",
    )
    parser.add_argument(
        "--expect-status",
        type=int,
        default=200,
        help="HTTP status code required for success.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    deadline = time.monotonic() + args.timeout
    last_error = "no response received"

    while time.monotonic() < deadline:
        try:
            request = Request(args.url, headers={"User-Agent": "cancerstudio-wait-for-http/1.0"})
            with urlopen(request, timeout=args.interval + 5) as response:
                if response.status == args.expect_status:
                    print(f"{args.url} responded with {response.status}")
                    return 0
                last_error = f"unexpected status {response.status}"
        except HTTPError as error:
            last_error = f"HTTP {error.code}"
        except URLError as error:
            last_error = str(error.reason)

        time.sleep(args.interval)

    print(
        f"Timed out waiting for {args.url} to return {args.expect_status}: {last_error}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
