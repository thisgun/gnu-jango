"""OpenAPI contract tests for the typed v1 endpoints (see gnu_jango/api/contracts/).

Each ``test_api_contract*`` module lists the operations it covers in ``CONTRACT_OPERATIONS``;
``ContractCoverageTests`` fails when an operation has a declared response schema but no module
claims it, so annotating a view without a contract test is caught.
"""

import importlib
import pkgutil

from django.core.cache import cache
from django.test import TestCase

import gnu_jango.core
from gnu_jango.config.models import Config
from gnu_jango.core.contract_testing import ContractAssertions, typed_operations

CONTRACT_OPERATIONS = {
    ("GET", "/api/v1/settings"),
}


class SiteContractTests(ContractAssertions, TestCase):
    def setUp(self):
        cache.clear()

    def test_settings_matches_its_contract(self):
        self.assertMatchesContract(self.client.get("/api/v1/settings"), "/api/v1/settings")

    def test_settings_with_theme_settings_matches_its_contract(self):
        Config.objects.update_or_create(name="cf_theme", defaults={"value": "handbook"})
        Config.objects.update_or_create(name="cf_docs_group", defaults={"value": "docs"})
        cache.clear()

        response = self.client.get("/api/v1/settings")

        self.assertIsInstance(response.json()["data"]["theme_settings"], dict)
        self.assertMatchesContract(response, "/api/v1/settings")


def covered_operations():
    covered = set()
    for module_info in pkgutil.iter_modules(gnu_jango.core.__path__):
        if module_info.name.startswith("test_api_contract"):
            module = importlib.import_module(f"gnu_jango.core.{module_info.name}")
            covered |= set(getattr(module, "CONTRACT_OPERATIONS", ()))
    return covered


class ContractCoverageTests(TestCase):
    def test_every_typed_operation_has_a_contract_test(self):
        self.assertEqual(typed_operations() - covered_operations(), set())

    def test_every_claimed_operation_is_typed(self):
        self.assertEqual(covered_operations() - typed_operations(), set())
