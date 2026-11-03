// Mirrors the backend Pydantic schemas exactly (snake_case on purpose)
export type Envelope<T> = { success: true; data: T };
export type Pagination = { total: number; page: number; limit: number; total_pages: number };
export type Page<T> = { success: true; data: T[]; pagination: Pagination };
export type ApiErrorBody = {
  success: false;
  error: { code: string; message: string; fields?: Record<string, string[]> };
};

export type User = { id: number; email: string; name: string; is_admin: boolean };
export type LoginResult = { access_token: string; token_type: 'bearer'; user: User };

export type ScreeningStatus = 'pending' | 'analyzed' | 'reviewed';
export type Eye = 'left' | 'right' | 'unknown';
export type Finding = {
  code: string;
  disease: string;
  probability: number;
  threshold: number;
  positive: boolean;
};
export type AttentionMap = {
  disease: string;
  method: 'Grad-CAM';
  layer: string;
  available: boolean;
  grid: number[][] | null;
};
export type ScreeningResult = {
  screening_id: number;
  overall: string;
  any_positive: boolean;
  findings: Finding[];
  maps: AttentionMap[];
  source: 'live' | 'fixture';
  demo: boolean; // precomputed demo result (DEMO_FIXTURES), never a live run
  latency_ms: number;
  disclaimer: string;
  model: ModelInfo | null; // which checkpoint and thresholds produced it (null on older results)
};
export type ModelInfo = {
  run_id: string | null;
  checkpoint_sha256: string | null;
  model_name: string | null;
  img_size: number | null;
  labels: string[];
  thresholds: number[];
  temperature: number[] | null;
};
export type ImageMeta = { name: string; width: number; height: number; type: string; bytes: number; sharpness: number | null };
export type Screening = {
  id: number;
  owner_id: number;
  patient_ref: string;
  eye: Eye;
  notes: string | null;
  status: ScreeningStatus;
  has_image: boolean;
  image: ImageMeta | null;
  latest_review: ReviewDecision | null;
  result: ScreeningResult | null;
  analyzed_at: string | null;
  created_at: string;
  updated_at: string;
};
export type ScreeningInput = { patient_ref: string; eye?: Eye; notes?: string | null };
export type ScreeningUpdate = Partial<ScreeningInput> & { status?: ScreeningStatus };
export type ScreeningStats = {
  total: number;
  by_status: Record<ScreeningStatus, number>;
  analyzed: number;
  flagged: number;
  positives: Record<string, number>;
  recent: Screening[];
};

export type ReviewDecision = 'agree' | 'disagree' | 'unsure';
export type Review = {
  id: number;
  owner_id: number;
  screening_id: number;
  decision: ReviewDecision;
  note: string | null;
  created_at: string;
};
export type ReviewInput = { decision: ReviewDecision; note?: string | null };

export type DiseaseCard = {
  code: string;
  disease: string;
  threshold: number | null;
  test_precision: number | null;
  test_recall: number | null;
  test_f1: number | null;
  test_ap: number | null;
  test_roc_auc: number | null;
  test_positives: number | null;
  odir_ap: number | null;
  odir_roc_auc: number | null;
  odir_recall: number | null;
  odir_recall_ci: [number, number] | null;
  odir_specificity: number | null;
  odir_specificity_ci: [number, number] | null;
  odir_positives: number | null;
};
export type SourceDataset = { name: string; images: number | null; diseases: string[] };
export type ModelCard = {
  architecture: string;
  model_name: string;
  img_size: number | null;
  live: boolean;
  device: string | null;
  test_images: number | null;
  checkpoint_sha256: string | null;
  checkpoint_modified: string | null;
  run_id: string | null;
  diseases: DiseaseCard[];
  sources: SourceDataset[];
  limitations: string[];
};

/** SQLite drops the UTC offset; treat offset-less timestamps as UTC. */
export const parseUtc = (s: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);

type AxiosLike = { response?: { status?: number; data?: ApiErrorBody }; code?: string; request?: unknown };

/** True when the server could not be reached at all (offline state). */
export function isOffline(err: unknown): boolean {
  const e = err as AxiosLike;
  return !!e && !e.response && (e.code === 'ERR_NETWORK' || e.code === 'ECONNABORTED' || !!e.request);
}

export function apiStatus(err: unknown): number | undefined {
  return (err as AxiosLike)?.response?.status;
}

export function apiError(err: unknown): ApiErrorBody['error'] | undefined {
  return (err as AxiosLike)?.response?.data?.error;
}

/** Human-readable message from any API error. Never render raw error objects. */
export function apiErrorMessage(err: unknown): string {
  if (isOffline(err)) return "Can't reach the server";
  return apiError(err)?.message ?? 'Something went wrong — please try again';
}
