"""Download a small, labelled Snapshot Karoo subset from LILA BC.

What it does
- Fetches the Snapshot Karoo S1 COCO Camera Traps metadata and LILA's precomputed
  MegaDetector v5a results (both small zips, cached in the output folder).
- Picks a few camera locations and samples **whole sequences** from each, mixing
  animal and empty sequences (Karoo is ~83% empty; we oversample animals a bit so
  the demo has something to review).
- Downloads the images, preserving LILA's relative paths.
- Writes `manifest.csv` (file, camera, site, timestamp, ground_truth, seq_id) and
  `md_results_subset.json` (the MegaDetector results for just these files, in the
  standard batch-output format) for `scripts/import_md_results.py`.

Only uses the standard library so it runs on the host without the backend venv.

    python scripts/download_lila_subset.py --n-images 500
"""

import argparse
import csv
import io
import json
import random
import sys
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GCS = "https://storage.googleapis.com/public-datasets-lila"
METADATA_URL = f"{GCS}/snapshot-safari/KAR/SnapshotKaroo_S1_v1.0.json.zip"
MD_RESULTS_URL = (
    "https://lila.science/public/lila-md-results/snapshot-safari_KAR_mdv5a.0.0_results.json.zip"
)
IMAGE_BASE_URL = f"{GCS}/snapshot-safari/KAR/KAR_public/"
SITE_NAME = "Snapshot Karoo"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "lila"


def fetch_zipped_json(url: str, cache_dir: Path) -> dict:
    cache = cache_dir / Path(url).name
    if not cache.exists():
        print(f"downloading {url}")
        urllib.request.urlretrieve(url, cache)
    with zipfile.ZipFile(cache) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".json"))
        # The Karoo metadata contains bare NaN values, which json.load accepts.
        return json.load(io.TextIOWrapper(zf.open(name), encoding="utf-8"))


def sequence_labels(metadata: dict) -> dict[str, str]:
    """seq_id -> 'animal' | 'person' | 'empty'.

    Snapshot Safari labels are only reliable at the sequence level, so every image in a
    sequence gets the sequence's label.
    """
    cat_names = {c["id"]: c["name"] for c in metadata["categories"]}
    labels: dict[str, str] = {}
    for ann in metadata["annotations"]:
        name = cat_names[ann["category_id"]]
        label = "empty" if name == "empty" else "person" if name == "human" else "animal"
        current = labels.get(ann["seq_id"])
        # Any non-empty annotation makes the sequence non-empty.
        if current is None or current == "empty":
            labels[ann["seq_id"]] = label
    return labels


def choose_images(
    metadata: dict,
    available: set[str],
    n_images: int,
    n_locations: int,
    animal_fraction: float,
    seed: int,
) -> list[dict]:
    """Sample whole sequences from the busiest locations until ~n_images are chosen."""
    labels = sequence_labels(metadata)
    seqs: dict[str, list[dict]] = defaultdict(list)
    for img in metadata["images"]:
        if img["file_name"] in available and not img.get("corrupt"):
            seqs[img["seq_id"]].append(img)

    by_location: dict[str, list[str]] = defaultdict(list)
    for seq_id, imgs in seqs.items():
        by_location[imgs[0]["location"]].append(seq_id)

    rng = random.Random(seed)

    # Busiest locations by number of animal sequences, so every camera has some animals.
    def animal_seqs(loc: str) -> int:
        return sum(labels.get(s) == "animal" for s in by_location[loc])

    locations = sorted(by_location, key=animal_seqs, reverse=True)[:n_locations]
    per_location = n_images // len(locations)

    chosen: list[dict] = []
    for loc in locations:
        animal = [s for s in by_location[loc] if labels.get(s) == "animal"]
        empty = [s for s in by_location[loc] if labels.get(s) == "empty"]
        rng.shuffle(animal)
        rng.shuffle(empty)
        picked: list[dict] = []
        target_animal = int(per_location * animal_fraction)
        for pool, target in ((animal, target_animal), (empty, per_location)):
            for seq_id in pool:
                if len(picked) >= target:
                    break
                picked.extend(seqs[seq_id])
        for img in picked:
            img["_label"] = labels.get(img["seq_id"], "empty")
        chosen.extend(picked)
    return chosen


def download_one(file_name: str, images_dir: Path) -> bool:
    dest = images_dir / file_name
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(IMAGE_BASE_URL + file_name, timeout=60) as r:
            dest.write_bytes(r.read())
        return True
    except OSError as e:
        print(f"  failed {file_name}: {e}", file=sys.stderr)
        return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--n-images", type=int, default=500)
    p.add_argument("--n-locations", type=int, default=5)
    p.add_argument("--animal-fraction", type=float, default=0.4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    images_dir = args.out / "images"
    metadata = fetch_zipped_json(METADATA_URL, args.out)
    md_results = fetch_zipped_json(MD_RESULTS_URL, args.out)
    md_by_file = {e["file"]: e for e in md_results["images"]}

    chosen = choose_images(
        metadata, set(md_by_file), args.n_images, args.n_locations, args.animal_fraction, args.seed
    )
    print(f"downloading {len(chosen)} images to {images_dir}")
    with ThreadPoolExecutor(args.workers) as pool:
        ok = list(pool.map(lambda img: download_one(img["file_name"], images_dir), chosen))
    chosen = [img for img, good in zip(chosen, ok, strict=True) if good]

    with (args.out / "manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "camera", "site", "timestamp", "ground_truth", "seq_id"])
        for img in chosen:
            w.writerow(
                [
                    img["file_name"],
                    img["location"],
                    SITE_NAME,
                    img.get("datetime", ""),
                    img["_label"],
                    img["seq_id"],
                ]
            )

    subset = {**md_results, "images": [md_by_file[img["file_name"]] for img in chosen]}
    (args.out / "md_results_subset.json").write_text(json.dumps(subset))

    counts: dict[str, int] = defaultdict(int)
    for img in chosen:
        counts[img["_label"]] += 1
    print(f"done: {len(chosen)} images, labels {dict(counts)}")
    print(f"manifest: {args.out / 'manifest.csv'}")
    print(f"MegaDetector results subset: {args.out / 'md_results_subset.json'}")


if __name__ == "__main__":
    main()
