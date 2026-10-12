from .models import Comment, Post
from gnu_jango.users.point_ledger import delete_point, post_point_id

# 게시판 리스트에서 게시물 들을 삭제
class Delete_all_posts:

    def __init__(self):
        self.count_write = 0
        self.count_comment = 0
        self.board = None

    def get_descendants(self, post, board):
        thread_id = post.wr_parent or post.pk
        replies = Post.objects.filter(board=board, wr_parent=thread_id).exclude(
            wr_reply=""
        )

        if post.wr_reply:
            replies = replies.filter(wr_reply__startswith=post.wr_reply).exclude(
                wr_reply=post.wr_reply
            )

        descendants = list(replies.exclude(pk=post.pk))
        return sorted(
            descendants,
            key=lambda row: (len(row.wr_reply or ""), row.wr_reply or "", row.pk),
        )

    def check_delete(self, post, board, descendants=None):

        if not post:
            return {}

        self.board = board
        if descendants is None:
            descendants = self.get_descendants(post, board)
        deleted_ids = []

        # 답글이 먼저 삭제되도록 깊이 우선으로 역순 처리한다.
        for row in reversed(descendants):
            self.etc_check(row, board)
            if self.sql_delete(row.pk):
                self.count_write += 1
                deleted_ids.append(row.pk)

        return {
            "count_write": self.count_write,
            "count_comment": self.count_comment,
            "deleted_ids": deleted_ids,
        }

    def etc_check(self, row, board):

        # 원글 포인트 삭제 (Gnuboard5 delete.php: 글쓰기/답변 포인트를 회수)
        if row.user_id:
            delete_point(row.user, board.bo_table, post_point_id(row), "쓰기")

        # 업로드된 파일이 있다면 파일삭제

        # 에디터 썸네일 삭제

        # 스크랩 삭제

        # 코멘트 및 코멘트 포인트 삭제
        for comment in Comment.objects.filter(post_id=row.id).select_related("user"):
            if comment.user_id:
                delete_point(comment.user, board.bo_table, comment.id, "댓글")
        self.sql_comment_delete(row.id)

    # 글 삭제
    def sql_delete(self, post_id):
        result = Post.objects.filter(pk=post_id).delete()

        return result

    # 댓글 삭제
    def sql_comment_delete(self, post_id):
        pass
