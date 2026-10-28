"""OpenAPI contract tests for the current-member read (gnu_jango/api/contracts/auth.py)."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.core.contract_testing import ContractAssertions
from gnu_jango.users.models import Profile

ME = "/api/v1/auth/me"

CONTRACT_OPERATIONS = {
    ("GET", ME),
}


class AuthMeContractTests(ContractAssertions, TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def bearer_client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def test_me_for_a_member_with_contact_details_matches_the_contract(self):
        user = get_user_model().objects.create_user(username="contract_member", email="", password="Str0ng-pass-99")
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.nickname = "계약회원"
        profile.user_level = 2
        profile.user_hp = "010-1234-5678"
        profile.user_zip = "06236"
        profile.user_addr1 = "서울 강남구"
        profile.open_profile = False
        profile.open_profile_date = timezone.now()
        profile.save()

        response = self.bearer_client(user).get(ME)

        data = response.json()["data"]
        self.assertIs(data["is_super_admin"], False)
        self.assertEqual((data["member"]["mb_zip1"], data["member"]["mb_zip2"]), ("062", "36"))
        self.assertEqual(data["member"]["mb_open"], 0)
        self.assertMatchesContract(response, ME)

    def test_me_for_a_superuser_without_a_profile_matches_the_contract(self):
        user = get_user_model().objects.create_superuser(
            username="contract_admin", email="admin@example.test", password="Str0ng-pass-99"
        )
        Profile.objects.filter(user=user).delete()  # member_payload creates a blank one

        response = self.bearer_client(user).get(ME)

        data = response.json()["data"]
        self.assertIs(data["is_super_admin"], True)
        self.assertIs(data["member"]["is_superuser"], True)
        self.assertEqual(data["member"]["mb_hp"], "")
        self.assertMatchesContract(response, ME)

    def test_me_for_a_session_member_matches_the_contract(self):
        user = get_user_model().objects.create_user(username="contract_session", password="Str0ng-pass-99")
        self.client.force_login(user)

        self.assertMatchesContract(self.client.get(ME), ME)

    def test_anonymous_me_is_401_and_not_part_of_the_contract(self):
        self.assertEqual(APIClient().get(ME).status_code, 401)
