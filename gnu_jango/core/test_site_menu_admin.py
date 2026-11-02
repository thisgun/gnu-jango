"""The site menu editor (/admin/core/site_menu/) rewrites every menu row on save."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from gnu_jango.core.models import Site_menu

CHANGELIST = "admin:core_site_menu_changelist"


def menu_post(**overrides):
    data = {
        "csrfmiddlewaretoken": "token",
        "code[]": ["10", "20"],
        "me_name[]": ["새 메뉴", "둘째 메뉴"],
        "me_link[]": ["/new", "/second"],
        "me_type[]": ["", ""],
        "me_type_pk[]": ["0", "0"],
        "me_target[]": ["self", "self"],
        "me_order[]": ["0", "1"],
        "me_use[]": ["1", "1"],
        "me_mobile_use[]": ["1", "1"],
    }
    data.update(overrides)
    return data


class SiteMenuAdminTests(TestCase):
    def setUp(self):
        Site_menu.objects.create(me_code="10", me_name="기존 메뉴", me_link="/old")

    def staff_with(self, *codenames):
        staff = get_user_model().objects.create_user(username="-".join(codenames), password="pw", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
        self.client.force_login(staff)
        return staff

    def menu_names(self):
        return sorted(Site_menu.objects.values_list("me_name", flat=True))

    def test_a_view_only_staff_user_cannot_rewrite_the_menus(self):
        self.staff_with("view_site_menu")

        response = self.client.post(reverse(CHANGELIST), menu_post())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.menu_names(), ["기존 메뉴"])

    def test_a_staff_user_who_may_change_menus_saves_them(self):
        self.staff_with("view_site_menu", "change_site_menu")

        response = self.client.post(reverse(CHANGELIST), menu_post())

        self.assertRedirects(response, reverse(CHANGELIST), fetch_redirect_response=False)
        self.assertEqual(self.menu_names(), ["둘째 메뉴", "새 메뉴"])

    def test_a_bad_number_keeps_the_existing_menus(self):
        self.staff_with("view_site_menu", "change_site_menu")

        response = self.client.post(reverse(CHANGELIST), menu_post(**{"me_order[]": ["0", "abc"]}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "숫자")
        self.assertEqual(self.menu_names(), ["기존 메뉴"])

    def test_empty_numbers_are_posted_back_as_zero(self):
        # Rows imported from 그누보드 may hold NULL; "None" in the form would block the next save.
        Site_menu.objects.update(me_type_pk=None, me_order=None)
        self.staff_with("view_site_menu", "change_site_menu")

        response = self.client.get(reverse(CHANGELIST))

        self.assertContains(response, 'name="me_type_pk[]" value="0"')
        self.assertContains(response, 'name="me_order[]" value="0"')
        self.assertNotContains(response, 'value="None"')

    def test_a_failure_while_saving_rolls_the_whole_menu_back(self):
        self.staff_with("view_site_menu", "change_site_menu")
        original_save = Site_menu.save
        calls = []

        def fail_on_second_row(menu, *args, **kwargs):
            calls.append(menu.me_name)
            if len(calls) == 2:
                raise RuntimeError("database went away")
            return original_save(menu, *args, **kwargs)

        with patch.object(Site_menu, "save", fail_on_second_row), self.assertRaises(RuntimeError):
            self.client.post(reverse(CHANGELIST), menu_post())

        self.assertEqual(self.menu_names(), ["기존 메뉴"])
