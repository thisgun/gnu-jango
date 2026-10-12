from collections import defaultdict
from pathlib import Path
from typing import Dict

from django import forms
from django.template.defaultfilters import urlize
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.widgets import (
    CHECKBOX_CLASSES,
    INPUT_CLASSES,
    SELECT_CLASSES,
    TEXTAREA_CLASSES,
)

from . import signals, config, admin_config
from .models import Config


def _unfold_widget_classes(widget):
    """Return the Unfold utility classes that match a given form widget."""
    if isinstance(widget, forms.CheckboxInput):
        return CHECKBOX_CLASSES
    if isinstance(widget, forms.Textarea):
        return TEXTAREA_CLASSES
    if isinstance(widget, (forms.Select, forms.SelectMultiple)):
        return SELECT_CLASSES
    return INPUT_CLASSES

# if settings.USE_MODELTRANSLATION:
#    from collections import OrderedDict

#    from modeltranslation.utils import build_localized_fieldname


# `defaults.CONFIGS` describes each setting with a *string* type marker
# ("checkbox", "choices", "text", "int", ...). The previous mapping was keyed by
# Python types (bool/int/float), so no marker ever matched and every setting
# fell back to CharField -- which is why 27 checkboxes, 21 selects and 7
# textareas all rendered as plain text inputs.
FIELD_TYPES = {
    "checkbox": forms.BooleanField,
    "choices": forms.ChoiceField,
    "email": forms.EmailField,
    "float": forms.FloatField,
    "hidden": forms.CharField,
    "int": forms.IntegerField,
    "str": forms.CharField,
    "text": forms.CharField,
    "url": forms.URLField,
}

# Settings stored as a flag. gnuboard keeps these as strings and consumers test
# them for truthiness (`if config.cf_use_point:`), so a stored "0" reads as
# enabled. Write "1" when checked and "" when cleared so the checkbox state and
# the runtime behaviour agree.
CHECKBOX_ON = "1"
CHECKBOX_OFF = ""
CHECKBOX_FALSE_VALUES = {"", "0", "false", "no", "off"}


def config_to_bool(value):
    """Interpret a stored config value as a flag."""
    if isinstance(value, str):
        return value.strip().lower() not in CHECKBOX_FALSE_VALUES
    return bool(value)


def _level_choices():
    return [(str(i), str(i)) for i in range(1, 11)]


def _skin_choices(kind):
    """List the skins shipped under ``templates/skin/<kind>`` plus the themes."""
    import gnu_jango

    templates = Path(gnu_jango.__file__).resolve().parent / "templates"
    found = []
    skin_dir = templates / "skin" / kind
    if skin_dir.is_dir():
        found += [(d.name, d.name) for d in sorted(skin_dir.iterdir()) if d.is_dir()]
    theme_dir = templates / "theme"
    if theme_dir.is_dir():
        for theme in sorted(theme_dir.iterdir()):
            if (theme / "skin" / kind).is_dir():
                found.append((f"theme/{theme.name}", "(%s) %s" % (_("테마"), theme.name)))
    return [("", _("선택"))] + found


# Directory under templates/skin/ that backs each skin setting.
SKIN_CONFIG_KINDS = {
    "cf_new_skin": "latest",
    "cf_mobile_new_skin": "latest",
    "cf_search_skin": "search",
    "cf_mobile_search_skin": "search",
    "cf_connect_skin": "connect",
    "cf_mobile_connect_skin": "connect",
    "cf_faq_skin": "faq",
    "cf_mobile_faq_skin": "faq",
    "cf_user_skin": "user",
    "cf_mobile_user_skin": "user",
}

