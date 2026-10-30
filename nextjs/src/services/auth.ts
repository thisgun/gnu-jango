import { apiClient } from "@/lib/api";
import { validateApiData } from "@/lib/api-response";
import {
  authAvailabilitySchema,
  passwordResetRequestSchema,
  type AuthAvailability,
} from "@/lib/schemas";

const DEFAULT_AVAILABILITY: AuthAvailability = {
  available: false,
  message: "",
};

export interface RegisterPayload {
  mb_id?: string;
  mb_password?: string;
  mb_password_re?: string;
  mb_nick: string;
  mb_name: string;
  mb_email: string;
  captcha_key?: string;
  agree_terms: boolean;
  agree_privacy: boolean;
  // 정보 메일 수신 동의 (mb_mailling) — 고르지 않으면 받지 않는다.
  mb_mailling?: number;
  mb_recommend?: string;
  // 본인인증(KG 이니시스 간편인증) 결과 — gnuboard5 admin cf_cert_use=1 일 때 필수.
  cert_type?: string;
  cert_no?: string;
  mb_hp?: string;
  mb_birth?: string;
  mb_adult?: number;
  social_signup_ticket?: string;
}

export interface RegisterResponse {
  token?: string;
  refresh_token?: string;
  expires_in?: number;
  member?: Record<string, string | number | undefined>;
  user?: Record<string, string | number | undefined>;
  requires_email_verification?: boolean;
  mb_id?: string;
  message?: string;
  registration_result_url?: string;
}

export interface PasswordResetRequestPayload {
  mb_id: string;
  mb_email: string;
}

export interface PasswordResetCertRequestPayload {
  cert_type: string;
  cert_no: string;
}

export interface PasswordResetPayload {
  reset_token: string;
  mb_password: string;
  mb_password_re: string;
}

export async function checkMemberId(mbId: string): Promise<AuthAvailability> {
  const response = await apiClient.get<unknown>("/auth/check-id", {
    params: { mb_id: mbId },
  });

  return validateApiData(response.data, authAvailabilitySchema, DEFAULT_AVAILABILITY);
}

export async function checkMemberEmail(
  mbEmail: string
): Promise<AuthAvailability> {
  const response = await apiClient.get<unknown>("/auth/check-email", {
    params: { mb_email: mbEmail },
  });

  return validateApiData(response.data, authAvailabilitySchema, DEFAULT_AVAILABILITY);
}

export function registerMember(payload: RegisterPayload) {
  return apiClient.post<RegisterResponse>("/auth/register", payload);
}

export interface RegisterResult {
  mb_id: string;
  mb_name: string;
  mb_nick: string;
  mb_email: string;
  mb_datetime: string;
  requires_email_verification: boolean;
}

export async function getRegisterResult(): Promise<RegisterResult> {
  const response = await apiClient.get<RegisterResult>("/auth/register-result");
  if (!response.data) {
    throw new Error("회원가입 완료 정보를 찾을 수 없습니다.");
  }
  return response.data;
}

/**
 * Ask for a reset link. The server mails it and answers the same way whether or not the id and
 * e-mail match, so the returned text is only the notice to show.
 */
export async function requestPasswordReset(
  payload: PasswordResetRequestPayload
): Promise<string> {
  const response = await apiClient.post<{ message?: string }>("/auth/password-reset", {
    step: "request",
    ...payload,
  });
  return (
    response.data?.message ||
    "입력하신 정보와 일치하는 회원이 있으면 비밀번호 재설정 메일을 보냈습니다."
  );
}

export async function requestPasswordResetByCert(
  payload: PasswordResetCertRequestPayload
): Promise<string> {
  const response = await apiClient.post<unknown>("/auth/password-reset", {
    step: "cert_request",
    ...payload,
  });
  const parsed = validateApiData(response.data, passwordResetRequestSchema, {
    reset_token: "",
  });

  if (!parsed.reset_token) {
    throw new Error("비밀번호 재설정 토큰을 받지 못했습니다.");
  }

  return parsed.reset_token;
}

export interface EmailCertifyResult {
  certified?: boolean;
  mb_id?: string;
  message?: string;
}

/** 메일인증 링크 처리 (bbs/email_certify.php) — 링크는 한 번만, 유효시간 안에만 쓸 수 있다. */
export async function certifyEmail(mbId: string, token: string): Promise<string> {
  const response = await apiClient.post<EmailCertifyResult>("/auth/email-certify", {
    mb_id: mbId,
    token,
  });
  return response.data?.message || "메일인증 처리를 완료 하였습니다.";
}

export interface ResendCertifyPayload {
  mb_id: string;
  mb_password: string;
  // 다른 주소로 바꿔 인증받으려면 새 주소 (bbs/register_email_update.php).
  mb_email?: string;
}

/** 인증 메일 다시 보내기 — 로그인이 막힌 미인증 회원이 아이디 · 비밀번호로 부른다. */
export async function resendCertifyEmail(payload: ResendCertifyPayload): Promise<string> {
  const response = await apiClient.post<{ message?: string }>("/auth/email-certify/resend", payload);
  return response.data?.message || "인증메일을 다시 보내 드렸습니다.";
}

export function resetPassword(payload: PasswordResetPayload) {
  return apiClient.post("/auth/password-reset", {
    step: "reset",
    ...payload,
  });
}
