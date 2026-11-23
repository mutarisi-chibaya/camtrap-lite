import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { type TriageStatus, getCameras, getStats } from "../api/client";
import ProgressBar from "../components/ProgressBar";

const OUTCOMES: { status: TriageStatus; label: string }[] = [
  { status: "auto_empty", label: "Auto: empty" },
  { status: "auto_animal", label: "Auto: animal" },
  { status: "auto_person", label: "Auto: person" },
  { status: "auto_vehicle", label: "Auto: vehicle" },
  { status: "needs_review", label: "Needs review" },
  { status: "reviewed", label: "Reviewed by a human" },
];

export default function Dashboard() {
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: () => getStats(),
    // Poll quickly while the worker is still processing, slowly otherwise.
    refetchInterval: (q) => ((q.state.data?.processing_progress ?? 0) < 1 ? 3000 : 15000),
  });
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: getCameras });

  if (stats.isPending) return <p>Loading…</p>;
  if (stats.isError) return <p className="error-banner">Could not load stats: {String(stats.error)}</p>;
  const s = stats.data;
  const processed = s.images_by_status.processed ?? 0;
  const failed = s.images_by_status.failed ?? 0;
  const maxImages = Math.max(1, ...Object.values(s.images_by_triage).map((v) => v ?? 0));

  return (
    <div className="dashboard">
      <section className="tiles">
        <div className="tile tile-hero">
          <div className="tile-value">{s.pct_images_auto_handled.toFixed(1)}%</div>
          <div className="tile-label">of images a human never had to look at</div>
        </div>
        <div className="tile">
          <div className="tile-value">{s.total_images}</div>
          <div className="tile-label">images · {s.cameras} cameras</div>
        </div>
        <div className="tile">
          <div className="tile-value">{s.total_events}</div>
          <div className="tile-label">trigger events</div>
        </div>
        <Link to="/review" className="tile tile-link">
          <div className="tile-value">{s.review.remaining_events}</div>
          <div className="tile-label">events need review →</div>
        </Link>
        <div className="tile">
          <div className="tile-value">
            {s.review.median_review_ms === null ? "–" : `${(s.review.median_review_ms / 1000).toFixed(1)} s`}
          </div>
          <div className="tile-label">
            median review time
            {s.review.events_per_minute !== null && ` · ${s.review.events_per_minute.toFixed(0)} events/min`}
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Processing</h2>
        <ProgressBar
          value={s.processing_progress}
          label={`${processed + failed} / ${s.total_images} images processed${failed ? ` (${failed} failed)` : ""}`}
        />
      </section>

      <section className="card">
        <h2>Triage outcomes</h2>
        <table className="bars">
          <thead>
            <tr>
              <th>Outcome</th>
              <th>Events</th>
              <th>Images</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {OUTCOMES.map(({ status, label }) => {
              const images = s.images_by_triage[status] ?? 0;
              return (
                <tr key={status}>
                  <td>{label}</td>
                  <td className="num">{s.events_by_triage[status] ?? 0}</td>
                  <td className="num">{images}</td>
                  <td className="bar-cell">
                    <div className={`bar bar-${status}`} style={{ width: `${(100 * images) / maxImages}%` }} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <div className="two-col">
        <section className="card">
          <h2>Cameras</h2>
          <table className="plain">
            <thead>
              <tr>
                <th>Name</th>
                <th>Site</th>
                <th className="num">Images</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {cameras.data?.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{c.site_name}</td>
                  <td className="num">{c.image_count}</td>
                  <td>
                    <Link to={`/review?camera=${c.id}`}>review</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {cameras.data?.length === 0 && (
            <p>
              No cameras yet. <Link to="/upload">Upload images</Link>.
            </p>
          )}
        </section>

        <section className="card">
          <h2>Thresholds in use</h2>
          <table className="plain">
            <tbody>
              <tr>
                <td>Auto-accept (animal/person/vehicle)</td>
                <td className="num">≥ {s.thresholds.auto_accept_conf}</td>
              </tr>
              <tr>
                <td>Auto-empty (all detections)</td>
                <td className="num">&lt; {s.thresholds.auto_empty_conf}</td>
              </tr>
              <tr>
                <td>Event gap</td>
                <td className="num">{s.thresholds.event_gap_seconds} s</td>
              </tr>
              <tr>
                <td>Static: min confidence / IoU</td>
                <td className="num">
                  {s.thresholds.static_min_conf} / {s.thresholds.static_iou}
                </td>
              </tr>
              <tr>
                <td>Static: min share / count of images</td>
                <td className="num">
                  {s.thresholds.static_min_fraction * 100}% / {s.thresholds.static_min_count}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            Static clusters:{" "}
            {Object.entries(s.static_clusters_by_status)
              .map(([k, v]) => `${v} ${k.replace("_", " ")}`)
              .join(", ") || "none"}
          </p>
        </section>
      </div>
    </div>
  );
}