# Settings marked "choices" in defaults.CONFIGS that carry no option list there.
# The options mirror the gnuboard5 admin (adm/config_form.php) they replace.
CONFIG_CHOICES = {
    "cf_link_target": [
        ("_blank", "_blank"),
        ("_self", "_self"),
        ("_top", "_top"),
        ("_new", "_new"),
    ],
    "cf_register_level": _level_choices,
    "cf_icon_level": _level_choices,
    "cf_cert_use": [
        ("0", _("사용안함")),
        ("1", _("테스트")),
        ("2", _("실서비스")),
    ],
    "cf_cert_simple": [
        ("", _("사용안함")),
        ("inicis", _("KG이니시스 통합인증(간편인증)")),
    ],
    "cf_cert_hp": [
        ("", _("사용안함")),
        ("kcb", _("코리아크레딧뷰로(KCB) 휴대폰 본인확인")),
        ("kcp", _("NHN KCP 휴대폰 본인확인")),
        ("kcp_v2", _("NHN KCP 휴대폰 본인확인(api_v2)")),
    ],
    "cf_cert_ipin": [
        ("", _("사용안함")),
        ("kcb", _("코리아크레딧뷰로(KCB) 아이핀")),
    ],
    "cf_captcha": [
        ("", _("사용안함")),
        ("kcaptcha", "Kcaptcha"),
        ("recaptcha", "reCAPTCHA V2"),
        ("recaptcha_inv", "Invisible reCAPTCHA"),
    ],
    "cf_captcha_mp3": [
        ("", _("선택")),
        ("basic", "basic"),
    ],
}


def resolve_choices(name, declared, value):
    """Build the option list for a "choices" setting.

    The stored value is always kept as an option: a value that has dropped out
    of the list (a removed skin, a retired provider) would otherwise fail
    validation and block the whole settings form from saving.
    """
    choices = list(declared) if declared else []
    if not choices:
        if name in SKIN_CONFIG_KINDS:
            choices = _skin_choices(SKIN_CONFIG_KINDS[name])
        else:
            source = CONFIG_CHOICES.get(name)
            choices = list(source() if callable(source) else source or [])
    if not choices:
        choices = [("", _("선택"))]
    current = "" if value is None else str(value)
    if current not in {str(key) for key, label in choices}:
        choices = [*choices, (current, current or _("선택"))]
    return [(str(key), label) for key, label in choices]

# Config fields that hold credentials/secrets. They are rendered as masked
# password inputs whose value is never sent to the browser, and an empty
# submission is treated as "keep the stored value" (see save()).
SECRET_CONFIG_FIELDS = {
    "cf_naver_secret",
    "cf_facebook_secret",
    "cf_cert_kg_mid",
    "cf_cert_kg_cd",
}

# https://stackoverflow.com/questions/66724197/get-key-from-a-value-where-value-is-in-a-list


def corresponding_key(val, dictionary):
    for k, v in dictionary.items():
        if val in v:
            return k
            # return admin_config.CONFIGS_TITLE_SETS.get(k, k)

    # return val.split("_", 1)[0]
    return "etc"


CONFIG_GROUP_LABELS = {
    "1_basic": _("1. 기본 환경"),
    "2_board": _("2. 게시판 기본"),
    "3_join": _("3. 회원가입/회원"),
    "4_cert": _("4. 본인확인"),
    "5_mail": _("5. 메일 설정"),
    "6_article_mail": _("6. 게시글 메일"),
    "7_join_mail": _("7. 회원가입 메일"),
    "8_vote_mail": _("8. 포인트/투표 메일"),
    "9_sns": _("9. SNS 로그인"),
    "10_site_info": _("사이트 정보"),
    "11_home_layout": _("홈 화면 구성"),
    "etc": _("기타 설정"),
}


def format_config_group_label(group_key):
    normalized = str(group_key or "etc").lower()
    return CONFIG_GROUP_LABELS.get(normalized, str(group_key).replace("_", " ").title())


# Each group renders as a card; the groups are gathered into the tabs across the
# top so 113 settings are not one endless scroll.
CONFIG_TABS = {
    "1_basic": "basic",
    "2_board": "board",
    "3_join": "member",
    "4_cert": "member",
    "5_mail": "mail",
    "6_article_mail": "mail",
    "7_join_mail": "mail",
    "8_vote_mail": "mail",
    "9_sns": "sns",
    "10_site_info": "etc",
    "11_home_layout": "etc",
    "etc": "etc",
}

TAB_ORDER = ["basic", "board", "member", "mail", "sns", "etc"]

TAB_LABELS = {
    "basic": _("기본"),
    "board": _("게시판"),
    "member": _("회원"),
    "mail": _("메일"),
    "sns": _("소셜 로그인"),
    "etc": _("기타"),
}

