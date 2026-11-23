import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createMask,
  deleteMask,
  getCameraBoxes,
  getCameraImages,
  getCameras,
  getMasks,
  imageUrl,
} from "../api/client";
import { boxStyle } from "../components/boxes";
import { type Point, closesPolygon, isMasked, svgPoints, toNormalized } from "../masks/geometry";

/**
 * Draw polygons over areas whose detections should be ignored (grass, branches, a road).
 * All of the camera's detection boxes are overlaid, so piles of false boxes are easy to see,
 * and boxes turn grey live as the polygon covers them.
 */
export default function Masks() {
  const queryClient = useQueryClient();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: getCameras });
  const [cameraId, setCameraId] = useState<number | null>(null);
  const cam = cameraId ?? cameras.data?.[0]?.id ?? null;

  const images = useQuery({
    queryKey: ["camera-images", cam],
    queryFn: () => getCameraImages(cam!, 200),
    enabled: cam !== null,
  });
  const boxes = useQuery({
    queryKey: ["camera-boxes", cam],
    queryFn: () => getCameraBoxes(cam!),
    enabled: cam !== null,
  });
  const masks = useQuery({ queryKey: ["masks", cam], queryFn: () => getMasks(cam!), enabled: cam !== null });

  const [imageIndex, setImageIndex] = useState(0);
  const [draft, setDraft] = useState<Point[]>([]);
  const [name, setName] = useState("");
  const frame = useRef<HTMLDivElement>(null);

  const invalidate = () => {
    for (const key of [["masks", cam], ["camera-boxes", cam], ["stats"], ["static-clusters"]])
      void queryClient.invalidateQueries({ queryKey: key });
  };
  const save = useMutation({
    mutationFn: () => createMask(cam!, { name: name.trim(), polygon: draft }),
    onSuccess: () => {
      setDraft([]);
      setName("");
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: deleteMask, onSuccess: invalidate });

  // Reset when switching camera.
  useEffect(() => {
    setImageIndex(0);
    setDraft([]);
  }, [cam]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      // In the name box only Enter (save) applies; other keys type normally.
      if ((tag === "INPUT" || tag === "SELECT") && e.key !== "Enter") return;
      if (e.key === "Escape") setDraft([]);
      else if (e.key === "Backspace") setDraft((d) => d.slice(0, -1));
      else if (e.key === "Enter" && draft.length >= 3 && !save.isPending) save.mutate();
      else if (e.key === "ArrowLeft") setImageIndex((i) => Math.max(0, i - 1));
      else if (e.key === "ArrowRight") setImageIndex((i) => Math.min((images.data?.length ?? 1) - 1, i + 1));
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [draft, save, images.data]);

  const saved = useMemo(() => (masks.data ?? []).map((m) => m.polygon), [masks.data]);
  const preview = draft.length >= 3 ? [...saved, draft] : saved;
  const image = images.data?.[imageIndex];
  const allBoxes = boxes.data ?? [];
  const nMasked = allBoxes.filter((b) => isMasked(b.bbox, preview)).length;

  function onClick(e: MouseEvent<HTMLDivElement>) {
    if (!frame.current) return;
    const p = toNormalized(e.clientX, e.clientY, frame.current.getBoundingClientRect());
    if (closesPolygon(p, draft)) {
      if (!save.isPending) save.mutate();
      return;
    }
    setDraft((d) => [...d, p]);
  }

  return (
    <div className="masks-page">
      <p className="muted">
        Click on the image to draw a polygon around an area whose detections should be ignored, such as
        grass that moves in the wind. A box is masked when its centre is inside a polygon. Triage, the
        static finder and exports ignore masked boxes; deleting the mask brings them back. Keys: click
        the first point or <kbd>Enter</kbd> to save, <kbd>Backspace</kbd> undo point, <kbd>Esc</kbd>{" "}
        cancel, <kbd>←/→</kbd> background image.
      </p>

      <div className="row masks-toolbar">
        <label>
          Camera{" "}
          <select value={cam ?? ""} onChange={(e) => setCameraId(Number(e.target.value))}>
            {cameras.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">
          image {images.data?.length ? imageIndex + 1 : 0} / {images.data?.length ?? 0}
        </span>
        <span>
          <strong>{nMasked}</strong> of {allBoxes.length} boxes (conf ≥ 0.2) masked
        </span>
      </div>

      <div className="masks-layout">
        <div className="mask-frame" ref={frame} onClick={onClick}>
          {image && <img src={imageUrl(image.id)} alt="" draggable={false} />}
          {allBoxes.map((b, i) => (
            <div key={i} className="heat-box" style={boxStyle(b.bbox)} />
          ))}
          <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="mask-svg">
            {/* box centres decide masking, so they are drawn as dots */}
            {allBoxes.map((b, i) => (
              <circle
                key={i}
                cx={b.bbox[0] + b.bbox[2] / 2}
                cy={b.bbox[1] + b.bbox[3] / 2}
                r={0.006}
                className={isMasked(b.bbox, preview) ? "centre centre-masked" : "centre"}
              />
            ))}
            {masks.data?.map((m) => (
              <polygon key={m.id} points={svgPoints(m.polygon)} className="mask-saved" />
            ))}
            {draft.length > 0 && (
              <polyline
                points={svgPoints(draft.length >= 3 ? [...draft, draft[0]] : draft)}
                className="mask-draft"
              />
            )}
            {draft.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r={i === 0 ? 0.008 : 0.005} className="mask-point" />
            ))}
          </svg>
        </div>

        <aside className="card mask-side">
          <h2>New mask</h2>
          <input placeholder="Name, e.g. grass bottom-left" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="row">
            <button
              type="button"
              className="primary"
              disabled={draft.length < 3 || save.isPending}
              onClick={() => save.mutate()}
            >
              Save mask ({draft.length} points)
            </button>
            <button type="button" disabled={draft.length === 0} onClick={() => setDraft([])}>
              Cancel
            </button>
          </div>
          {save.isError && <p className="error-banner">{String(save.error)}</p>}

          <h2>Masks on this camera</h2>
          {masks.data?.length ? (
            <ul className="mask-list">
              {masks.data.map((m) => (
                <li key={m.id}>
                  <span>{m.name || `Mask ${m.id}`}</span>
                  <button type="button" disabled={remove.isPending} onClick={() => remove.mutate(m.id)}>
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None yet.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
