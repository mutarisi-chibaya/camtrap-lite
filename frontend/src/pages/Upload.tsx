import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type DragEvent, type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { createCamera, getCameras, uploadImages } from "../api/client";
import ProgressBar from "../components/ProgressBar";

// Files per request: keeps each request small and lets the worker start on early batches.
const CHUNK = 20;

interface Outcome {
  uploaded: number;
  jobs: number;
  rejected: { filename: string; reason: string }[];
}

export default function Upload() {
  const queryClient = useQueryClient();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: getCameras });
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [newSite, setNewSite] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = cameraId ?? cameras.data?.[0]?.id ?? null;

  async function onCreateCamera(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const cam = await createCamera({ name: newName.trim(), site_name: newSite.trim() });
      await queryClient.invalidateQueries({ queryKey: ["cameras"] });
      setCameraId(cam.id);
      setNewName("");
      setNewSite("");
    } catch (err) {
      setError(String(err));
    }
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    const images = Array.from(list).filter((f) => f.type.startsWith("image/") || /\.jpe?g$/i.test(f.name));
    setFiles((prev) => [...prev, ...images]);
    setOutcome(null);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  }

  async function onUpload() {
    if (selected === null || files.length === 0) return;
    setError(null);
    const total = files.reduce((n, f) => n + f.size, 0);
    let done = 0;
    const result: Outcome = { uploaded: 0, jobs: 0, rejected: [] };
    setProgress(0);
    try {
      for (let i = 0; i < files.length; i += CHUNK) {
        const chunk = files.slice(i, i + CHUNK);
        const size = chunk.reduce((n, f) => n + f.size, 0);
        const r = await uploadImages(selected, chunk, (loaded) => setProgress((done + Math.min(loaded, size)) / total));
        done += size;
        result.uploaded += r.images.length;
        result.jobs += r.job_ids.length;
        result.rejected.push(...r.rejected);
        setProgress(done / total);
      }
      setFiles([]);
      setOutcome(result);
      void queryClient.invalidateQueries({ queryKey: ["cameras"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    } catch (err) {
      setError(String(err));
    } finally {
      setProgress(null);
    }
  }

  const totalMb = files.reduce((n, f) => n + f.size, 0) / 1e6;

  return (
    <div className="upload">
      <section className="card">
        <h2>1. Camera</h2>
        <div className="row">
          <select
            value={selected ?? ""}
            onChange={(e) => setCameraId(Number(e.target.value))}
            disabled={!cameras.data?.length}
          >
            {cameras.data?.length ? null : <option value="">No cameras yet: create one</option>}
            {cameras.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} {c.site_name && `(${c.site_name})`}
              </option>
            ))}
          </select>
          <span className="muted">or</span>
          <form className="row" onSubmit={onCreateCamera}>
            <input placeholder="New camera name" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <input placeholder="Site" value={newSite} onChange={(e) => setNewSite(e.target.value)} />
            <button type="submit" disabled={!newName.trim()}>
              Create
            </button>
          </form>
        </div>
      </section>

      <section className="card">
        <h2>2. Images</h2>
        <label
          className={`dropzone${dragging ? " dropzone-active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input type="file" multiple accept="image/*" onChange={(e) => addFiles(e.target.files)} hidden />
          <strong>Drop camera-trap images here</strong>
          <span>or click to choose files</span>
          {files.length > 0 && (
            <span className="muted">
              {files.length} files selected ({totalMb.toFixed(1)} MB)
            </span>
          )}
        </label>
        <div className="row">
          <button
            type="button"
            className="primary"
            onClick={onUpload}
            disabled={selected === null || files.length === 0 || progress !== null}
          >
            Upload {files.length || ""} images
          </button>
          {files.length > 0 && progress === null && (
            <button type="button" onClick={() => setFiles([])}>
              Clear
            </button>
          )}
        </div>
        {progress !== null && <ProgressBar value={progress} label={`Uploading… ${Math.round(progress * 100)}%`} />}
        {error && <p className="error-banner">{error}</p>}
        {outcome && (
          <div className="notice">
            Uploaded {outcome.uploaded} images; {outcome.jobs} detection jobs queued. Track progress on the{" "}
            <Link to="/">dashboard</Link>.
            {outcome.rejected.length > 0 && (
              <ul>
                {outcome.rejected.map((r) => (
                  <li key={r.filename}>
                    {r.filename}: {r.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
