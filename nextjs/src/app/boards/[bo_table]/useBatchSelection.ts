"use client";

import { useCallback, useState } from "react";
import { apiClient } from "@/lib/api";
import { toastSuccess, toastError } from "@/lib/toast";

/**
 * 관리자 일괄 선택(선택 삭제). 목록형 표와 갤러리 격자가 같은 상태를 쓴다.
 * 지운 글은 다시 불러오지 않고 deletedIds 로 화면에서만 걷는다. 답글까지 함께 지워지면(deleted_ids)
 * 그 글들도 걷고, 지우지 못한 글은 선택된 채로 남겨 다시 누르기만 하면 되게 한다.
 * 복사 · 이동(그누보드 move.php)은 Django API 에 아직 없어 두지 않는다.
 */
export function useBatchSelection(boTable: string, ids: number[], isAdmin: boolean) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [deletedIds, setDeletedIds] = useState<Set<number>>(new Set());

  const visibleIds = Array.from(new Set(ids)).filter((id) => !deletedIds.has(id));
  const allSelected = visibleIds.length > 0 && selected.size === visibleIds.length;

  const toggleOne = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(visibleIds));
  };

  const clearSelection = () => setSelected(new Set());

  const handleBatchDelete = useCallback(async () => {
    if (selected.size === 0) return;
    if (!confirm(`선택한 ${selected.size}개의 게시글을 삭제하시겠습니까?`)) return;

    setDeleting(true);
    const selectedIds = [...selected];
    const deletedInBatch = new Set<number>();
    const failedRequests = new Set<number>();
    try {
      for (const wrId of selectedIds) {
        if (deletedInBatch.has(wrId)) continue;

        try {
          const response = await apiClient.delete<{ deleted_ids?: number[] }>(
            `/posts/${boTable}/${wrId}`
          );
          for (const deletedId of response.data?.deleted_ids ?? [wrId]) {
            deletedInBatch.add(deletedId);
          }
          deletedInBatch.add(wrId);
        } catch {
          failedRequests.add(wrId);
        }
      }

      setDeletedIds((prev) => new Set([...prev, ...deletedInBatch]));
      // Keep only the posts that were not removed selected, so a retry is one click.
      setSelected(new Set(selectedIds.filter((id) => !deletedInBatch.has(id))));

      const failedCount = [...failedRequests].filter((id) => !deletedInBatch.has(id)).length;
      if (failedCount > 0) {
        const deletedSelectedCount = selectedIds.length - failedCount;
        toastError(
          deletedSelectedCount > 0
            ? `${deletedSelectedCount}개 선택 글은 삭제했고 ${failedCount}개 선택 글은 삭제하지 못했습니다. 삭제하지 못한 글은 선택된 상태로 남아 있습니다.`
            : "선택한 게시글을 삭제하지 못했습니다. 선택은 유지되므로 다시 시도할 수 있습니다."
        );
      } else if (deletedInBatch.size > 0) {
        toastSuccess(`${deletedInBatch.size}개의 게시글이 삭제되었습니다.`);
      }
    } finally {
      setDeleting(false);
    }
  }, [selected, boTable]);

  return {
    isAdmin,
    selected,
    deletedIds,
    deleting,
    allSelected,
    visibleIds,
    toggleOne,
    toggleAll,
    clearSelection,
    handleBatchDelete,
  };
}
