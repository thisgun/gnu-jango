import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gnu_jango.api import v1_auth, v1_shop
from gnu_jango.shop import pg_settings


# A check for something the site does not use (a PG nobody picked, a social login that is off,
# certification that is off): reported, but never a production gap.
UNUSED = "unused"

LEGACY_PAYMENT_PROVIDERS = [
    ("kcp", "NHN KCP"),
    ("kcp_v2", "NHN KCP V2"),
    ("inicis", "KG Inicis"),
    ("nicepay", "NicePay"),
    ("naverpay", "Naver Pay"),
    ("kakaopay", "KakaoPay"),
    ("samsungpay", "Samsung Pay"),
]

LEGACY_SOCIAL_PROVIDERS = []


def setting_value(name):
    value = getattr(settings, name, "")
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def has_setting(name):
    return bool(setting_value(name))


def namespaced_config_name(name):
    return f"Config.{name}" if name else ""


def setting_or_config_label(setting_name, config_name):
    names = [name for name in (setting_name, namespaced_config_name(config_name)) if name]
    return " or ".join(names)


def check_item(name, label, status, *, missing=None, details=None, action=""):
    return {
        "name": name,
        "label": label,
        "status": status,
        "missing": missing or [],
        "details": details or {},
        "action": action,
    }


def unused_item(name, label, *, details=None):
    return check_item(name, label, UNUSED, details=details)


def adapter_routes(adapter_config, provider):
    return bool(adapter_config["enabled"] and provider in set(adapter_config["providers"]))


def chosen_payment_provider(rows, toss_config):
    """The PG the site picked, keyed or not: SHOP_PAYMENT_PROVIDER, else the saved admin
    결제대행사 (de_pg_service), else Toss when Toss keys exist. "" means bank transfer only."""
    env_provider = pg_settings.env_payment_provider()
    if env_provider:
        return env_provider
    if pg_settings.PG_SERVICE_FIELD in rows:
        service = pg_settings.admin_pg_service(rows)
        return "" if service == pg_settings.PG_SERVICE_NONE else service
    return "toss" if toss_config["client_key"] or toss_config["has_secret_key"] else ""