# Short line under each card title.
SECTION_DESCRIPTIONS = {
    "1_basic": _("사이트 이름과 관리자 연락 정보 등 기본 운영값입니다."),
    "2_board": _("새 게시판을 만들 때 적용되는 기본값입니다."),
    "3_join": _("회원가입 정책과 가입 폼에 표시할 항목입니다."),
    "4_cert": _("휴대폰·아이핀 등 본인확인 서비스 연동 정보입니다."),
    "5_mail": _("메일 발송 사용 여부와 발송 주체를 설정합니다."),
    "6_article_mail": _("게시글이 등록될 때 보내는 알림 메일입니다."),
    "7_join_mail": _("회원가입 단계에서 보내는 메일입니다."),
    "8_vote_mail": _("포인트와 투표 관련 메일입니다."),
    "9_sns": _("소셜 로그인 제공자별 연동 키입니다."),
    "10_site_info": _("푸터와 사이트 안내에 공개할 사업자 정보를 설정합니다."),
    "11_home_layout": _("홈의 게시판과 갤러리 영역에 표시할 게시판을 지정합니다."),
    "etc": _("위 분류에 속하지 않는 나머지 설정입니다."),
}

# Unit suffix shown beside numeric settings, as in the reference design.
CONFIG_UNITS = {
    "cf_new_del": _("일"),
    "cf_memo_del": _("일"),
    "cf_visit_del": _("일"),
    "cf_popular_del": _("일"),
    "cf_login_minutes": _("분"),
    "cf_leave_day": _("일"),
    "cf_nick_modify": _("일"),
    "cf_password_expire": _("일"),
    "cf_point_term": _("일"),
    "cf_login_point": _("점"),
    "cf_read_point": _("점"),
    "cf_write_point": _("점"),
    "cf_comment_point": _("점"),
    "cf_download_point": _("점"),
    "cf_memo_send_point": _("점"),
    "cf_cut_name": _("자"),
    "cf_write_pages": _("개"),
    "cf_mobile_pages": _("개"),
    "cf_page_rows": _("개"),
    "cf_mobile_page_rows": _("개"),
    "cf_new_rows": _("개"),
    "cf_delay_sec": _("초"),
}


