# Project: CamTrap Lite — AI camera-trap processing pipeline

## Why this project exists

This is a portfolio project for a job application to WildEye (wildeyeconservation.org), whose main product, TrapTagger, is a cloud platform that processes camera-trap images with AI. The role asks for **full-stack Python + React + cloud (AWS)**, with machine learning, web apps and big data as bonuses.

The goal is a **small, working, deployed** version of the core TrapTagger workflow that a reviewer can understand in two minutes:

1. Upload camera-trap images
2. Run **MegaDetector** to find animals / people / vehicles and filter out empty images
3. Group images into **trigger events** (bursts from the same camera)
4. Flag **static false detections** (rocks, branches that trigger the detector in the same spot over and over)
5. Let a human **review only the uncertain cases** in a fast, keyboard-driven React interface
6. **Export** results as CSV and COCO JSON
7. Report real numbers (how much was auto-handled, accuracy against ground-truth labels, review speed)

**Priorities, in order:** working end-to-end > clean code and tests > README + demo video > polish > extra features. Keep it small. Do not over-engineer.

**This project is NOT deployed to the cloud.** It runs locally with docker-compose. Cloud readiness is shown through clean storage/queue interfaces and a written AWS design in the README, not by actually deploying.

## Hard scope limits (do NOT do these)

- No cloud deployment and no AWS SDK code (boto3 etc.).
- Do not train or fine-tune any model. Use MegaDetector as-is.
- No species classification and no individual identification. Detection plus human review only.
- No complex auth. A single hard-coded demo user or one API key from an env var is fine.
- No Kubernetes, Terraform, microservices or message brokers beyond what is described below.
- Do not add dependencies without a clear reason.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- **Database:** Postgres in docker-compose; SQLite allowed for running tests. The code must work with both through `DATABASE_URL`.
- **ML:** the `megadetector` pip package (MegaDetector v5a). **Check the package's current README/API before writing the integration code. Do not guess function names.** Wrap it behind our own interface (see `detector.py`) so the rest of the code never imports it directly.
- **Worker:** a separate Python process that pulls jobs from a queue and runs detection.
- **Queue:** a small abstract interface (`base.py`) with one implementation, `DbQueue` (polls a `jobs` table using `SELECT ... FOR UPDATE SKIP LOCKED` on Postgres so several workers could run safely). Do not implement SQS; the interface exists so it could be added.
- **Storage:** a small abstract interface with one implementation, `LocalStorage` (a folder on disk, mounted as a Docker volume). Do not implement S3; same reason.
- **Frontend:** React + TypeScript + Vite. Plain CSS or CSS modules; no heavy UI framework needed. Use TanStack Query for data fetching.
- **Tests:** pytest for the backend, Vitest for any non-trivial frontend logic.
- **Packaging:** `docker-compose.yml` that runs api + worker + postgres + frontend locally with one command.

## Verified external API facts (checked 2026-11, update if they change)

- **megadetector 10.0.x**: `megadetector.detection.run_detector.load_detector("MDV5A", force_cpu=...)` auto-downloads the weights (currently `md_v5a.0.1.pt`, ~280 MB) to `<tempdir>/megadetector_models` and returns a `PTDetector`; `detector.generate_detections_one_image(pil_img, image_id, detection_threshold)` returns `{file, detections: [{category: "1"|"2"|"3", conf, bbox: [x,y,w,h] normalised]}, failure}`. Load images with `megadetector.visualization.visualization_utils.load_image` (handles EXIF rotation). Batch CLI: `python -m megadetector.detection.run_detector_batch MDV5A <dir> <out.json> --recursive --output_relative_filenames`.
- **CPU speed measured on the dev laptop: ~6 s/image** (slower than the 1–3 s estimate), so use the precomputed-results path for the full subset and the worker for small batches.
- **LILA Snapshot Karoo S1**: metadata `https://storage.googleapis.com/public-datasets-lila/snapshot-safari/KAR/SnapshotKaroo_S1_v1.0.json.zip` (COCO Camera Traps; `images[].file_name/location/seq_id/datetime`, sequence-level annotations, category `empty`, `human`). Images: `https://storage.googleapis.com/public-datasets-lila/snapshot-safari/KAR/KAR_public/<file_name>`. Precomputed MDv5a results: `https://lila.science/public/lila-md-results/snapshot-safari_KAR_mdv5a.0.0_results.json.zip`, paths relative to `KAR_public/`. Karoo JPEGs have EXIF `DateTimeOriginal`.
- `scripts/import_md_results.py --camera` is optional: without it, entries are matched against all cameras (the LILA subset spans 5 cameras). `scripts/ingest_lila_subset.py` loads the downloaded subset (one Camera per LILA location, sets `ground_truth_label`).

