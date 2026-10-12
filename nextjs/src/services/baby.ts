/**
 * 육아앱 웹 서비스 — /v1/babies, /v1/baby-logs, /v1/baby-growth, /v1/vaccines.
 * 모바일(baby-app)과 동일한 그누보드 REST API 를 /api/g5 프록시로 호출.
 */
import { apiClient } from "@/lib/api";

export type BabySex = "m" | "f" | "";

export interface Baby {
  baby_id: number;
  mb_id: string;
  baby_name: string;
  baby_birth: string;
  baby_sex: BabySex;
  baby_image_uri: string | null;
  baby_memo: string | null;
  baby_pinned: boolean;
  age_days: number | null;
  age_months: number | null;
  age_label: string;
  can_manage?: boolean;
}

export interface BabyInput {
  baby_name: string;
  baby_birth: string;
  baby_sex?: BabySex;
  baby_memo?: string | null;
  client_uid?: string;
}

// ⚠️ 단일 소스 없음 — baby-app/src/api/babyLogs.ts, extend/baby.extend.php baby_log_types()
//    와 동일 목록 유지 필요(서버 검증의 진실 원천은 baby_log_types()).
export type BabyLogType =
  | "feed_breast" | "feed_bottle" | "feed_solid" | "pump"
  | "diaper_wet" | "diaper_dirty" | "diaper_mixed"
  | "sleep" | "bath" | "med" | "temperature" | "etc";

export interface BabyLog {
  log_id: number;
  baby_id: number;
  log_type: BabyLogType;
  started_at: string;
  ended_at: string | null;
  amount: number | null;
  unit: string | null;
  memo: string | null;
}

export interface BabyGrowth {
  growth_id: number;
  baby_id: number;
  measured_on: string;
  height_cm: number | null;
  weight_kg: number | null;
  head_cm: number | null;
  age_days_at_measure: number | null;
}

export type VaccineStatus = "done" | "overdue" | "upcoming" | "scheduled";

export interface VaccineItem {
  tpl_id: number;
  vaccine_name: string;
  target_disease: string;
  dose_no: number;
  due_label: string;
  due_date: string | null;
  days_until: number | null;
  status: VaccineStatus;
  bv_id: number | null;
  done_on: string | null;
}

export interface VaccineSummary {
  done: number; overdue: number; upcoming: number; scheduled: number;
}

export interface VaccineView {
  baby_id: number;
  items: VaccineItem[];
  summary: VaccineSummary;
  disclaimer: string;
}

export async function listBabies(): Promise<Baby[]> {
  const res = await apiClient.get<Baby[]>("/babies");
  return res.data ?? [];
}

export async function createBaby(input: BabyInput): Promise<Baby | null> {
  const res = await apiClient.post<Baby>("/babies", input);
  return res.data ?? null;
}

export async function listLogs(babyId: number, limit = 50): Promise<BabyLog[]> {
  const res = await apiClient.get<BabyLog[]>("/baby-logs", { params: { baby_id: babyId, limit } });
  return res.data ?? [];
}

export async function createLog(input: {
  baby_id: number; log_type: BabyLogType; started_at: string;
  amount?: number | null; unit?: string | null; memo?: string | null; client_uid?: string;
}): Promise<BabyLog | null> {
  const res = await apiClient.post<BabyLog>("/baby-logs", input);
  return res.data ?? null;
}

export async function listGrowth(babyId: number): Promise<BabyGrowth[]> {
  const res = await apiClient.get<BabyGrowth[]>("/baby-growth", { params: { baby_id: babyId } });
  return res.data ?? [];
}

export async function createGrowth(input: {
  baby_id: number; measured_on: string;
  height_cm?: number | null; weight_kg?: number | null; head_cm?: number | null; client_uid?: string;
}): Promise<BabyGrowth | null> {
  const res = await apiClient.post<BabyGrowth>("/baby-growth", input);
  return res.data ?? null;
}

export async function getVaccines(babyId: number): Promise<VaccineView | null> {
  const res = await apiClient.get<VaccineView>("/vaccines", { params: { baby_id: babyId } });
  return res.data ?? null;
}

export async function upsertVaccine(input: {
  baby_id: number; tpl_id: number; done_on?: string | null; client_uid?: string;
}): Promise<void> {
  await apiClient.post("/vaccines", input);
}

export const LOG_LABEL: Record<BabyLogType, { label: string; emoji: string }> = {
  feed_breast: { label: "모유", emoji: "🤱" },
  feed_bottle: { label: "분유", emoji: "🍼" },
  feed_solid: { label: "이유식", emoji: "🥣" },
  pump: { label: "유축", emoji: "🥛" },
  diaper_wet: { label: "소변", emoji: "💧" },
  diaper_dirty: { label: "대변", emoji: "💩" },
  diaper_mixed: { label: "혼합", emoji: "🚼" },
  sleep: { label: "수면", emoji: "😴" },
  bath: { label: "목욕", emoji: "🛁" },
  med: { label: "투약", emoji: "💊" },
  temperature: { label: "체온", emoji: "🌡️" },
  etc: { label: "기타", emoji: "📝" },
};

export const VACCINE_STATUS_LABEL: Record<VaccineStatus, { label: string; cls: string }> = {
  done: { label: "완료", cls: "text-emerald-600" },
  overdue: { label: "지연", cls: "text-red-600" },
  upcoming: { label: "임박", cls: "text-amber-600" },
  scheduled: { label: "예정", cls: "text-gray-400" },
};

export function babyClientUid(prefix = "web"): string {
  // getRandomValues works on plain-HTTP pages too, unlike crypto.randomUUID.
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  const random = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}
