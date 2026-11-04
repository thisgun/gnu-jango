
from django import forms
from django.db import transaction
from django.db.models.functions import Substr, Length
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from .models import Site_menu
from gnu_jango.utils.lib import chng_frm_base


class SiteMenuForms(forms.Form):
    me_code = forms.CharField()
    me_name = forms.CharField()
    me_link = forms.CharField()
    me_type = forms.CharField()
    me_type_pk = forms.IntegerField()
    # me_target = models.DateTimeField(_("새창"), null=True, blank=True, max_length=255)
    # me_order = models.IntegerField(_("출력순서"), default=0, null=True, blank=True)
    # me_use = models.PositiveSmallIntegerField(_("메뉴사용"), default=0, null=True, blank=True)
    # me_mobile_use = models.PositiveSmallIntegerField(
    #     _("모바일 메뉴사용"), default=0, null=True, blank=True
    # )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # The numeric columns of a menu row, and whether they must not be negative.
    NUMBER_FIELDS = (("me_type_pk[]", False), ("me_order[]", False), ("me_use[]", True), ("me_mobile_use[]", True))
    NUMBER_ERROR = _("메뉴의 대상참조·출력순서·사용 값은 숫자여야 합니다.")

    def is_valid(self):
        # The editor posts parallel lists (code[], me_name[], ...) that save() reads itself, so the
        # declared fields never validate; check instead that every row save() keeps can be stored.
        return not self._has_bad_number()

    def _has_bad_number(self):
        codes = self.data.getlist("code[]")
        names = self.data.getlist("me_name[]")
        links = self.data.getlist("me_link[]")
        for i, code in enumerate(codes):
            if not (code and len(names) > i and names[i] and len(links) > i and links[i]):
                continue
            for key, must_be_positive in self.NUMBER_FIELDS:
                values = self.data.getlist(key)
                if len(values) <= i:
                    continue
                try:
                    number = int(values[i])
                except ValueError:
                    return True
                if must_be_positive and number < 0:
                    return True
        return False

    @transaction.atomic
    def save(self):

        Site_menu.objects.all().delete()

        codes = self.data.getlist("code[]")
        me_links = self.data.getlist("me_link[]")
        me_names = self.data.getlist("me_name[]")
        me_types = self.data.getlist("me_type[]")
        me_type_pks = self.data.getlist("me_type_pk[]")
        me_targets = self.data.getlist("me_target[]")
        me_orders = self.data.getlist("me_order[]")
        me_uses = self.data.getlist("me_use[]")
        me_mobile_uses = self.data.getlist("me_mobile_use[]")

        group_code = None
        primary_code = None

        if codes:

            for i, code in enumerate(codes):

                me_name = me_names[i] if len(me_names) > i else None
                me_link = me_links[i] if len(me_links) > i else None
                me_type = me_types[i] if len(me_types) > i else None
                me_type_pk = me_type_pks[i] if len(me_type_pks) > i else None
                me_target = me_targets[i] if len(me_targets) > i else None
                me_order = me_orders[i] if len(me_orders) > i else None
                me_use = me_uses[i] if len(me_uses) > i else None
                me_mobile_use = me_mobile_uses[i] if len(me_mobile_uses) > i else None

                if not (code and me_name and me_link):
                    continue

                sub_code = ""
                if group_code == code:

                    row_max_me_code = (
                        Site_menu.objects.annotate(
                            max_me_code=Substr("me_code", 3, 2),
                            where_me_code=Substr("me_code", 1, 2),
                        )
                        .filter(where_me_code__exact=primary_code)
                        .aggregate(Max("max_me_code"))
                    )["max_me_code__max"]

                    sub_code = chng_frm_base(str(row_max_me_code), 36, 10)
                    sub_code = int(sub_code) if sub_code else 0
                    sub_code += 36
                    sub_code = chng_frm_base(str(sub_code), 10, 36)
                    me_code = primary_code + sub_code

                else:
                    row_max_me_code = (
                        Site_menu.objects.annotate(
                            max_me_code=Substr("me_code", 1, 2), text_len=Length("me_code")
                        )
                        .filter(text_len__exact=2)
                        .aggregate(Max("max_me_code"))
                    )["max_me_code__max"]

                    max_me_code = str(row_max_me_code) if row_max_me_code else ""
                    me_code = chng_frm_base(max_me_code, 36, 10)
                    me_code = int(me_code) if me_code else 0
                    me_code += 36
                    me_code = chng_frm_base(str(me_code), 10, 36)

                    group_code = code
                    primary_code = me_code

                data = {
                    "me_code": me_code,
                    "me_name": me_name,
                    "me_link": me_link,
                    "me_type": me_type,
                    "me_type_pk": me_type_pk,
                    "me_target": me_target,
                    "me_order": me_order,
                    "me_use": me_use,
                    "me_mobile_use": me_mobile_use,
                }

                menu = Site_menu(
                    me_code=data["me_code"],
                    me_name=data["me_name"],
                    me_type=data["me_type"],
                    me_type_pk=data["me_type_pk"],
                    me_link=data["me_link"],
                    me_target=data["me_target"],
                    me_order=data["me_order"],
                    me_use=data["me_use"],
                    me_mobile_use=data["me_mobile_use"],
                )

                menu.save()

        # for (name, value) in self.cleaned_data.items():

        #     print(name, value)
