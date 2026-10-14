"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuthStore } from "@/store/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  babyClientUid, createBaby, createLog, getVaccines, listBabies, listGrowth, listLogs,
  upsertVaccine, LOG_LABEL, VACCINE_STATUS_LABEL,
  type Baby, type BabyGrowth, type BabyLog, type BabyLogType, type VaccineView,
} from "@/services/baby";

const QUICK: BabyLogType[] = ["feed_breast", "feed_bottle", "diaper_wet", "diaper_dirty", "sleep"];
const LOG_FETCH_LIMIT = 30;
const LOG_DISPLAY_LIMIT = 12;
const GROWTH_DISPLAY_LIMIT = 8;

// 로컬(브라우저 타임존) 날짜 — toISOString()은 UTC라 KST 야간에 날짜가 하루 어긋남.
function todayYmd(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function nowSql(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function hhmm(value: string | null): string {
  if (!value) return "";
  const d = new Date(value.replace(" ", "T"));
  if (isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function BabyDashboard() {
  const { user, isInitialized } = useAuthStore();

  const [babies, setBabies] = useState<Baby[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loadingBabies, setLoadingBabies] = useState(true);

  const [logs, setLogs] = useState<BabyLog[]>([]);
  const [growth, setGrowth] = useState<BabyGrowth[]>([]);
  const [vaccines, setVaccines] = useState<VaccineView | null>(null);

  const [newName, setNewName] = useState("");
  const [newBirth, setNewBirth] = useState(todayYmd());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingTpls, setPendingTpls] = useState<Set<number>>(new Set());

  const selected = useMemo(
    () => babies.find((b) => b.baby_id === selectedId) ?? babies[0] ?? null,
    [babies, selectedId],
  );

  const loadBabies = useCallback(async () => {
    setLoadingBabies(true);
    try {
      const list = await listBabies();
      setBabies(list);
      setSelectedId((prev) => prev ?? list[0]?.baby_id ?? null);
    } finally {
      setLoadingBabies(false);
    }
  }, []);

  const reloadData = useCallback(async (babyId: number) => {
    try {
      const [lg, gr, vx] = await Promise.all([
        listLogs(babyId, LOG_FETCH_LIMIT),
        listGrowth(babyId),
        getVaccines(babyId),
      ]);
      setLogs(lg); setGrowth(gr); setVaccines(vx);
    } catch {
      setError("데이터를 새로고침하지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    if (user) void loadBabies();
  }, [user, loadBabies]);

  // 선택 아기 데이터 — 전환 시 이전 데이터 즉시 비우고, 경쟁조건(늦게 온 이전 응답이 덮어씀) 방지.
  const selectedBabyId = selected?.baby_id ?? null;
  useEffect(() => {
    if (!selectedBabyId) return;
    let alive = true;
    setLogs([]); setGrowth([]); setVaccines(null); setError(null);
    (async () => {
      try {
        const [lg, gr, vx] = await Promise.all([
          listLogs(selectedBabyId, LOG_FETCH_LIMIT),
          listGrowth(selectedBabyId),
          getVaccines(selectedBabyId),
        ]);
        if (!alive) return;
        setLogs(lg); setGrowth(gr); setVaccines(vx);
      } catch {
        if (alive) setError("데이터를 불러오지 못했습니다. 다시 시도해주세요.");
      }
    })();
    return () => { alive = false; };
  }, [selectedBabyId]);

  const addBaby = async () => {
    if (!newName.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const baby = await createBaby({
        baby_name: newName.trim(),
        baby_birth: newBirth,
        client_uid: babyClientUid("baby"),
      });
      setNewName("");
      await loadBabies();
      if (baby) setSelectedId(baby.baby_id);
    } catch {
      setError("아기 등록에 실패했습니다. 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  const quickLog = async (type: BabyLogType) => {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createLog({
        baby_id: selected.baby_id,
        log_type: type,
        started_at: nowSql(),
        client_uid: babyClientUid("log"),
      });
      await reloadData(selected.baby_id);
    } catch {
      setError("기록에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const toggleVaccine = async (tplId: number, done: boolean) => {
    if (!selected || pendingTpls.has(tplId)) return;
    const babyId = selected.baby_id;
    setPendingTpls((prev) => new Set(prev).add(tplId));
    // 낙관적 업데이트 — 즉시 UI 반영, 서버 응답으로 동기화.
    setVaccines((prev) => prev ? {
      ...prev,
      items: prev.items.map((v) =>
        v.tpl_id === tplId
          ? { ...v, status: done ? "scheduled" : "done", done_on: done ? null : todayYmd() }
          : v,
      ),
    } : prev);
    try {
      await upsertVaccine({
        baby_id: babyId,
        tpl_id: tplId,
        done_on: done ? null : todayYmd(),
        client_uid: babyClientUid("vax"),
      });
      setVaccines(await getVaccines(babyId));
    } catch {
      setVaccines(await getVaccines(babyId).catch(() => null)); // 실패 시 서버 상태로 롤백
      setError("접종 상태 변경에 실패했습니다.");
    } finally {
      setPendingTpls((prev) => {
        const next = new Set(prev);
        next.delete(tplId);
        return next;
      });
    }
  };

  // ---- 인증 ----
  if (!isInitialized) {
    return <Centered>불러오는 중…</Centered>;
  }
  if (!user) {
    return (
      <Centered>
        <div className="text-5xl mb-3">🍼</div>
        <p className="text-lg font-semibold mb-4">로그인하고 우리 아기 육아 기록을 시작하세요</p>
        <a href="/login" className="rounded-full bg-rose-500 px-6 py-3 text-white font-bold hover:bg-rose-600">
          로그인 / 회원가입
        </a>
      </Centered>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">육아수첩</h1>
        {babies.length > 0 && (
          <div className="flex gap-2">
            {babies.map((b) => (
              <button
                key={b.baby_id}
                onClick={() => setSelectedId(b.baby_id)}
                className={`rounded-full border px-3 py-1.5 text-sm font-semibold ${
                  b.baby_id === selected?.baby_id
                    ? "border-rose-500 bg-rose-100 text-rose-700"
                    : "border-gray-300 text-gray-600"
                }`}
              >
                {b.baby_sex === "f" ? "👧" : b.baby_sex === "m" ? "👦" : "👶"} {b.baby_name}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loadingBabies ? (
        <Centered>불러오는 중…</Centered>
      ) : !selected ? (
        <Card>
          <CardHeader><CardTitle>아기 등록</CardTitle></CardHeader>
          <CardContent>
            <p className="mb-4 text-sm text-gray-500">
              생일을 등록하면 모바일 앱에서 100일·돌·생일 디데이가 자동으로 만들어져요.
            </p>
            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="이름 / 태명"
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2"
              />
              <input
                type="date"
                value={newBirth}
                onChange={(e) => setNewBirth(e.target.value)}
                className="rounded-lg border border-gray-300 px-3 py-2"
              />
              <button
                onClick={addBaby}
                disabled={busy || !newName.trim()}
                className="rounded-lg bg-rose-500 px-5 py-2 font-bold text-white disabled:opacity-50"
              >
                등록
              </button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-6">
          {/* 히어로 */}
          <Card className="bg-rose-50">
            <CardContent className="py-6">
              <div className="text-lg font-bold text-rose-800">
                {selected.baby_sex === "f" ? "👧" : "👦"} {selected.baby_name}
              </div>
              <div className="mt-1 text-3xl font-extrabold text-rose-900">{selected.age_label}</div>
              <div className="mt-1 text-sm text-rose-700/80">{selected.baby_birth} 출생</div>
            </CardContent>
          </Card>

          {/* 빠른 기록 */}
          <Card>
            <CardHeader><CardTitle>빠른 기록</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-5 gap-2">
                {QUICK.map((t) => (
                  <button
                    key={t}
                    onClick={() => quickLog(t)}
                    disabled={busy}
                    className="flex flex-col items-center gap-1 rounded-xl border border-gray-200 py-3 hover:bg-gray-50 disabled:opacity-50"
                  >
                    <span className="text-2xl">{LOG_LABEL[t].emoji}</span>
                    <span className="text-xs font-semibold">{LOG_LABEL[t].label}</span>
                  </button>
                ))}
              </div>
              <div className="mt-4 divide-y">
                {logs.length === 0 && <p className="py-4 text-sm text-gray-400">아직 기록이 없어요.</p>}
                {logs.slice(0, LOG_DISPLAY_LIMIT).map((l) => (
                  <div key={l.log_id} className="flex items-center gap-3 py-2">
                    <span className="text-lg">{LOG_LABEL[l.log_type].emoji}</span>
                    <span className="flex-1 text-sm font-medium">
                      {LOG_LABEL[l.log_type].label}
                      {l.amount != null && ` · ${l.amount}${l.unit ?? ""}`}
                      {l.memo && <span className="text-gray-400"> · {l.memo}</span>}
                    </span>
                    <span className="text-xs text-gray-400">
                      {l.started_at.slice(5, 10)} {hhmm(l.started_at)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* 성장 */}
          <Card>
            <CardHeader><CardTitle>성장 기록</CardTitle></CardHeader>
            <CardContent>
              {growth.length === 0 ? (
                <p className="text-sm text-gray-400">성장 기록이 없어요. 앱에서 키·몸무게를 추가해보세요.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400">
                      <th className="py-1 font-medium">측정일</th>
                      <th className="py-1 font-medium">몸무게</th>
                      <th className="py-1 font-medium">키</th>
                      <th className="py-1 font-medium">머리둘레</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...growth].reverse().slice(0, GROWTH_DISPLAY_LIMIT).map((g) => (
                      <tr key={g.growth_id} className="border-t">
                        <td className="py-1.5">{g.measured_on}</td>
                        <td className="py-1.5">{g.weight_kg != null ? `${g.weight_kg}kg` : "—"}</td>
                        <td className="py-1.5">{g.height_cm != null ? `${g.height_cm}cm` : "—"}</td>
                        <td className="py-1.5">{g.head_cm != null ? `${g.head_cm}cm` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>

          {/* 예방접종 */}
          <Card>
            <CardHeader><CardTitle>예방접종 (한국 표준일정)</CardTitle></CardHeader>
            <CardContent>
              {vaccines && (
                <div className="mb-3 flex gap-4 text-sm">
                  <Stat n={vaccines.summary.overdue} label="지연" cls="text-red-600" />
                  <Stat n={vaccines.summary.upcoming} label="임박" cls="text-amber-700" />
                  <Stat n={vaccines.summary.scheduled} label="예정" cls="text-gray-400" />
                  <Stat n={vaccines.summary.done} label="완료" cls="text-emerald-600" />
                </div>
              )}
              <div className="divide-y">
                {(vaccines?.items ?? []).map((v) => {
                  const meta = VACCINE_STATUS_LABEL[v.status];
                  const done = v.status === "done";
                  return (
                    <label key={v.tpl_id} className="flex cursor-pointer items-center gap-3 py-2">
                      <input
                        type="checkbox"
                        checked={done}
                        disabled={pendingTpls.has(v.tpl_id)}
                        onChange={() => toggleVaccine(v.tpl_id, done)}
                        className="h-5 w-5 accent-emerald-600 disabled:opacity-50"
                      />
                      <span className="flex-1">
                        <span className="text-sm font-semibold">
                          {v.vaccine_name} <span className="text-gray-400">{v.dose_no}차</span>
                        </span>
                        <span className="block text-xs text-gray-400">{v.target_disease} · {v.due_label}</span>
                      </span>
                      <span className={`text-xs font-semibold ${meta.cls}`}>
                        {meta.label}
                        {!done && v.days_until != null &&
                          ` · ${v.days_until < 0 ? `${-v.days_until}일 지남` : v.days_until === 0 ? "오늘" : `D-${v.days_until}`}`}
                      </span>
                    </label>
                  );
                })}
              </div>
              {vaccines?.disclaimer && (
                <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
                  ⚠️ {vaccines.disclaimer}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-6 text-center text-gray-500">
      {children}
    </div>
  );
}

function Stat({ n, label, cls }: { n: number; label: string; cls: string }) {
  return (
    <div className="flex flex-col items-center">
      <span className={`text-xl font-extrabold ${cls}`}>{n}</span>
      <span className="text-xs text-gray-500">{label}</span>
    </div>
  );
}