## Repository layout

```
camtrap-lite/
  CLAUDE.md
  README.md
  docker-compose.yml
  .env.example
  backend/
    pyproject.toml
    app/
      main.py            # FastAPI app, routers
      config.py          # settings from env vars
      db.py              # engine, session
      models.py          # SQLAlchemy models
      schemas.py         # Pydantic schemas
      routers/           # cameras.py, images.py, review.py, exports.py, stats.py
      services/
        ingest.py        # register uploaded files, read EXIF timestamps
        events.py        # group images into trigger events
        static.py        # static false-detection finder
        triage.py        # decide auto-accept / auto-empty / needs-review
        export_csv.py
        export_coco.py
      storage/           # base.py, local.py
      queue/             # base.py, db_queue.py
      ml/detector.py     # wraps MegaDetector; returns our own Detection dataclass
    worker/run.py        # worker loop
    scripts/
      download_lila_subset.py
      evaluate.py
    alembic/
    tests/
  frontend/
    src/
      api/               # typed API client
      pages/             # Dashboard, Upload, Review, StaticCheck, Export
      components/        # ImageWithBoxes, EventStrip, KeyboardHelp, ProgressBar
```

## Data model

- **Camera**: id, name, site_name, latitude (nullable), longitude (nullable)
- **Image**: id, camera_id, original_filename, storage_key, width, height, timestamp (nullable), timestamp_source (`exif` | `filename` | `ocr` | `missing`; `ocr` added with the stretch goal), event_id (nullable), status (`uploaded` | `queued` | `processed` | `failed`), ground_truth_label (nullable; only set for LILA evaluation data)
- **Detection**: id, image_id, category (`animal` | `person` | `vehicle`), confidence (float), bbox_x, bbox_y, bbox_w, bbox_h (**normalised 0–1, top-left x/y plus width/height**, the same convention as MegaDetector), is_static_candidate (bool), static_cluster_id (nullable)
- **Event**: id, camera_id, start_time, end_time, triage_status (`auto_animal` | `auto_empty` | `auto_person` | `auto_vehicle` | `needs_review` | `reviewed`; person/vehicle values added in M3, stored as VARCHAR so no migration was needed), max_animal_conf
- **Annotation**: id, event_id, label (`animal` | `empty` | `person` | `vehicle`), source (`ai` | `human`), created_at, review_duration_ms (nullable)
- **StaticCluster**: id, camera_id, bbox (normalised), occurrence_count, occurrence_fraction, status (`pending` | `confirmed_static` | `rejected`)
- **CameraMask** (stretch goal, migration 0002): id, camera_id, name, polygon (JSON list of normalised [x, y] points), created_at. A detection whose box centre lies inside a mask is ignored by triage, the static finder and exports.
- **Job**: id, type (`detect`), payload (JSON), status (`pending` | `running` | `done` | `failed`), attempts, error, created_at, updated_at

## Core logic (write unit tests for every rule here)

### Event grouping (`services/events.py`)
- Per camera, sort images by timestamp.
- Start a new event when the gap to the previous image is greater than `EVENT_GAP_SECONDS` (default 60).
- Images with no timestamp each become their own single-image event, flagged in the UI.

### Static false-detection finder (`services/static.py`)
- Per camera, take all detections with confidence ≥ `STATIC_MIN_CONF` (default 0.2).
- Greedily cluster detections whose IoU with the cluster's representative box is ≥ `STATIC_IOU` (default 0.7).
- A cluster is a **static candidate** if it appears in ≥ `STATIC_MIN_FRACTION` (default 0.1) of that camera's images **and** in ≥ `STATIC_MIN_COUNT` (default 5) images.
- Mark member detections `is_static_candidate = true`. These are **suggestions**: they are ignored in triage only after a human confirms the cluster in the Static Check page. (Prefer high recall here and let humans verify; this matches how TrapTagger works.)

