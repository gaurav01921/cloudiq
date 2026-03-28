import argparse

import uvicorn

from app.db.session import SessionLocal
from app.services.cost_intelligence import CostIntelligenceService


def cmd_runserver(args: argparse.Namespace) -> None:
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


def cmd_sync(_: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        result = CostIntelligenceService(db).sync()
        print(result.model_dump())
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cloud Cost Intelligence CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    runserver = subparsers.add_parser("runserver", help="Run the web application")
    runserver.add_argument("--host", default="127.0.0.1")
    runserver.add_argument("--port", type=int, default=8000)
    runserver.add_argument("--reload", action="store_true")
    runserver.set_defaults(func=cmd_runserver)

    sync = subparsers.add_parser("sync", help="Run one sync cycle")
    sync.set_defaults(func=cmd_sync)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
