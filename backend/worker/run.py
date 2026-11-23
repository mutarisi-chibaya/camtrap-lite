"""Worker process. Milestone 1 stub: idles so docker-compose has a running worker.

Milestone 2 replaces this with the real loop (load MegaDetector once, pull detect jobs
from the queue, save detections, run post-processing).
"""

import logging
import time

log = logging.getLogger("worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.info("worker started (stub: no job processing yet)")
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
