"""Start the local two-board procurement demo server."""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer

from bidfactory.mocksite import MockBidHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BidCrawler Factory's local mock procurement site")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockBidHandler)
    print(f"Mock procurement site: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
