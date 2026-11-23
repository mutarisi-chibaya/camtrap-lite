# CamTrap Lite tutorial

This guide takes you from a fresh start to exported results in about 20 minutes:

1. start the app;
2. load real camera-trap data;
3. read the dashboard;
4. review the uncertain events;
5. check static detections;
6. mask waving grass;
7. fix missing timestamps;
8. export your results.

You need **Docker Desktop**. Python 3.11 is needed only for the download script in step 2.
Commands are shown for PowerShell; they are the same in a Mac/Linux terminal.

> Want the 2-minute version first? Watch the [demo video](demo.mp4).

---

## 1. Start the app

Start Docker Desktop and wait until it says the engine is running. Then, in the project
folder:

```powershell
copy .env.example .env      # optional: the defaults work
docker compose up -d --build
```

The first build takes several minutes, because it downloads PyTorch and MegaDetector for
the worker. When it finishes, four services are running:

| Service | What it does | Address |
|---|---|---|
| `frontend` | the web app | <http://localhost:5173> |
| `api` | REST API (FastAPI) | <http://localhost:8000/docs> |
| `worker` | runs MegaDetector on uploaded images | (no page) |
| `db` | Postgres database | `localhost:5432` |

Check them with `docker compose ps`. Stop them with `docker compose down`. **Never add
`-v`**: that deletes the database.

## 2. Load real camera-trap data

The quickest way to see the app at work is about 500 labelled images from the
**Snapshot Karoo** project (South Africa), published on LILA BC.

```powershell
# Download images + metadata + LILA's MegaDetector results (~480 MB, a few minutes)
python backend\scripts\download_lila_subset.py

# Load them: one camera per LILA location, ground-truth labels attached
docker compose exec api python scripts/ingest_lila_subset.py

# Detection: use LILA's precomputed MegaDetector v5a results (takes seconds)
docker compose exec api python scripts/import_md_results.py --results /data/lila/md_results_subset.json
```

