import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { exportUrl, getCameras, getStats } from "../api/client";

export default function Export() {
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: getCameras });
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => getStats() });
  const [cameraId, setCameraId] = useState<number | undefined>(undefined);
  const [minConf, setMinConf] = useState(0.2);
  const remaining = stats.data?.review.remaining_events ?? 0;
  const opts = { cameraId, minConf };

  return (
    <div className="export">
      <section className="card">
        <h2>Options</h2>
        <div className="row">
          <label>
            Camera{" "}
            <select
              value={cameraId ?? ""}
              onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">All cameras</option>
              {cameras.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Min. detection confidence{" "}
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minConf}
              onChange={(e) => setMinConf(Math.min(1, Math.max(0, Number(e.target.value))))}
              style={{ width: 80 }}
            />
          </label>
        </div>
        {remaining > 0 && (
          <p className="badge-warning-light">
            {remaining} events still need review; their images are exported without a final label.
          </p>
        )}
      </section>

      <div className="two-col">
        <section className="card">
          <h2>CSV</h2>
          <p className="muted">
            One row per image: camera, site, coordinates, timestamp, event, final label (a human
            label overrides the AI one), label source, number of animal detections and max confidence.
          </p>
          <a className="button primary" href={exportUrl("csv", opts)} download>
            Download CSV
          </a>
        </section>
        <section className="card">
          <h2>COCO JSON</h2>
          <p className="muted">
            <code>images</code>, <code>annotations</code> with pixel boxes <code>[x, y, width, height]</code>,
            and <code>categories</code> (animal, person, vehicle). Boxes from events labelled empty and from
            confirmed static clusters are left out.
          </p>
          <a className="button primary" href={exportUrl("coco", opts)} download>
            Download COCO JSON
          </a>
        </section>
      </div>
    </div>
  );
}
