"""JWT checks for account-wide token versions and individually revocable login sessions."""

from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from gnu_jango.users.models import Profile


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Keep the existing API's session-cookie behaviour for admin browser requests."""

    def enforce_csrf(self, request):
        return None


class SessionJWTAuthentication(JWTAuthentication):
    """Reject access tokens after their password version or refresh-token session is revoked."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        payload = validated_token.payload
        current_version = Profile.objects.filter(user_id=user.pk).values_list("token_version", flat=True).first() or 0
        try:
            token_version = int(payload.get("tv", 0))
        except (TypeError, ValueError):
            raise AuthenticationFailed("Invalid authentication token.", code="token_invalid") from None
        if token_version != current_version:
            raise AuthenticationFailed("Authentication token has been revoked.", code="token_revoked")

        session_jti = payload.get("sid")
        if session_jti:
            active_session = OutstandingToken.objects.filter(
                jti=session_jti,
                user_id=user.pk,
                expires_at__gt=timezone.now(),
                blacklistedtoken__isnull=True,
            ).exists()
            if not active_session:
                raise AuthenticationFailed("Login session has been revoked.", code="session_revoked")
        else:
            token_jti = payload.get("jti")
            if token_jti and BlacklistedToken.objects.filter(token__jti=token_jti).exists():
                raise AuthenticationFailed("Authentication token has been revoked.", code="token_revoked")
        return user
