"""Plugin hooks for members (gnu_jango.plugins.hooks).

- ``member.joined`` (user, request): a member signed up (password or social sign-up), sent once the
  account commits. A member who must still certify the e-mail address is sent too: the account exists.
- ``member.visited`` is sent by gnu_jango.api.v1_auth.member_visited.
"""

from django.db import transaction

from gnu_jango.plugins import hooks


def member_joined(user, request):
    transaction.on_commit(lambda: hooks.emit("member.joined", user=user, request=request))