class Command(BaseCommand):
    help = "Audit PG, social OAuth, and identity-verification readiness for Gnuboard5-grade production parity."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary.")
        parser.add_argument(
            "--fail-on-missing",
            action="store_true",
            help="Exit with an error when required production-readiness gaps remain.",
        )

    def handle(self, *args, **options):
        audit = {
            "payment": self.audit_payment(),
            "social_oauth": self.audit_social_oauth(),
            "identity_verification": self.audit_identity_verification(),
        }
        audit["summary"] = self.summarize(audit)

        if options["json"]:
            self.stdout.write(json.dumps(audit, ensure_ascii=False, indent=2))
        else:
            self.print_summary(audit)

        if options["fail_on_missing"] and not audit["summary"]["production_ready"]:
            summary = audit["summary"]
            raise CommandError(
                "External integrations are not production-ready "
                f"(missing_settings={summary['missing_settings']}, "
                f"disabled={summary['disabled']}, blocked={summary['blocked']})."
            )

    def audit_payment(self):
        rows = pg_settings.stored_rows()
        toss_config = v1_shop.toss_payment_config(rows=rows)
        nicepay_config = pg_settings.nicepay_payment_config(rows)
        adapter_config = v1_shop.payment_adapter_config()
        chosen = chosen_payment_provider(rows, toss_config)
        # The adapter is in use once any of its settings is there, or when the chosen PG has no
        # native Django flow (everything but Toss and NICEPAY goes through it).
        adapter_in_use = bool(
            adapter_config["base_url"]
            or adapter_config["has_secret"]
            or (chosen in v1_shop.PAYMENT_ADAPTER_PROVIDERS and chosen != "nicepay")
        )
        if chosen == "nicepay" and not adapter_routes(adapter_config, "nicepay"):
            nicepay = self.audit_native_nicepay(nicepay_config)
        else:
            nicepay = unused_item("nicepay", "NICEPAY server approval")
        if adapter_in_use:
            callback_items = self.audit_payment_callbacks()
            adapter = self.audit_payment_adapter(adapter_config)
            operations = [
                self.audit_payment_operation("settlement_reconciliation", "Provider-authoritative settlement reconciliation", adapter_config),
                self.audit_payment_operation("tax_cash_receipts", "Tax invoice and cash receipt provider parity", adapter_config),
            ]
        else:
            callback_items = {
                "callback_secret": unused_item("payment_callback_secret", "PG callback shared secret"),
                "callback_hmac_signature": unused_item("payment_callback_hmac_signature", "PG callback HMAC-SHA256 signature"),
            }
            adapter = unused_item("payment_adapter_delegation", "Provider-verified PG adapter delegation")
            operations = [
                unused_item("settlement_reconciliation", "Provider-authoritative settlement reconciliation"),
                unused_item("tax_cash_receipts", "Tax invoice and cash receipt provider parity"),
            ]

        return {
            "active_provider": v1_shop.configured_payment_provider(
                rows=rows, toss_config=toss_config, nicepay_config=nicepay_config
            ),
            "chosen_provider": chosen or "bank",
            **callback_items,
            "toss": self.audit_toss(toss_config) if chosen == "toss" else unused_item("toss", "Toss Payments server confirmation"),
            "nicepay": nicepay,
            "adapter_delegation": adapter,
            "legacy_pg_parity": [
                self.audit_legacy_pg_provider(provider, label, adapter_config, chosen=chosen, nicepay=nicepay)
                for provider, label in LEGACY_PAYMENT_PROVIDERS
            ],
            "operations": operations,
        }

    def audit_payment_callbacks(self):
        return {
            "callback_secret": check_item(
                "payment_callback_secret",
                "PG callback shared secret",
                "ready" if has_setting("SHOP_PAYMENT_CALLBACK_SECRET") else "missing",
                missing=[] if has_setting("SHOP_PAYMENT_CALLBACK_SECRET") else ["SHOP_PAYMENT_CALLBACK_SECRET"],
                details={"endpoint_enabled": has_setting("SHOP_PAYMENT_CALLBACK_SECRET")},
                action="Set SHOP_PAYMENT_CALLBACK_SECRET before exposing PG callback URLs.",
            ),
            "callback_hmac_signature": check_item(
                "payment_callback_hmac_signature",
                "PG callback HMAC-SHA256 signature",
                "ready" if has_setting("SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET") else "missing",
                missing=[] if has_setting("SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET") else ["SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET"],
                details={
                    "enabled": has_setting("SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET"),
                    "payload": "sha256(canonical provider/order_id/amount/transaction_id/success JSON)",
                },
                action="Set SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET and send X-Gnujango-Payment-Signature from the PG adapter or webhook proxy.",
            ),
        }

    def audit_toss(self, toss_config):
        toss_missing = []
        if not toss_config["client_key"]:
            toss_missing.append("SHOP_TOSS_CLIENT_KEY")
        if not toss_config["has_secret_key"]:
            toss_missing.append("SHOP_TOSS_SECRET_KEY")
        return check_item(
            "toss",
            "Toss Payments server confirmation",
            "ready" if not toss_missing else "missing",
            missing=toss_missing,
            details={
                "enabled": toss_config["enabled"],
                "has_client_key": bool(toss_config["client_key"]),
                "has_secret_key": bool(toss_config["has_secret_key"]),
                "api_base_url": toss_config["api_base_url"],
                "is_test_mode": toss_config["is_test_mode"],
            },
            action="Set Toss client/secret keys from the live or test merchant contract.",
        )

    def audit_native_nicepay(self, nicepay_config):
        """NICEPAY runs natively in Django: the server approves with the MerchantKey and checks
        the response signature, so it only needs the MID/MerchantKey pair of the selected mode."""
        prefix = "SHOP_NICEPAY_TEST_" if nicepay_config["selected_mode"] == "test" else "SHOP_NICEPAY_"
        ready = nicepay_config["enabled"]
        return check_item(
            "nicepay",
            "NICEPAY server approval",
            "ready" if ready else "missing",
            missing=[] if ready else [f"{prefix}MID", f"{prefix}MERCHANT_KEY"],
            details={
                "key_status": nicepay_config["key_status"],
                "source": nicepay_config["source"],
                "is_test_mode": nicepay_config["is_test_mode"],
            },
            action="" if ready else "Set the NICEPAY MID and MerchantKey of the selected mode in the environment or the admin 결제설정.",
        )

    def audit_payment_adapter(self, adapter_config):
        missing = []
        if not adapter_config["base_url"]:
            missing.append("SHOP_PAYMENT_ADAPTER_BASE_URL")
        if not adapter_config["has_secret"]:
            missing.append("SHOP_PAYMENT_ADAPTER_SECRET")
        status = "ready" if not missing else "missing"
        return check_item(
            "payment_adapter_delegation",
            "Provider-verified PG adapter delegation",
            status,
            missing=missing,
            details={
                "enabled": adapter_config["enabled"],
                "base_url_configured": bool(adapter_config["base_url"]),
                "has_secret": adapter_config["has_secret"],
                "providers": adapter_config["providers"],
            },
            action="Set SHOP_PAYMENT_ADAPTER_BASE_URL and SHOP_PAYMENT_ADAPTER_SECRET to a verified PG adapter that validates provider signatures/decrypt payloads before Django marks orders paid.",
        )

    def audit_legacy_pg_provider(self, provider, label, adapter_config, *, chosen, nicepay):
        if provider == "nicepay" and nicepay["status"] != UNUSED:
            return check_item(
                provider,
                label,
                nicepay["status"],
                missing=nicepay["missing"],
                details={
                    "native_signature_verification": True,
                    "adapter_signature_verification": False,
                    "provider_reconciliation": False,
                    "adapter_delegation": False,
                },
                action=nicepay["action"],
            )
        if provider != chosen and not adapter_routes(adapter_config, provider):
            return unused_item(provider, label)
        missing = []
        if not adapter_config["base_url"]:
            missing.append("SHOP_PAYMENT_ADAPTER_BASE_URL")
        if not adapter_config["has_secret"]:
            missing.append("SHOP_PAYMENT_ADAPTER_SECRET")
        if provider not in set(adapter_config["providers"]):
            missing.append("SHOP_PAYMENT_ADAPTER_PROVIDERS")
        status = "delegated" if not missing and adapter_config["enabled"] else "missing"
        return check_item(
            provider,
            label,
            status,
            missing=missing,
            details={
                "native_signature_verification": False,
                "adapter_signature_verification": status == "delegated",
                "provider_reconciliation": False,
                "adapter_delegation": status == "delegated",
            },
            action=(
                "Configure the verified PG adapter for this provider, or implement the provider SDK/API directly in Django."
                if status != "delegated"
                else ""
            ),
        )

    def audit_payment_operation(self, name, label, adapter_config):
        missing = []
        if not adapter_config["base_url"]:
            missing.append("SHOP_PAYMENT_ADAPTER_BASE_URL")
        if not adapter_config["has_secret"]:
            missing.append("SHOP_PAYMENT_ADAPTER_SECRET")
        status = "delegated" if not missing and adapter_config["enabled"] else "missing"
        return check_item(
            name,
            label,
            status,
            missing=missing,
            details={
                "native_provider_api_implemented": False,
                "adapter_delegation": status == "delegated",
                "management_command": "reconcile_payment_adapter",
            },
            action=(
                "Configure the verified PG adapter, then run manage.py reconcile_payment_adapter --apply for reconciliation and receipt checks."
                if status != "delegated"
                else ""
            ),
        )

    def audit_social_oauth(self):
        providers = {}
        for provider_name in ("naver", "kakao", "google", "facebook", "twitter", "payco"):
            providers[provider_name] = self.audit_primary_social_provider(provider_name)

        origin_ready = bool(setting_value("SOCIAL_APP_BASE_URL") or setting_value("SOCIAL_ALLOWED_REDIRECT_ORIGINS"))
        social_in_use = any(item["status"] != UNUSED for item in providers.values())
        return {
            "frontend_origin": unused_item("social_frontend_origin", "Hosted frontend redirect origin")
            if not social_in_use
            else check_item(
                "social_frontend_origin",
                "Hosted frontend redirect origin",
                "ready" if origin_ready else "missing",
                missing=[] if origin_ready else ["SOCIAL_APP_BASE_URL or SOCIAL_ALLOWED_REDIRECT_ORIGINS"],
                details={
                    "has_app_base_url": bool(setting_value("SOCIAL_APP_BASE_URL")),
                    "allowed_redirect_origins": setting_value("SOCIAL_ALLOWED_REDIRECT_ORIGINS"),
                },
                action="Set SOCIAL_APP_BASE_URL to the Vercel URL and add allowed origins when multiple domains are used.",
            ),
            "providers": providers,
            "legacy_provider_parity": [
                check_item(
                    provider,
                    label,
                    "blocked",
                    details={"oauth_flow_implemented": False},
                    action="Add provider OAuth URLs, token exchange, profile normalization, tests, and admin configuration mapping.",
                )
                for provider, label in LEGACY_SOCIAL_PROVIDERS
            ],
        }

    def audit_primary_social_provider(self, provider_name):
        spec = v1_auth.SOCIAL_PROVIDER_SPECS[provider_name]
        provider_config = v1_auth._provider_config(provider_name)
        client_id = v1_auth._setting_value(spec.get("setting_client_id", "")) or v1_auth._config_value(
            spec.get("config_client_id", "")
        )
        client_secret = v1_auth._setting_value(spec.get("setting_secret", "")) or v1_auth._config_value(
            spec.get("config_secret", "")
        )
        service_provider_code = v1_auth._setting_value(spec.get("setting_service_provider_code", ""))
        # Turned on: the server sets the client id, or the admin switched social login on and the
        # 서비스 목록 (empty = every provider) includes this one. Same rule as v1_auth._provider_config.
        service_list = v1_auth._split_provider_list(v1_auth._config_value("cf_social_servicelist", ""))
        turned_on = bool(v1_auth._setting_value(spec.get("setting_client_id", ""))) or (
            v1_auth._truthy(v1_auth._config_value("cf_social_login_use", "0"))
            and (not service_list or provider_name in service_list)
        )
        if not turned_on:
            return unused_item(provider_name, spec.get("label", provider_name.title()))

        missing = []
        if not client_id:
            missing.append(setting_or_config_label(spec.get("setting_client_id", ""), spec.get("config_client_id", "")))
        if spec.get("requires_secret", False) and not client_secret:
            missing.append(setting_or_config_label(spec.get("setting_secret", ""), spec.get("config_secret", "")))
        if spec.get("requires_service_provider_code", False) and not service_provider_code:
            missing.append(spec.get("setting_service_provider_code", "SOCIAL_PAYCO_SERVICE_PROVIDER_CODE"))

        if missing:
            status = "missing"
        elif provider_config and provider_config["enabled"]:
            status = "ready"
        else:
            status = "disabled"

        return check_item(
            provider_name,
            spec.get("label", provider_name.title()),
            status,
            missing=missing,
            details={
                "has_client_id": bool(client_id),
                "has_client_secret": bool(client_secret),
                "requires_secret": bool(spec.get("requires_secret", False)),
                "has_service_provider_code": bool(service_provider_code),
                "requires_service_provider_code": bool(spec.get("requires_service_provider_code", False)),
                "enabled": bool(provider_config and provider_config["enabled"]),
            },
            action=(
                "Set OAuth credentials and enable the provider in imported Config rows or environment settings."
                if status != "ready"
                else ""
            ),
        )

    def audit_identity_verification(self):
        config = v1_auth._cert_config_payload()
        if not config["enabled"]:
            return {
                "configuration": unused_item(
                    "cert_configuration",
                    "Gnuboard5 identity-verification provider configuration",
                    details={"enabled": False, "mode": config["mode"]},
                ),
                "frontend_origin": unused_item("cert_frontend_origin", "Certification popup postMessage origin"),
                "adapter_delegation": unused_item(
                    "cert_adapter_delegation", "Existing Gnuboard5/PHP certification adapter delegation"
                ),
                "provider_verification": unused_item(
                    "cert_provider_result_verification", "Provider result decrypt/signature verification"
                ),
            }
        adapter_base_url = setting_value("GNUBOARD_CERT_ADAPTER_BASE_URL")
        enabled_methods = [name for name in ("simple", "hp", "ipin") if config.get(name)]
        origin_ready = bool(
            setting_value("GNUBOARD_CERT_APP_BASE_URL")
            or setting_value("GNUBOARD_CERT_ALLOWED_ORIGINS")
            or setting_value("SOCIAL_APP_BASE_URL")
        )

        if not enabled_methods:
            config_status = "missing"
            config_missing = [
                "GNUBOARD_CERT_SIMPLE or Config.cf_cert_simple",
                "GNUBOARD_CERT_HP or Config.cf_cert_hp",
                "GNUBOARD_CERT_IPIN or Config.cf_cert_ipin",
            ]
        else:
            config_status = "ready"
            config_missing = []

        adapter_status = "ready" if adapter_base_url else "missing"

        if adapter_base_url:
            provider_verification_status = "delegated"
            provider_verification_action = ""
        else:
            provider_verification_status = "blocked"
            provider_verification_action = "Implement official KG Inicis/KCB/KCP/LG verification SDK/API callbacks or configure GNUBOARD_CERT_ADAPTER_BASE_URL."

        return {
            "configuration": check_item(
                "cert_configuration",
                "Gnuboard5 identity-verification provider configuration",
                config_status,
                missing=config_missing,
                details={
                    "enabled": config["enabled"],
                    "mode": config["mode"],
                    "required": config["required"],
                    "find_enabled": config["find_enabled"],
                    "simple": config["simple"],
                    "hp": config["hp"],
                    "ipin": config["ipin"],
                    "use_hp": config["use_hp"],
                    "require_hp": config["require_hp"],
                },
                action="Import or set cf_cert_* values before enabling certification in production.",
            ),
            "frontend_origin": check_item(
                "cert_frontend_origin",
                "Certification popup postMessage origin",
                "ready" if origin_ready else "missing",
                missing=[] if origin_ready else ["GNUBOARD_CERT_APP_BASE_URL or GNUBOARD_CERT_ALLOWED_ORIGINS"],
                details={
                    "has_cert_app_base_url": bool(setting_value("GNUBOARD_CERT_APP_BASE_URL")),
                    "has_social_app_base_url": bool(setting_value("SOCIAL_APP_BASE_URL")),
                    "cert_allowed_origins": setting_value("GNUBOARD_CERT_ALLOWED_ORIGINS"),
                },
                action="Set the Vercel/frontend origin so popup results are posted only to trusted domains.",
            ),
            "adapter_delegation": check_item(
                "cert_adapter_delegation",
                "Existing Gnuboard5/PHP certification adapter delegation",
                adapter_status,
                missing=[] if adapter_base_url else ["GNUBOARD_CERT_ADAPTER_BASE_URL"],
                details={"configured": bool(adapter_base_url), "base_url": adapter_base_url},
                action="Point GNUBOARD_CERT_ADAPTER_BASE_URL at a verified provider adapter or implement native SDK verification.",
            ),
            "provider_verification": check_item(
                "cert_provider_result_verification",
                "Provider result decrypt/signature verification",
                provider_verification_status,
                details={
                    "native_implemented": False,
                    "adapter_delegation": bool(adapter_base_url),
                },
                action=provider_verification_action,
            ),
        }

    def summarize(self, audit):
        summary = {"ready": 0, "delegated": 0, "missing_settings": 0, "disabled": 0, "blocked": 0, "unused": 0}

        for item in self.iter_check_items(audit):
            status = item.get("status")
            if status == "ready":
                summary["ready"] += 1
            elif status == "delegated":
                summary["delegated"] += 1
            elif status == UNUSED:
                summary["unused"] += 1
            elif status == "missing":
                summary["missing_settings"] += max(1, len(item.get("missing") or []))
            elif status == "disabled":
                summary["disabled"] += 1
            elif status == "blocked":
                summary["blocked"] += 1

        summary["production_ready"] = not (
            summary["missing_settings"] or summary["disabled"] or summary["blocked"]
        )
        return summary

    def iter_check_items(self, value):
        if isinstance(value, dict):
            if "status" in value and "name" in value:
                yield value
            for child in value.values():
                yield from self.iter_check_items(child)
        elif isinstance(value, list):
            for child in value:
                yield from self.iter_check_items(child)

    def print_summary(self, audit):
        self.stdout.write("External integration readiness")
        self.stdout.write("")
        self.print_payment(audit["payment"])
        self.print_social(audit["social_oauth"])
        self.print_certification(audit["identity_verification"])
        summary = audit["summary"]
        self.stdout.write("Summary:")
        self.stdout.write(f"  production ready: {'yes' if summary['production_ready'] else 'no'}")
        self.stdout.write(f"  ready checks: {summary['ready']}")
        self.stdout.write(f"  missing settings: {summary['missing_settings']}")
        self.stdout.write(f"  disabled checks: {summary['disabled']}")
        self.stdout.write(f"  blocked implementation gaps: {summary['blocked']}")
        self.stdout.write(f"  unused checks: {summary['unused']} (not used by this site)")

    def print_payment(self, payment):
        self.stdout.write("Payment:")
        self.stdout.write(f"  chosen provider: {payment['chosen_provider']}")
        self.stdout.write(f"  active provider: {payment['active_provider']}")
        self.print_item(payment["callback_secret"], indent=2)
        self.print_item(payment["callback_hmac_signature"], indent=2)
        self.print_item(payment["toss"], indent=2)
        self.print_item(payment["nicepay"], indent=2)
        self.print_item(payment["adapter_delegation"], indent=2)
        self.stdout.write("  legacy PG parity:")
        for item in payment["legacy_pg_parity"]:
            self.print_item(item, indent=4)
        self.stdout.write("  operations:")
        for item in payment["operations"]:
            self.print_item(item, indent=4)

    def print_social(self, social):
        self.stdout.write("Social OAuth:")
        self.print_item(social["frontend_origin"], indent=2)
        for item in social["providers"].values():
            self.print_item(item, indent=2)
        self.stdout.write("  legacy social parity:")
        for item in social["legacy_provider_parity"]:
            self.print_item(item, indent=4)

    def print_certification(self, certification):
        self.stdout.write("Identity verification:")
        for item in certification.values():
            self.print_item(item, indent=2)

    def print_item(self, item, indent=2):
        padding = " " * indent
        self.stdout.write(f"{padding}- {item['label']}: {item['status']}")
        if item.get("missing"):
            self.stdout.write(f"{padding}  missing: {', '.join(item['missing'])}")
        if item.get("action") and item["status"] not in {"ready", UNUSED}:
            self.stdout.write(f"{padding}  action: {item['action']}")
