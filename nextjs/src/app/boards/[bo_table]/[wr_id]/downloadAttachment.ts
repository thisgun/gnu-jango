import { api } from "@/lib/api";
import { localizeApiMessage } from "@/lib/api-messages";
import { toastError } from "@/lib/toast";

/** True for the API's checked download links (other attachment URLs open normally). */
export function isCheckedDownloadUrl(url: string): boolean {
  return /\/api\/v1\/boards\/[^/]+\/\d+\/files\/\d+\/download$/.test(url);
}

// Same credentials as the API client: the session cookie plus the bearer token, refreshed once
// when it has expired.
async function fetchWithAuth(url: string): Promise<Response> {
  const request = (token: string | null) =>
    fetch(url, { credentials: "include", headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const response = await request(api.getToken());
  if (response.status !== 401 || !api.getRefreshToken()) return response;
  const refreshed = await api.refreshAccessToken();
  return refreshed ? request(refreshed) : response;
}

// Gnuboard5 download.php asks before a download that costs points and refuses one the member
// cannot afford. The checked download endpoint answers JSON on refusal, so the file is fetched
// here and a refusal is shown as a message instead of a raw JSON page.
export async function downloadAttachment(
  url: string,
  filename: string,
  downloadPoint: number
): Promise<void> {
  if (
    downloadPoint < 0 &&
    !window.confirm(
      `${filename} 파일을 다운로드 하시면 포인트가 차감(${downloadPoint.toLocaleString()}점)됩니다.\n` +
        "포인트는 게시물당 한번만 차감되며 다음에 다시 다운로드 하셔도 중복하여 차감하지 않습니다.\n" +
        "그래도 다운로드 하시겠습니까?"
    )
  ) {
    return;
  }

  try {
    const response = await fetchWithAuth(url);
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const message =
        body && typeof body === "object" && "message" in body && typeof body.message === "string"
          ? localizeApiMessage(body.message)
          : "파일을 내려받지 못했습니다.";
      toastError(message);
      return;
    }
    const objectUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename || "download";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  } catch {
    toastError("파일을 내려받지 못했습니다. 잠시 후 다시 시도해 주세요.");
  }
}
