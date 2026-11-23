"""Import a MegaDetector batch-output JSON (from Colab or LILA) into the app.

    python scripts/import_md_results.py --results results.json --camera 3
    python scripts/import_md_results.py --results data/lila/md_results_subset.json   # all cameras

Matches entries to Image rows by filename / relative path, saves detections, marks the
images processed, then runs event grouping, the static finder and triage - the same
post-processing the worker does.
"""

import argparse
import json
import logging
from pathlib import Path

from app.db import SessionLocal
from app.services.md_import import import_md_results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--results", type=Path, required=True, help="MegaDetector batch output JSON")
    p.add_argument("--camera", type=int, help="only match images of this camera id")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    results = json.loads(args.results.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        report = import_md_results(db, results, args.camera)

    print(f"matched images:      {report.matched}")
    print(f"failed in results:   {report.failed}")
    print(f"detections saved:    {report.detections}")
    print(f"not found in DB:     {len(report.missing_from_db)}")
    for f in report.missing_from_db[:10]:
        print(f"    {f}")
    print(f"cameras finalized:   {report.finalized_cameras}")


if __name__ == "__main__":
    main()
