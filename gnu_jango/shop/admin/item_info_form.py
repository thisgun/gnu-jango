"""Admin editing of 상품정보제공고시 rows (itemform.php's ii_article / ii_value table)."""
from django import forms
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextareaWidget

from gnu_jango.shop.item_info import item_info_from_text, item_info_kind_choices, item_info_to_text


class ItemInfoTextField(forms.CharField):
    """One ``title: value`` line per notice row; the form resolves the article keys."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("strip", False)
        kwargs.setdefault("label", "상품정보제공고시")
        kwargs.setdefault(
            "help_text",
            "한 줄에 한 항목씩 “항목명: 내용”으로 입력하세요. 예) 제품소재: 면 100%. "
            "선택한 상품군의 항목명을 쓰면 영카트 항목으로 저장됩니다.",
        )
        kwargs.setdefault("widget", UnfoldAdminTextareaWidget(attrs={"rows": 8}))
        super().__init__(**kwargs)

    def prepare_value(self, value):
        if isinstance(value, list):
            return item_info_to_text(value)
        return value

    def has_changed(self, initial, data):
        before = item_info_to_text(initial) if isinstance(initial, list) else str(initial or "")
        return before.strip() != str(data or "").strip()


def item_info_kind_field(current):
    return forms.ChoiceField(
        label="상품정보제공고시 상품군",
        choices=item_info_kind_choices(current),
        required=False,
        widget=UnfoldAdminSelectWidget,
    )


def clean_item_info(form, cleaned):
    """Turn the edited text into rows with the kind's article keys, or flag the bad line."""
    if "it_info_value" not in form.fields or form.has_error("it_info_value"):
        return cleaned
    try:
        cleaned["it_info_value"] = item_info_from_text(cleaned.get("it_info_value") or "", cleaned.get("it_info_gubun", ""))
    except ValueError as exc:
        form.add_error("it_info_value", f"{exc.args[0]}번째 줄을 “항목명: 내용” 형식으로 입력해 주세요.")
    return cleaned