class ConfigsForm(forms.Form):
    """
    Form for settings - creates a field for each setting in
    ``mezzanine.conf`` that is marked as editable.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Create a form field for each editable setting's from its type.

        # Configs = defaults.CONFIGS

        # Configs = ConfigALL.get_all()

        # for name in sorted(Configs.keys()):

        # print(config)
        for name, value in config.get_conf_all().items():
            # print( value )
            if isinstance(value, Dict):
                config_row = value
            else:
                config_row = {
                    "name": name,
                    "value": value,
                    "type": "str",
                    "label": name,
                    "description": None,
                    "choices": None,
                    "group": None,
                }

            kind = str(config_row["type"] or "str").strip().lower()
            field_class = FIELD_TYPES.get(kind, forms.CharField)
            self._init_field(config_row, field_class, name, kind=kind)

    def _init_field(
        self,
        config_row,
        field_class,
        name,
        code=None,
        kind="str",
    ):
        """
        Initialize a field whether it is built with a custom name for a
        specific translation language or not.
        """
        value = config_row["value"]
        kwargs = {
            "label": "{}:".format(config_row["label"] or name),
            # Every setting stays optional: the form saves all 113 settings at
            # once, so one blank field must not block the whole page.
            "required": False,
            "initial": value,
            "help_text": self.format_help(config_row["description"]),
        }

        # A declared option list wins; "choices" settings without one fall back
        # to the list resolved from skins/providers.
        if config_row["choices"] or kind == "choices":
            field_class = forms.ChoiceField
            kwargs["choices"] = resolve_choices(name, config_row["choices"], value)
            kwargs["initial"] = "" if value is None else str(value)
        elif kind == "checkbox":
            kwargs["initial"] = config_to_bool(value)
        elif kind == "text":
            kwargs["widget"] = forms.Textarea(attrs={"rows": 5})
        elif kind == "hidden":
            kwargs["widget"] = forms.HiddenInput()

        field_instance = field_class(**kwargs)
        if name in SECRET_CONFIG_FIELDS:
            # Never echo the stored secret back to the browser; an empty submit
            # keeps the existing value (handled in save()).
            field_instance.required = False
            field_instance.widget = forms.PasswordInput(render_value=False)
        code_name = "_modeltranslation_" + code if code else ""
        self.fields[name + code_name] = field_instance

        # Style the widget with Unfold's own utility classes so the rendered
        # field is visually identical to a native Unfold admin form. The
        # original type/translation markers are kept for any JS hooks.
        widget = field_instance.widget
        classes = list(_unfold_widget_classes(widget))
        classes.append(field_class.__name__.lower())
        if code:
            classes.append("modeltranslation")
        widget.attrs["class"] = " ".join(classes)

    def __iter__(self):
        """
        Calculate and apply a group heading to each field and order by
        the heading.
        """
        fields = list(super().__iter__())
        # group = lambda field: field.name.split("_", 1)[0].title()

        # group_key = corresponding_key(admin_config.CONFIG_FIELDSETS)

        # key = corresponding_key

        # group = lambda field: field.name.split("_", 1)[0].title()

        group_key = lambda field: str(
            corresponding_key(field.name, admin_config.CONFIG_FIELDSETS) or "etc"
        ).lower()

        # A group holding a single setting is not worth its own card, so it
        # joins the catch-all one.
        counts = defaultdict(int)
        for field in fields:
            counts[group_key(field)] += 1

        for field in fields:
            key = group_key(field)
            if counts[key] == 1:
                key = "etc"
            tab_id = CONFIG_TABS.get(key, "etc")
            field.group_key = key
            field.group = format_config_group_label(key)
            field.section_help = SECTION_DESCRIPTIONS.get(key, "")
            field.tab_id = tab_id
            field.tab_label = TAB_LABELS.get(tab_id, TAB_LABELS["etc"])
            field.unit = CONFIG_UNITS.get(field.name, "")
            widget = field.field.widget
            field.is_checkbox = isinstance(widget, forms.CheckboxInput)
            field.is_textarea = isinstance(widget, forms.Textarea)
            # Long free-text settings need the full card width; everything else
            # sits in the responsive column grid.
            field.is_wide = field.is_textarea

        tab_rank = {tab: i for i, tab in enumerate(TAB_ORDER)}
        return iter(
            sorted(
                fields,
                key=lambda f: (tab_rank.get(f.tab_id, len(TAB_ORDER)), f.group_key),
            )
        )

    def save(self):
        """
        Save each of the settings to the DB.
        """

        rows = config.get_all()
        for (name, value) in self.cleaned_data.items():
            if name not in rows.keys():
                if "_modeltranslation_" not in name:
                    continue
                name, code = name.rsplit("_modeltranslation_", 1)
            else:
                code = None

            # Only persist known settings (defense against mass-assignment of
            # arbitrary config names into the DB).
            if name not in rows:
                continue

            # An empty secret submission means "leave the stored value alone".
            if name in SECRET_CONFIG_FIELDS and value in (None, ""):
                continue

            # Config.value is a string column, so a checkbox has to be stored as
            # one. "" rather than "0" for off, because consumers only test the
            # stored string for truthiness and "0" would read as enabled.
            if isinstance(value, bool):
                value = CHECKBOX_ON if value else CHECKBOX_OFF

            # A blank number field cleans to None, which the NOT NULL value
            # column rejects. Leave the stored setting alone instead, the same
            # way an empty secret submission does.
            if value is None:
                continue

            if rows[name] == value:
                continue

            setting_obj, created = Config.objects.get_or_create(name=name)

            setting_obj.value = value
            setting_obj.save()

        signals.config_done.send(sender=Config)

    def format_help(self, description):
        """
        Format the setting's description into HTML.
        """
        description = conditional_escape(description or "")
        for bold in ("``", "*"):
            parts = []
            for i, s in enumerate(str(description).split(bold)):
                parts.append(s if i % 2 == 0 else format_html("<b>{}</b>", s))
            description = mark_safe("".join(str(part) for part in parts))
        description = urlize(description, autoescape=False)
        return mark_safe(str(description).replace("\n", "<br>"))
