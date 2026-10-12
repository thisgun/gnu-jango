"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { toastSuccess, toastError } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { PlusIcon, PencilIcon, TrashIcon } from "lucide-react";
import type { Board } from "@/lib/types";

export default function AdminBoardsPage() {
  const router = useRouter();
  const [boards, setBoards] = useState<Board[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newBoard, setNewBoard] = useState({ bo_table: "", bo_subject: "" });
  const [creating, setCreating] = useState(false);

  async function fetchBoards() {
    setLoading(true);
    try {
      const res = await api.get<Board[]>("/admin/boards");
      if (res.data) setBoards(res.data);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchBoards();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newBoard.bo_table || !newBoard.bo_subject) {
      toastError("게시판 ID와 제목을 입력하세요.");
      return;
    }
    setCreating(true);
    try {
      await api.post("/admin/boards", newBoard);
      toastSuccess("게시판이 생성되었습니다.");
      setDialogOpen(false);
      setNewBoard({ bo_table: "", bo_subject: "" });
      fetchBoards();
    } catch {
      toastError("게시판 생성에 실패했습니다.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(boTable: string) {
    if (!confirm(`'${boTable}' 게시판을 삭제하시겠습니까?`)) return;
    try {
      await api.delete(`/admin/boards/${boTable}`);
      toastSuccess("삭제되었습니다.");
      fetchBoards();
    } catch {
      toastError("삭제에 실패했습니다.");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">게시판관리</h1>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <PlusIcon className="size-4 mr-1" />
              새 게시판
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>새 게시판 생성</DialogTitle>
              <DialogDescription>
                게시판 ID와 제목을 입력하세요.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="bo_table">게시판 ID</Label>
                <Input
                  id="bo_table"
                  placeholder="영문, 숫자, 언더스코어만"
                  value={newBoard.bo_table}
                  onChange={(e) =>
                    setNewBoard((prev) => ({
                      ...prev,
                      bo_table: e.target.value,
                    }))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_subject">게시판 제목</Label>
                <Input
                  id="bo_subject"
                  placeholder="게시판 이름"
                  value={newBoard.bo_subject}
                  onChange={(e) =>
                    setNewBoard((prev) => ({
                      ...prev,
                      bo_subject: e.target.value,
                    }))
                  }
                />
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setDialogOpen(false)}
                >
                  취소
                </Button>
                <Button type="submit" disabled={creating}>
                  {creating ? "생성 중..." : "생성"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">게시판 목록</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">로딩 중...</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>게시판 ID</TableHead>
                  <TableHead>제목</TableHead>
                  <TableHead>스킨</TableHead>
                  <TableHead>글 수</TableHead>
                  <TableHead>댓글 수</TableHead>
                  <TableHead className="text-right">관리</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {boards.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="text-center text-muted-foreground"
                    >
                      게시판이 없습니다.
                    </TableCell>
                  </TableRow>
                ) : (
                  boards.map((board) => (
                    <TableRow key={board.bo_table}>
                      <TableCell className="font-medium">
                        {board.bo_table}
                      </TableCell>
                      <TableCell>{board.bo_subject}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {board.bo_skin}
                      </TableCell>
                      <TableCell>{board.bo_count_write}</TableCell>
                      <TableCell>{board.bo_count_comment}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Edit board ${board.bo_table}`}
                            onClick={() =>
                              runtimeRouterPush(router, `/admin/boards/${board.bo_table}`)
                            }
                          >
                            <PencilIcon className="size-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Delete board ${board.bo_table}`}
                            onClick={() => handleDelete(board.bo_table)}
                          >
                            <TrashIcon className="size-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
