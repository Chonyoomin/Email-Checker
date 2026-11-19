import sys

import uvicorn
from pydantic import ValidationError

from .app import create_app
from .config import Settings


def main():
    try:
        settings = Settings()
    except ValidationError:
        print(
            "Invalid configuration. Check EMAIL_CHECK_* settings and .env.example.", file=sys.stderr
        )
        raise SystemExit(2) from None
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
