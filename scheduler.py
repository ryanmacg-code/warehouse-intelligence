#!/usr/bin/env python3
"""
15-minute sync scheduler.

  py -3 scheduler.py

Runs an immediate sync on startup, then every 15 minutes.
Ctrl-C to stop.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

from sync_pvx import sync_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="Europe/London")


def _job():
    try:
        sync_all()
    except Exception as exc:
        log.error("scheduled sync failed: %s", exc)


def _shutdown(sig, frame):
    log.info("shutting down scheduler")
    scheduler.shutdown(wait=False)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("running initial sync before starting schedule …")
    _job()

    scheduler.add_job(_job, "interval", minutes=15, id="pvx_sync")
    log.info("scheduler started — next sync in 15 minutes (Ctrl-C to stop)")
    scheduler.start()
