from django.urls import include, path

from gnu_jango.api import internal_cron, v1_auth

# Only the v1 API and the Gnuboard5-compatible social login / identity verification bridges are
# served. The pre-v1 API (user/, post/, board/, articles, main/, config/, menu/) was removed: no
# client used it and its sign-up had no captcha.
urlpatterns = [
    path("v1/", include("gnu_jango.api.v1_urls")),
    # Scheduled maintenance for HTTP schedulers (Vercel Cron); 404 unless CRON_SECRET is set.
    path("internal/cron", internal_cron.cron_view, name="internal-cron"),
    path("social/start.php", v1_auth.social_start_view, name="social-start"),
    path("social/signup.php", v1_auth.social_signup_start_view, name="social-signup"),
    path("social/callback.php", v1_auth.social_callback_view, name="social-callback"),
    path("social/finish.php", v1_auth.social_callback_view, name="social-finish"),
    path("cert/inicis_start.php", v1_auth.cert_inicis_start_view, name="cert-inicis-start"),
    path("cert/inicis_result.php", v1_auth.cert_inicis_result_view, name="cert-inicis-result"),
    path("cert/kcp_start.php", v1_auth.cert_kcp_start_view, name="cert-kcp-start"),
    path("cert/kcp_result.php", v1_auth.cert_kcp_result_view, name="cert-kcp-result"),
    path("cert/kcp_v2_start.php", v1_auth.cert_kcp_v2_start_view, name="cert-kcp-v2-start"),
    path("cert/kcp_v2_result.php", v1_auth.cert_kcp_v2_result_view, name="cert-kcp-v2-result"),
]