### Triage (`services/triage.py`)
For each event, take the highest-confidence **non-static** animal detection across its images:
- `>= AUTO_ACCEPT_CONF` (default 0.80) → `auto_animal`
- `< AUTO_EMPTY_CONF` (default 0.10), and no person/vehicle above that → `auto_empty`
- otherwise → `needs_review`
Person/vehicle detections above `AUTO_ACCEPT_CONF` label the event `person`/`vehicle` automatically.
All thresholds live in `config.py` and are shown on the dashboard. Re-run triage whenever a static cluster is confirmed or rejected.

## API (FastAPI; OpenAPI docs at /docs)

- `POST /cameras`, `GET /cameras`
- `POST /cameras/{id}/images` (multipart, several files) → stores files, creates Image rows, enqueues one `detect` job per batch of `BATCH_SIZE` images
- `GET /images/{id}/file` → serves the image from storage
- `GET /stats` → counts by status/triage, % auto-handled, processing progress, review throughput
- `GET /review/next?camera_id=&limit=5` → next events needing review, with images and detections (the frontend prefetches these)
- `POST /review/{event_id}` → body `{label, review_duration_ms}`; creates a human Annotation and sets the event to `reviewed`
- `POST /review/{event_id}/undo`
- `GET /static-clusters?camera_id=`, `POST /static-clusters/{id}` → body `{status}`
- `GET /exports/csv`, `GET /exports/coco`

