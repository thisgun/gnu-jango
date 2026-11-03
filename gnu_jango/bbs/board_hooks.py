"""Plugin hooks for posts and comments (gnu_jango.plugins.hooks), sent once the write commits: a post
that is rolled back (a failed upload, a point shortage) sends nothing.

- ``bbs.post.created`` (post, user, request): a post or reply was written through the board API.
  ``user`` is None for a guest.
- ``bbs.comment.created`` (comment, user, request): a comment or reply comment was written.
"""

from django.db import transaction

from gnu_jango.plugins import hooks


def post_created(post, request):
    transaction.on_commit(lambda: hooks.emit("bbs.post.created", post=post, user=post.user, request=request))


def comment_created(comment, request):
    transaction.on_commit(
        lambda: hooks.emit("bbs.comment.created", comment=comment, user=comment.user, request=request)
    )