**Why precomputed results?** MegaDetector takes about 7 seconds per image on a laptop
CPU, so 500 images would take an hour. Our own worker produces the same numbers (within
±0.002 confidence), so the app treats both sources the same way. Prefer to run the model
yourself? See [Run MegaDetector yourself](#run-megadetector-yourself) below.

> **Git Bash on Windows:** put `MSYS_NO_PATHCONV=1` in front of commands that contain
> `/data/...`. Otherwise Git Bash rewrites the path. PowerShell doesn't have this problem.

## 3. Read the dashboard

Open <http://localhost:5173>.

![Dashboard](img/dashboard.png)

- **The green tile** is the headline: the share of images nobody needs to look at.
- **Trigger events.** A camera trap fires in bursts, and images 60 s or less apart form
  one event. You review events, not single images.
- **Triage outcomes.** Each event gets one outcome from its most confident detection:
  - `auto_animal`: an animal ≥ 0.80. Handled automatically.
  - `auto_empty`: nothing ≥ 0.10. Handled automatically.
  - `auto_person` / `auto_vehicle`: a person or vehicle ≥ 0.80.
  - `needs_review`: everything in between. **This is your work.**
- **Thresholds in use** shows the current settings (see [Tuning](#tuning-the-thresholds)).

## 4. Upload your own images (optional)

![Upload page](img/upload.png)

1. Go to **Upload** and pick a camera, or create one (name and site).
2. Drag images onto the drop zone, or click it to choose files.
3. Click **Upload**. The files are stored and detection jobs are queued, 20 images per job.
4. Go back to the **Dashboard**. The progress bar updates every few seconds while the
   worker runs MegaDetector.

When the last image of a camera is processed, the app groups that camera's images into
events, looks for static detections and triages every event automatically.

## 5. Review the uncertain events

Go to **Review**. You see one event at a time: a large image with MegaDetector's boxes, and
a strip of the event's other images.

![Review page](img/review.gif)

| Key | Action |
|---|---|
| `1` | Animal |
| `2` | Empty |
| `3` | Person |
| `4` | Vehicle |
| `←` / `→` | Previous / next image in the event |
| `Z` | Undo the last decision |
| `?` | Show the shortcuts |

![Keyboard shortcuts](img/review-help.png)

Tips for reviewing quickly and accurately:

- **Look at every image of an event** (`→`) before you choose "empty". The animal is
  often only in one frame, and the box with the highest confidence isn't always on the
  first image.
- **Low-confidence boxes** (0.1–0.3) are often a rock, a shadow or the edge of a bush. But
  small or distant animals also score low. Zoom with your browser (`Ctrl` + `+`) if needed.
- **Label the event, not the box.** If any image shows an animal, press `1`, even if
  MegaDetector boxed the wrong thing.
- **Made a mistake?** Press `Z`. The event comes back and you can label it again.
- **Work one camera at a time** with the *Camera* menu, so you get used to that camera's
  view.

The counter shows how many you've reviewed, how many are left, and your speed in events
per minute. Review time per event is saved, and `evaluate.py` reports it (step 10).

## 6. Check static detections

Some things look like an animal to MegaDetector in *every* image: a rock, a stump, a
branch, glare. The app finds boxes that appear in the same place in at least 10% (and at
least 5) of a camera's images, and suggests them as **static clusters**. Go to
**Static Check**.

![Static Check](img/static-check.png)

Each card shows zoomed crops of the box, spread over the whole time range.

- **`Y` (static, ignore):** the crops show the same object every time, such as a rock or a
  branch. From now on, triage ignores these detections, so events that only had "the
  rock" become empty.
- **`N` (real detections):** the crops show animals, people or vehicles. Nothing is
  ignored.

> **Example from the Karoo data:** camera E01 has a cluster covering almost the whole
> frame. The crops show large antelopes standing right in front of the lens on three
> different days, so the right answer is **N**. This is why clusters are only suggestions:
> rejecting by default would have thrown away real animals.

Every decision immediately re-runs triage for that camera. Changed your mind? Click
*Show decided clusters*, then **Reset to pending**.

## 7. Mask waving grass

Grass and branches moving in the wind trigger boxes that *wander around* an area. They
never sit in exactly the same place, so the static finder doesn't catch them. Use a
**mask** instead. Go to **Masks**.

![Mask editor](img/masks.png)

1. Choose the camera. Use `←` / `→` to pick a clear background image.
2. Every detection box of that camera is drawn, with a dot at its centre. Look for areas
   where boxes pile up but no animals are.
3. Click around that area to draw a polygon. Dots turn **grey** when they are covered:
   those detections will be ignored. A detection counts as masked when its box *centre* is
   inside the polygon.
4. Give it a name and press `Enter` (or click the first point) to save. Use `Backspace` to
   remove the last point and `Esc` to cancel.

Saving re-runs triage for that camera, and the dashboard numbers change. **Masks are
powerful:** an animal walking through the masked area is ignored too. Keep masks tight
around the problem area, and check how many events moved on the dashboard. Deleting a
mask restores everything.

## 8. Fix missing timestamps (OCR)

Images normally carry their capture time in EXIF data. Some arrive without it, for
example after being re-saved by other software. Without a time, an image can't be grouped
with its burst, so it becomes a single-image event marked *"No timestamp"*.

Most cameras also print the time on the image, in the banner at the bottom. The worker
reads that banner automatically for **uploaded** images without EXIF, and marks them
*"time from OCR"* on the Review page. For images that came in through the results importer,
run:

```powershell
docker compose exec worker python scripts/ocr_timestamps.py
```

Every OCR result is checked. Impossible dates, future dates, dates before 2000 and dates
far outside the camera's other images (a reset camera clock) are rejected. If your cameras
print dates day-first (25/10/2017), set `OCR_DATE_ORDER=DMY` in `.env`. To measure OCR
accuracy on images that *do* have EXIF:

```powershell
docker compose exec worker python scripts/ocr_timestamps.py --compare 40
```

On the Karoo data it matched EXIF to the minute in 40 of 40 images.

## 9. Export your results

Go to **Export**.

![Export page](img/export.png)

- **CSV:** one row per image with camera, site, coordinates, timestamp, event, **final
  label** and its source, triage status, number of animal detections and highest animal
  confidence. The final label is the human one if someone reviewed the event, otherwise the
  AI one. Images still waiting for review have an empty label.
- **COCO JSON:** for training or analysis tools. `images`, `annotations` with boxes in
  **pixels** `[x, y, width, height]`, and `categories` (animal, person, vehicle). Boxes from
  events labelled empty, from confirmed static clusters and from masks are left out.

Use *Min. detection confidence* to choose which boxes count (default 0.2, MegaDetector's
usual threshold), and *Camera* to export one camera.

## 10. Measure how well it worked

With ground-truth labels (the LILA data has them), the evaluation script scores the whole
pipeline. Run it from the `backend` folder on your computer, using the project's Python
environment (see the README to set it up):

```powershell
cd backend
$env:DATABASE_URL = "postgresql+psycopg://camtrap:camtrap@localhost:5432/camtrap"
$env:STORAGE_DIR = "../data/storage"
.venv\Scripts\python scripts\evaluate.py --benchmark 0
```

It writes [results.md](results.md) and reports:

- the share of images and events handled without a human;
- how many real animals were wrongly auto-emptied (the most important number);
- the empty filter's precision and recall;
- your median review time and events per minute;
- a table of what other thresholds would have done.

Drop `--benchmark 0` to also time MegaDetector on your machine.

## Tuning the thresholds

All thresholds are in `.env`:

| Setting | Default | Raise it to… | Lower it to… |
|---|---:|---|---|
| `AUTO_ACCEPT_CONF` | 0.80 | make automatic "animal" labels more reliable (more review) | automate more (more mistakes) |
| `AUTO_EMPTY_CONF` | 0.10 | automate more empties (risk losing faint animals) | send more to review (safer) |
| `EVENT_GAP_SECONDS` | 60 | merge slower bursts into one event | split events more |
| `STATIC_MIN_FRACTION` / `STATIC_MIN_COUNT` | 0.1 / 5 | suggest fewer static clusters | suggest more |

The threshold table in `results.md` shows what each choice would have done on your data.
After editing `.env`:

```powershell
docker compose up -d                               # restart with the new values
docker compose exec api python scripts/retriage.py # re-triage every camera
```

Human reviews and static decisions are kept; only automatic outcomes change.

## Run MegaDetector yourself

- **On this computer (CPU, about 7 s/image):** load images with
  `scripts/ingest_lila_subset.py --enqueue`, or simply upload them. The `worker` container
  processes the queue.
- **On a local NVIDIA GPU:** stop the container worker (`docker compose stop worker`) and run
  the worker outside Docker. It uses the GPU automatically. On Windows, pip installs a
  CPU-only PyTorch by default, so first install the CUDA build that matches your driver
  (see pytorch.org):
  ```powershell
  cd backend
  python -m venv .venv
  .venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
  .venv\Scripts\pip install -e ".[ml]"
  $env:DATABASE_URL = "postgresql+psycopg://camtrap:camtrap@localhost:5432/camtrap"
  $env:STORAGE_DIR = "../data/storage"
  .venv\Scripts\python -m worker.run
  ```
- **On Google Colab (free GPU):** open
  [notebooks/run_megadetector_colab.ipynb](../notebooks/run_megadetector_colab.ipynb), upload
  a zip of your images, and download `results.json`. Then:
  ```powershell
  docker compose cp results.json api:/tmp/results.json
  docker compose exec api python scripts/import_md_results.py --results /tmp/results.json --camera <id>
  ```

## Troubleshooting

| Problem | Fix |
|---|---|
| `docker compose up` fails pulling images with "unauthorized" | Your saved Docker Hub login is wrong: run `docker logout` (or `docker login`) |
| The page loads but shows errors or no data | `docker compose ps`: all four services should be running; check `docker compose logs api` |
| The progress bar doesn't move after an upload | `docker compose logs worker`: the first job downloads the model (~280 MB) |
| `FileNotFoundError: C:/Program Files/Git/data/...` | Git Bash path rewriting: put `MSYS_NO_PATHCONV=1` before the command |
| Port 5432 or 8000 already in use | Set `POSTGRES_PORT=5433` in `.env`, or stop the other program |
| I want to start over | `docker compose down -v` deletes the database (**irreversible**), then repeat step 2 |