## Worker (`worker/run.py`)
- Loads MegaDetector **once** at startup.
- Loop: take a job → fetch the images from storage → run detection → save Detections → set the images to `processed` → once every image for a camera is processed, run event grouping, the static finder and triage for that camera.
- Retry failed jobs up to 3 times, then mark them `failed` with the error. Log throughput (images/sec).
- Must run on CPU (the developer's laptop has no usable GPU; expect roughly 1–3 s per image). Use a GPU automatically if one is available. Default the LILA subset to ~500 images to keep CPU runs short.

## Offline batch path (no local GPU needed)
Detection can also run elsewhere, with the results loaded into the app afterwards:
- `notebooks/run_megadetector_colab.ipynb`: a Google Colab notebook (GPU runtime) that installs `megadetector`, runs it on a zip of images uploaded to Colab or Google Drive, and writes the standard **MegaDetector batch output JSON**. Keep it short with clear markdown cells.
- `scripts/import_md_results.py --camera <id> --results results.json`: reads a MegaDetector batch output JSON (our own Colab output, **or the precomputed MegaDetector results LILA publishes for many datasets**; check what's available for the chosen dataset), matches entries to Image rows by filename/relative path, saves Detections, sets the images to `processed`, then runs event grouping, the static finder and triage, exactly like the worker does.
- Put the shared "after detection" step in one function used by both the worker and the importer, so the logic isn't duplicated.
- Unit-test the importer with a tiny hand-written results JSON (including the case where a file listed in the JSON is missing from the DB).
- The README should present this as a feature: heavy GPU work can be done in batches elsewhere while the app handles storage, triage and human review.

## Frontend pages

1. **Dashboard**: cameras, processing progress bar, pie/bar of triage outcomes, "% of images the human never had to look at", thresholds in use.
2. **Upload**: choose/create a camera, drag-and-drop many images, upload progress.
3. **Review** (the most important page; make it fast):
   - Shows one event at a time: a large main image with bounding boxes drawn on top (label + confidence), and a thumbnail strip of the event's other images.
   - Keyboard: `1` animal, `2` empty, `3` person, `4` vehicle, `←/→` move between images in the event, `Z` undo the last decision, `?` show the shortcut help.
   - After a decision, move to the next event **instantly**: prefetch the next 5 events and their images.
   - Show a live counter: events reviewed, events left, events/minute.
   - Record `review_duration_ms` per event.
4. **Static Check**: for each pending cluster, show a grid of sample crops/images with the box highlighted; buttons (and keys `Y`/`N`) to confirm or reject.
5. **Export**: buttons to download the CSV and COCO files.

## Exports
- **CSV**: one row per image with camera, site, lat, lon, timestamp, event_id, final label (human annotation overrides AI), label source, number of animal detections, max confidence.
- **COCO JSON**: `images`, `annotations` (bbox in **pixels** `[x, y, width, height]`, converted from normalised), `categories` (animal, person, vehicle). Write a test that checks the bbox conversion.

## Evaluation data and metrics

`scripts/download_lila_subset.py`
- Downloads ~1,000 images with known labels from a camera-trap dataset on **LILA BC** (lila.science). Prefer one of the **Snapshot Safari South African projects** (e.g. Snapshot Karoo or Snapshot Kgalagadi); otherwise Snapshot Serengeti. Check LILA's current metadata/URL format before writing this.
- Choose images from several cameras, keeping whole sequences together, with a realistic mix of empty and animal images.
- Writes a manifest CSV (file, camera/site, timestamp if available, ground-truth empty/non-empty) used to set `ground_truth_label` on import.

`scripts/evaluate.py` prints and saves to `docs/results.md`:
- % of images/events auto-handled (no human needed)
- Empty-filter precision and recall against ground truth (how many real animals were wrongly auto-emptied matters most)
- Number of static clusters found and confirmed
- Median human review time per event, events/minute
- Worker throughput (images/sec on the hardware used)

## Running and demoing (no deployment)
- Everything runs locally with `docker compose up`. The worker must also be runnable outside Docker (`python -m worker.run`) so it can use a local GPU if there is one.
- Record a 2–3 minute demo video (screen recording): upload → processing progress → dashboard numbers → fast keyboard review → static check → export. Link it at the top of the README.
- Never commit credentials or downloaded datasets. Use `.env` (git-ignored) and `.env.example`; git-ignore the data folder.

## Written cloud design (`docs/cloud-design.md`, linked from the README)
A short (1–2 page) design, **not implemented**, showing how this would run at TrapTagger scale (~100M images/year) on AWS:
- S3 for images (direct browser uploads with pre-signed URLs), SQS replacing `DbQueue`, RDS Postgres.
- GPU workers for detection that scale with queue depth (e.g. spot GPU instances in an Auto Scaling group, or AWS Batch), scaling to zero when idle.
- Rough cost reasoning: images/sec per GPU, cost per million images, why spot instances and batching matter.
- How the existing `Storage` and `Queue` interfaces make the switch a matter of adding two classes.
- A Mermaid diagram.

## README requirements (this matters as much as the code)
- One-paragraph pitch: what it does and why (camera traps produce mostly empty images; reviewing them by hand is slow).
- An architecture diagram (Mermaid).
- A GIF or screenshot of the Review page in use.
- A results table taken from `docs/results.md`, with real numbers.
- Quick start: `docker compose up`, then `python scripts/download_lila_subset.py`, then upload.
- "Design decisions" section: why low-confidence cases go to humans instead of being auto-labelled, why static clusters need human confirmation, threshold trade-offs (precision vs recall), why storage and the queue are abstracted.
- "What I'd do next": cloud deployment (link to `docs/cloud-design.md`), species classifier, timestamp OCR, multiple annotators working at once, auth.

## Milestones (do them in order; commit after each with a clear message)

1. **Skeleton**: repo layout, FastAPI app with health check, DB models + Alembic migration, docker-compose, `.env.example`, pytest running. *Done when:* `docker compose up` starts and `/docs` loads.
2. **Data + detection**: LILA download script, ingest with EXIF timestamps, detector wrapper, DbQueue, worker, results-JSON importer and Colab notebook. *Done when:* ~500 images can be imported and get detections either from the local worker (test on a small batch of ~20 on CPU) or from a MegaDetector results JSON.
3. **Core logic**: event grouping, static finder, triage, with unit tests. *Done when:* tests pass and `/stats` shows sensible triage numbers.
4. **Review UI**: React app with Dashboard, Upload and Review pages, keyboard shortcuts and prefetching. *Done when:* a person can review all `needs_review` events using only the keyboard.
5. **Static Check + exports**: Static Check page, CSV and COCO exports, with tests.
6. **Evaluation**: `evaluate.py`, `docs/results.md`.
7. **README + cloud design**: diagram, GIF, results table, design decisions, `docs/cloud-design.md`. The user records the demo video.

**Stretch (only after milestone 7):** OCR of timestamps printed on images (EasyOCR or Tesseract), with checks that reject impossible dates; a polygon mask tool to hide detections in waving grass.

## Working rules for Claude Code
- Work one milestone at a time. At the end of each, summarise what was built, how to run it, and anything that's stubbed.
- Run the tests and linters (`ruff`, `tsc --noEmit`) before saying a milestone is done.
- Ask before adding new major dependencies or changing the data model.
- Keep functions small and typed. Write docstrings explaining *why* for the non-obvious logic (thresholds, clustering).
- When an external API (MegaDetector, LILA) behaves differently from what this file says, follow the real API and update this file.
