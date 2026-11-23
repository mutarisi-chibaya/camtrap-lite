/** Typed API client. All requests go through Vite's /api proxy to FastAPI. */

const BASE = "/api";
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY, ...extra } : extra;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: headers(body === undefined ? {} : { "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

function query(params: Record<string, string | number | number[] | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined) continue;
    for (const item of Array.isArray(v) ? v : [v]) q.append(k, String(item));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

// ---- types (mirror backend/app/schemas.py) ----

export type Label = "animal" | "empty" | "person" | "vehicle";
export type TriageStatus =
  | "auto_animal"
  | "auto_empty"
  | "auto_person"
  | "auto_vehicle"
  | "needs_review"
  | "reviewed";

export interface Camera {
  id: number;
  name: string;
  site_name: string;
  latitude: number | null;
  longitude: number | null;
  image_count: number;
}

export interface Thresholds {
  event_gap_seconds: number;
  auto_accept_conf: number;
  auto_empty_conf: number;
  static_min_conf: number;
  static_iou: number;
  static_min_fraction: number;
  static_min_count: number;
}

export interface Stats {
  cameras: number;
  total_images: number;
  images_by_status: Record<string, number>;
  processing_progress: number;
  total_events: number;
  events_by_triage: Partial<Record<TriageStatus, number>>;
  images_by_triage: Partial<Record<TriageStatus, number>>;
  pct_images_auto_handled: number;
  pct_events_auto_handled: number;
  static_clusters_by_status: Record<string, number>;
  review: {
    reviewed_events: number;
    remaining_events: number;
    median_review_ms: number | null;
    events_per_minute: number | null;
  };
  thresholds: Thresholds;
}

export interface DetectionOut {
  id: number;
  category: "animal" | "person" | "vehicle";
  confidence: number;
  bbox: [number, number, number, number];
  is_static_candidate: boolean;
}

export interface ReviewImage {
  id: number;
  original_filename: string;
  width: number | null;
  height: number | null;
  timestamp: string | null;
  timestamp_source: "exif" | "filename" | "missing";
  detections: DetectionOut[];
}

export interface ReviewEvent {
  id: number;
  camera_id: number;
  camera_name: string;
  start_time: string | null;
  end_time: string | null;
  max_animal_conf: number | null;
  images: ReviewImage[];
}

export interface ReviewQueue {
  events: ReviewEvent[];
  remaining: number;
}

export interface ReviewResult {
  event_id: number;
  triage_status: TriageStatus;
  label: Label | null;
  remaining: number;
}

export interface UploadResult {
  images: { id: number }[];
  rejected: { filename: string; reason: string }[];
  job_ids: number[];
}

// ---- endpoints ----

export const imageUrl = (imageId: number) => `${BASE}/images/${imageId}/file`;

export const getStats = (cameraId?: number) =>
  request<Stats>("GET", `/stats${query({ camera_id: cameraId })}`);

export const getCameras = () => request<Camera[]>("GET", "/cameras");

export const createCamera = (body: { name: string; site_name?: string }) =>
  request<Camera>("POST", "/cameras", body);

export const getNextReview = (opts: { cameraId?: number; limit?: number; exclude?: number[] }) =>
  request<ReviewQueue>(
    "GET",
    `/review/next${query({ camera_id: opts.cameraId, limit: opts.limit, exclude: opts.exclude })}`,
  );

export const postReview = (
  eventId: number,
  label: Label,
  reviewDurationMs: number,
  cameraId?: number,
) =>
  request<ReviewResult>("POST", `/review/${eventId}${query({ camera_id: cameraId })}`, {
    label,
    review_duration_ms: reviewDurationMs,
  });

export const undoReview = (eventId: number, cameraId?: number) =>
  request<ReviewResult>("POST", `/review/${eventId}/undo${query({ camera_id: cameraId })}`);

/** Multipart upload with progress (fetch has no upload progress events, XHR does). */
export function uploadImages(
  cameraId: number,
  files: File[],
  onProgress: (loadedBytes: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/cameras/${cameraId}/images`);
    for (const [k, v] of Object.entries(headers())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () =>
      xhr.status < 300
        ? resolve(JSON.parse(xhr.responseText) as UploadResult)
        : reject(new Error(`upload failed: ${xhr.status} ${xhr.responseText}`));
    xhr.onerror = () => reject(new Error("upload failed: network error"));
    xhr.send(form);
  });
}

// ---- static clusters & exports ----

export type StaticStatus = "pending" | "confirmed_static" | "rejected";

export interface StaticSample {
  image_id: number;
  detection_id: number;
  bbox: [number, number, number, number];
  confidence: number;
  category: string;
  timestamp: string | null;
  width: number | null;
  height: number | null;
}

export interface StaticCluster {
  id: number;
  camera_id: number;
  camera_name: string;
  bbox: [number, number, number, number];
  occurrence_count: number;
  occurrence_fraction: number;
  status: StaticStatus;
  samples: StaticSample[];
}

export const getStaticClusters = (opts: { cameraId?: number; status?: StaticStatus } = {}) =>
  request<StaticCluster[]>(
    "GET",
    `/static-clusters${query({ camera_id: opts.cameraId, status: opts.status })}`,
  );

export const setStaticStatus = (clusterId: number, status: StaticStatus) =>
  request<StaticCluster>("POST", `/static-clusters/${clusterId}`, { status });

export const exportUrl = (format: "csv" | "coco", opts: { cameraId?: number; minConf?: number }) =>
  `${BASE}/exports/${format}${query({ camera_id: opts.cameraId, min_conf: opts.minConf })}`;
