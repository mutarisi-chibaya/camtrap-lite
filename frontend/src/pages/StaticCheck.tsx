import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type StaticCluster, type StaticStatus, getStaticClusters, setStaticStatus } from "../api/client";
import BoxCrop from "../components/BoxCrop";

/**
 * Humans confirm or reject suggested static false detections. Only confirmed clusters are
 * ignored by triage, and every decision re-runs triage for that camera on the server.
 */
export default function StaticCheck() {
  const queryClient = useQueryClient();
  const [showDecided, setShowDecided] = useState(false);
  const clusters = useQuery({ queryKey: ["static-clusters"], queryFn: () => getStaticClusters() });

  const decide = useMutation({
    mutationFn: ({ id, status }: { id: number; status: StaticStatus }) => setStaticStatus(id, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["static-clusters"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const pending = clusters.data?.filter((c) => c.status === "pending") ?? [];
  const decided = clusters.data?.filter((c) => c.status !== "pending") ?? [];
  const current = pending[0];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.repeat || !current || decide.isPending) return;
      const key = e.key.toLowerCase();
      if (key === "y") decide.mutate({ id: current.id, status: "confirmed_static" });
      else if (key === "n") decide.mutate({ id: current.id, status: "rejected" });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, decide]);

  if (clusters.isPending) return <p>Loading…</p>;
  if (clusters.isError) return <p className="error-banner">{String(clusters.error)}</p>;

  return (
    <div className="static-check">
      <p className="muted">
        Boxes that fire in the same place across many images are often rocks, branches or glare.
        Confirming a cluster makes triage ignore its detections; rejecting keeps them. Keys:{" "}
        <kbd>Y</kbd> confirm static, <kbd>N</kbd> reject (real animals).
      </p>
      {decide.isError && <p className="error-banner">{String(decide.error)}</p>}

      {current ? (
        <ClusterCard
          cluster={current}
          busy={decide.isPending}
          onDecide={(status) => decide.mutate({ id: current.id, status })}
          highlight
        />
      ) : (
        <div className="review-empty">
          <h2>No pending static clusters</h2>
          <p className="muted">New ones are found automatically when a camera finishes processing.</p>
        </div>
      )}

      {pending.length > 1 && <p className="muted">{pending.length - 1} more pending after this one.</p>}

      {decided.length > 0 && (
        <section>
          <button type="button" className="link-button" onClick={() => setShowDecided((v) => !v)}>
            {showDecided ? "Hide" : "Show"} {decided.length} decided cluster{decided.length > 1 ? "s" : ""}
          </button>
          {showDecided &&
            decided.map((c) => (
              <ClusterCard
                key={c.id}
                cluster={c}
                busy={decide.isPending}
                onDecide={(status) => decide.mutate({ id: c.id, status })}
              />
            ))}
        </section>
      )}
    </div>
  );
}

function ClusterCard({
  cluster,
  busy,
  onDecide,
  highlight = false,
}: {
  cluster: StaticCluster;
  busy: boolean;
  onDecide: (s: StaticStatus) => void;
  highlight?: boolean;
}) {
  return (
    <section className={`card${highlight ? " card-current" : ""}`}>
      <div className="row cluster-head">
        <span className="camera-chip camera-chip-light">{cluster.camera_name}</span>
        <span>
          box in <strong>{cluster.occurrence_count}</strong> images (
          {(cluster.occurrence_fraction * 100).toFixed(1)}% of this camera)
        </span>
        <span className={`status status-${cluster.status}`}>{cluster.status.replace("_", " ")}</span>
        <span className="spacer" />
        {cluster.status === "pending" ? (
          <>
            <button type="button" className="primary" disabled={busy} onClick={() => onDecide("confirmed_static")}>
              <kbd>Y</kbd> Static (ignore)
            </button>
            <button type="button" disabled={busy} onClick={() => onDecide("rejected")}>
              <kbd>N</kbd> Real detections
            </button>
          </>
        ) : (
          <button type="button" disabled={busy} onClick={() => onDecide("pending")}>
            Reset to pending
          </button>
        )}
      </div>
      <div className="crop-grid">
        {cluster.samples.map((s) => (
          <BoxCrop
            key={s.detection_id}
            imageId={s.image_id}
            bbox={s.bbox}
            aspect={s.width && s.height ? s.width / s.height : 4 / 3}
            caption={`${s.timestamp ? new Date(s.timestamp).toLocaleString() : "no time"} · ${s.confidence.toFixed(2)}`}
          />
        ))}
      </div>
    </section>
  );
}
