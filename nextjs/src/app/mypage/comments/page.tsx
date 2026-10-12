"use client";

import { useEffect, useState } from "react";
import { getMyComments } from "@/services/member";
import type { MyComment } from "@/lib/schemas";
import { g5ShortHref } from "@/lib/g5-short-url";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatDate } from "@/lib/utils";
import { sanitizeUserHtml } from "@/lib/sanitize";

export default function MyCommentsPage() {
  const [comments, setComments] = useState<MyComment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setComments(await getMyComments(30));
      } catch {
        setComments([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>내 댓글</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="py-8 text-center text-muted-foreground">로딩 중...</p>
        ) : comments.length === 0 ? (
          <p className="py-8 text-center text-muted-foreground">
            작성한 댓글이 없습니다.
          </p>
        ) : (
          <ul className="divide-y">
            {comments.map((comment) => (
              <li
                key={`${comment.bo_table}-${comment.wr_id}`}
                className="py-3"
              >
                <a
                  href={g5ShortHref(`/boards/${comment.bo_table}/${comment.wr_parent}`)}
                  className="transition-colors hover:text-primary"
                >
                  <div
                    className="line-clamp-2 text-sm"
                    dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(comment.wr_content) }}
                  />
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <span>{comment.bo_subject || comment.bo_table}</span>
                    <span>{formatDate(comment.wr_datetime)}</span>
                  </div>
                </a>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
