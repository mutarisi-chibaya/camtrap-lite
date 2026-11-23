import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  type Label,
  getCameras,
  getNextReview,
  getStats,
  imageUrl,
  postReview,
  undoReview,
} from "../api/client";
import EventStrip from "../components/EventStrip";
import ImageWithBoxes from "../components/ImageWithBoxes";
import KeyboardHelp from "../components/KeyboardHelp";
import {
  KEY_LABELS,
  PREFETCH,
  eventsPerMinute,
  excludeIds,
  initialState,
  needsRefill,
  reducer,
  reviewDuration,
} from "../review/queue";

const LABEL_BUTTONS: { key: string; label: Label }[] = [
  { key: "1", label: "animal" },
  { key: "2", label: "empty" },
  { key: "3", label: "person" },
  { key: "4", label: "vehicle" },
];

export default function Review() {
  const [params, setParams] = useSearchParams();
  const cameraParam = params.get("camera");
  const cameraId = cameraParam ? Number(cameraParam) : undefined;
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: getCameras });

  return (
    <div className="review-page">
      <div className="review-toolbar row">
        <label>
          Camera{" "}
          <select
            value={cameraParam ?? ""}
            onChange={(e) => setParams(e.target.value ? { camera: e.target.value } : {})}
          >
            <option value="">All cameras</option>
            {cameras.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {/* A new session (fresh queue and counters) per camera filter. */}
      <ReviewSession key={cameraParam ?? "all"} cameraId={cameraId} />
    </div>
  );
}

function ReviewSession({ cameraId }: { cameraId?: number }) {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(reducer, Date.now(), initialState);
  const [showHelp, setShowHelp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => getStats() });
  const minConf = stats.data?.thresholds.auto_empty_conf ?? 0.1;

  const stateRef = useRef(state);
  stateRef.current = state;

  // All writes go through one promise chain so an undo can never overtake its decision.
  // While writes are pending the local counter is authoritative: a server count taken
  // mid-chain would not include the decisions still in flight.
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const send = useCallback(
    (fn: () => Promise<{ remaining: number }>) => {
      pending.current += 1;
      chain.current = chain.current
        .then(fn)
        .then((r) => {
          if (pending.current === 1) dispatch({ type: "remaining", remaining: r.remaining });
          void queryClient.invalidateQueries({ queryKey: ["stats"] });
        })
        .catch((e: unknown) => setError(String(e)))
        .finally(() => {
          pending.current -= 1;
        });
    },
    [queryClient],
  );

  // Don't lose decisions that are still being saved if the tab is closed.
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (pending.current > 0) e.preventDefault();
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);

  // Keep at least a few events queued; the request excludes what we already have.
  const loading = useRef(false);
  useEffect(() => {
    if (!needsRefill(state) || loading.current) return;
    loading.current = true;
    const exclude = excludeIds(state);
    queryClient
      .fetchQuery({
        queryKey: ["review-next", cameraId, exclude],
        queryFn: () => getNextReview({ cameraId, limit: PREFETCH, exclude }),
        staleTime: 0,
      })
      .then((q) =>
        dispatch({
          type: "loaded",
          events: q.events,
          remaining: pending.current === 0 ? q.remaining : stateRef.current.remaining ?? q.remaining,
          now: Date.now(),
        }),
      )
      .catch((e: unknown) => setError(String(e)))
      .finally(() => {
        loading.current = false;
      });
  }, [state, cameraId, queryClient]);

  // Prefetch every queued event's images so the next decision shows instantly.
  const preloaded = useRef(new Set<number>());
  useEffect(() => {
    for (const ev of state.queue) {
      for (const img of ev.images) {
        if (preloaded.current.has(img.id)) continue;
        preloaded.current.add(img.id);
        new Image().src = imageUrl(img.id);
      }
    }
  }, [state.queue]);

  // Refresh the events/minute display.
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 5000);
    return () => clearInterval(t);
  }, []);

  const decide = useCallback(
    (label: Label) => {
      const s = stateRef.current;
      const current = s.queue[0];
      if (!current) return;
      const now = Date.now();
      const duration = reviewDuration(s, now);
      dispatch({ type: "decide", label, now });
      send(() => postReview(current.id, label, duration, cameraId));
    },
    [send, cameraId],
  );

  const undo = useCallback(() => {
    const last = stateRef.current.history.at(-1);
    if (!last) return;
    dispatch({ type: "undo", now: Date.now() });
    send(() => undoReview(last.event.id, cameraId));
  }, [send, cameraId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA") return;
      if (e.key === "?") {
        setShowHelp((v) => !v);
      } else if (e.key === "Escape") {
        setShowHelp(false);
      } else if (e.key in KEY_LABELS) {
        if (!e.repeat) decide(KEY_LABELS[e.key]);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        dispatch({ type: "image", delta: e.key === "ArrowLeft" ? -1 : 1 });
      } else if (e.key === "z" || e.key === "Z") {
        if (!e.repeat) undo();
      } else {
        return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide, undo]);

  const current = state.queue[0];
  const image = current?.images[state.imageIndex];
  const epm = eventsPerMinute(state, Date.now());

  return (
    <>
      <div className="review-counter">
        <span>
          <strong>{state.history.length}</strong> reviewed this session
        </span>
        <span>
          <strong>{state.remaining ?? "…"}</strong> left
        </span>
        <span>
          <strong>{epm === null ? "–" : epm.toFixed(1)}</strong> events/min
        </span>
        <button type="button" className="link-button" onClick={() => setShowHelp(true)}>
          Shortcuts (?)
        </button>
      </div>

      {error && (
        <div className="error-banner" onClick={() => setError(null)}>
          {error} (click to dismiss)
        </div>
      )}

      {!current ? (
        <div className="review-empty">
          {state.exhausted ? (
            <>
              <h2>Nothing left to review</h2>
              <p>
                Every uncertain event has a human label.{" "}
                {state.history.length > 0 && "Press Z to undo the last decision, or "}
                see the <Link to="/">dashboard</Link>.
              </p>
            </>
          ) : (
            <p>Loading events…</p>
          )}
        </div>
      ) : (
        <div className="review-main">
          <div className="review-meta">
            <span className="camera-chip">{current.camera_name}</span>
            {current.start_time ? (
              <span>{new Date(current.start_time).toLocaleString()}</span>
            ) : (
              <span className="badge-warning">No timestamp: single-image event</span>
            )}
            <span>
              image {state.imageIndex + 1} / {current.images.length}
            </span>
            <span className="muted">{image?.original_filename}</span>
            <span className="muted">
              max animal conf {current.max_animal_conf?.toFixed(2) ?? "–"}
            </span>
          </div>

          {image && (
            <ImageWithBoxes
              imageId={image.id}
              detections={image.detections}
              minConf={minConf}
              alt={image.original_filename}
            />
          )}

          <EventStrip
            images={current.images}
            activeIndex={state.imageIndex}
            onSelect={(i) => dispatch({ type: "image", delta: i - state.imageIndex })}
          />

          <div className="label-buttons">
            {LABEL_BUTTONS.map((b) => (
              <button key={b.key} type="button" className={`label-${b.label}`} onClick={() => decide(b.label)}>
                <kbd>{b.key}</kbd> {b.label}
              </button>
            ))}
            <button type="button" onClick={undo} disabled={state.history.length === 0}>
              <kbd>Z</kbd> undo
            </button>
          </div>
        </div>
      )}

      {showHelp && <KeyboardHelp onClose={() => setShowHelp(false)} />}
    </>
  );
}
