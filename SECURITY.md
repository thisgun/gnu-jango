# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
"Report a vulnerability" (private vulnerability reporting) on this repository, or
contact the maintainers privately through the address listed on the repository
profile. Include the affected URL or file, steps to reproduce and the impact.
We aim to acknowledge reports within a week.

## Supported versions

Only the latest commit on the default branch receives fixes.

## Deployment checklist

- Set `DJANGO_SETTINGS_MODULE` to the production settings, `DEBUG` off, and a long
  random `SECRET_KEY` from the environment (the app refuses to start without it).
- Set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `TRUSTED_PROXY_COUNT` to match the
  real proxy chain (client IPs, poll limits and throttles depend on it).
- Keep payment (PG), social login and identity verification keys only in the
  environment; never commit them. `.env.example` lists the variables.
- Configure SMTP: password reset and e-mail certification are mail-only.
- Serve `data/` and `media/` through the app or a web server rule that refuses
  active content (`.php`, `.html`, `.svg`, ...), as Gnuboard5's `data/.htaccess` does.
- Schedule `expire_pending_payment_orders --apply` and `expire_toss_vbank_orders --apply`.
