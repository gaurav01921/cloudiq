import argparse
import time

import uvicorn

from app.db.session import SessionLocal
from app.services.batch_service import BatchService
from app.services.cost_intelligence import CostIntelligenceService
from app.tasks.scheduler import scheduler_service


def cmd_runserver(args: argparse.Namespace) -> None:
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


def cmd_sync(_: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        result = CostIntelligenceService(db).sync()
        print(result.model_dump())
    finally:
        db.close()


def cmd_worker(args: argparse.Namespace) -> None:
    while True:
        db = SessionLocal()
        try:
            result = BatchService(db).run_sync_cycle()
            print(result)
        finally:
            db.close()
        if args.once:
            break
        time.sleep(args.interval)


def cmd_scheduler(_: argparse.Namespace) -> None:
    scheduler_service.start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler_service.stop()


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

    worker = subparsers.add_parser("worker", help="Run the batch worker loop")
    worker.add_argument("--interval", type=int, default=300)
    worker.add_argument("--once", action="store_true")
    worker.set_defaults(func=cmd_worker)

    scheduler = subparsers.add_parser("scheduler", help="Run the scheduler service")
    scheduler.set_defaults(func=cmd_scheduler)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
