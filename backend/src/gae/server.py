"""Container entry point: query strings must never reach access or HTTP client logs."""

import logging
import os

import uvicorn


def configure_logging() -> None:
    logging.getLogger("uvicorn.access").disabled = True
    # httpx INFO includes upstream URLs (including EPC postcodes).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    uvicorn.run(
        "gae.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
