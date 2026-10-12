from gnu_jango.core.admin._common import *  # noqa: F401,F403
from django.utils.translation import gettext_lazy as _


CONTENT_STATUS_PUBLISHED = 2


class DisplayableAdminForm(ModelForm):
    def clean_content(form):
        status = form.cleaned_data.get("status")
        content = form.cleaned_data.get("content")
        if status == CONTENT_STATUS_PUBLISHED and not content:
            raise ValidationError(_("This field is required if status " "is set to published."))
        return content


class DisplayableAdmin(ModelAdmin):
    """
    Admin class for subclasses of the abstract ``Displayable`` model.
    """

    list_display = ("title", "status", "admin_link")
    list_display_links = ("title",)
    list_editable = ("status",)
    list_filter = ("status", "keywords__keyword")
    # modeltranslation breaks date hierarchy links, see:
    # https://github.com/deschler/django-modeltranslation/issues/324
    # Once that's resolved we can restore this.
    date_hierarchy = None if settings.USE_MODELTRANSLATION else "publish_date"
    radio_fields = {"status": admin.HORIZONTAL}
    fieldsets = (
        (
            None,
            {
                "fields": ["title", "status", ("publish_date", "expiry_date")],
            },
        ),
        (
            _("Meta data"),
            {
                "fields": [
                    "_meta_title",
                    "slug",
                    ("description", "gen_description"),
                    "keywords",
                    "in_sitemap",
                ],
                "classes": ("collapse-closed",),
            },
        ),
    )

    form = DisplayableAdminForm

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.search_fields = list(
                set(list(self.search_fields) + list(self.model.objects.get_search_fields().keys()))
            )
        except AttributeError:
            pass

    def check_permission(self, request, page, permission):
        """
        Subclasses can define a custom permission check and raise an exception
        if False.
        """
        pass

    def save_model(self, request, obj, form, change):
        """
        Save model for every language so that field auto-population
        is done for every each of it.
        """
        super().save_model(request, obj, form, change)
        if settings.USE_MODELTRANSLATION:
            lang = get_language()
            for code in OrderedDict(settings.LANGUAGES):
                if code != lang:  # Already done
                    try:
                        activate(code)
                    except (LookupError, ValueError):
                        # Unknown/invalid locale code — skip that language
                        # instead of silently swallowing every exception.
                        pass
                    else:
                        obj.save()
            activate(lang)


class ContentTypedAdmin:
    def __init__(self, *args, **kwargs):
        """
        For subclasses that are registered with an Admin class
        that doesn't implement fieldsets, add any extra model fields
        to this instance's fieldsets. This mimics Django's behaviour of
        adding all model fields when no fieldsets are defined on the
        Admin class.
        """
        super().__init__(*args, **kwargs)

        self.concrete_model = base_concrete_model(ContentTyped, self.model)

        # Test that the fieldsets don't differ from the concrete admin's.
        if (
            self.model is not self.concrete_model
            and self.fieldsets == self.base_concrete_modeladmin.fieldsets
        ):

            # Make a copy so that we aren't modifying other Admin
            # classes' fieldsets.
            self.fieldsets = deepcopy(self.fieldsets)

            # Insert each field between the publishing fields and nav
            # fields. Do so in reverse order to retain the order of
            # the model's fields.
            model_fields = self.concrete_model._meta.get_fields()
            concrete_field = "{concrete_model}_ptr".format(
                concrete_model=self.concrete_model.get_content_model_name()
            )
            exclude_fields = [f.name for f in model_fields] + [concrete_field]

            try:
                exclude_fields.extend(self.exclude)
            except (AttributeError, TypeError):
                pass

            try:
                exclude_fields.extend(self.form.Meta.exclude)
            except (AttributeError, TypeError):
                pass

            fields = self.model._meta.get_fields() + self.model._meta.many_to_many
            for field in reversed(fields):
                if field.name not in exclude_fields and field.editable:
                    if (
                        not hasattr(field, "translated_field")
                        and field.name not in self.fieldsets[0][1]["fields"]
                    ):
                        self.fieldsets[0][1]["fields"].insert(3, field.name)

    @property
    def base_concrete_modeladmin(self):
        """The class inheriting directly from ContentModelAdmin."""
        candidates = [self.__class__]
        while candidates:
            candidate = candidates.pop()
            if ContentTypedAdmin in candidate.__bases__:
                return candidate
            candidates.extend(candidate.__bases__)

        raise Exception("Can't find base concrete ModelAdmin class.")

    def has_module_permission(self, request):
        """
        Hide subclasses from the admin menu.
        """
        return self.model is self.concrete_model

    def change_view(self, request, object_id, **kwargs):
        """
        For the concrete model, check ``get_content_model()``
        for a subclass and redirect to its admin change view.
        """
        instance = get_object_or_404(self.concrete_model, pk=object_id)
        content_model = instance.get_content_model()

        self.check_permission(request, content_model, "change")

        if content_model.__class__ != self.model:
            change_url = admin_url(content_model.__class__, "change", content_model.id)
            return HttpResponseRedirect(change_url)

        return super().change_view(request, object_id, **kwargs)

    def changelist_view(self, request, extra_context=None):
        """Redirect to the changelist view for subclasses."""
        if self.model is not self.concrete_model:
            return HttpResponseRedirect(admin_url(self.concrete_model, "changelist"))

        extra_context = extra_context or {}
        extra_context["content_models"] = self.get_content_models()

        return super().changelist_view(request, extra_context)

    def get_content_models(self):
        """Return all subclasses that are admin registered."""
        models = []

        for model in self.concrete_model.get_content_models():
            try:
                admin_url(model, "add")
            except NoReverseMatch:
                continue
            else:
                setattr(model, "meta_verbose_name", model._meta.verbose_name)
                setattr(model, "add_url", admin_url(model, "add"))
                models.append(model)

        return models


# class Site_menu_admin(ContentTypedAdmin, DisplayableAdmin):

#     change_list_template = "admin/pages/page/change_list.html"


class Site_menu_admin(ModelAdmin):

    change_list_template = "admin/site_menu/change_list.html"
    change_form_template = "admin/site_menu/change_form.html"
    list_display = ("me_code",)
    search_fields = ["me_code"]

    def get_ordering(self, request):
        return [Lower("me_code")]  # sort case insensitive

    # def get_urls(self):
    #     urls = super().get_urls()
    #     custom_urls = [
    #         path("add/", self.admin_view(organization_admin.preview), name="preview"),
    #     ]
    #     return urls + custom_urls

    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            wrapper.model_admin = self
            return update_wrapper(wrapper, view)

        urls = super().get_urls()
        custom_urls = [
            path("add_site_menu/", wrap(self.add_menu_form), name="add_admin_site_menu"),
            path(
                "ajax_menu_form_search/",
                wrap(self.ajax_menu_form_search),
                name="ajax_menu_form_search",
            ),
        ]

        return custom_urls + urls

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):

        new = request.GET.get("new")
        code = str(request.GET.get("code", 0))

        if new == "new" or not code:
            code = lib.chng_frm_base(code[:2], 36, 10)
            code = int(code) if code else 0
            code += 36
            code = lib.chng_frm_base(str(code), 10, 36)

        context["new"] = new
        context["code"] = code

        return super().render_change_form(request, context, add, change, form_url, obj)

    def get_form(self, request, obj=None, **kwargs):

        # primary_code = str(10)
        # # row_max_me_code = (
        # #     site_menu.objects.annotate(max_me_code=Substr("me_code", 3, 2))
        # #     .filter(me_code__istartswith=primary_code)
        # #     .aggregate(Max("max_me_code"))
        # # )["max_me_code__max"]

        # row_max_me_code = (
        #     site_menu.objects.annotate(
        #         max_me_code=Substr("me_code", 3, 2), where_me_code=Substr("me_code", 1, 2)
        #     )
        #     .filter(where_me_code__exact=primary_code)
        #     .aggregate(Max("max_me_code"))
        # )["max_me_code__max"]

        # sub_code = chng_frm_base(str(row_max_me_code), 36, 10)
        # sub_code = int(sub_code) if sub_code else 0
        # sub_code += 36
        # sub_code = chng_frm_base(str(sub_code), 10, 36)
        # me_code = primary_code + sub_code

        # print(me_code)

        # row_max_me_code = (
        #     site_menu.objects.annotate(
        #         max_me_code=Substr("me_code", 1, 2), text_len=Length("me_code")
        #     )
        #     .filter(text_len__exact=2)
        #     .aggregate(Max("max_me_code"))
        # )["max_me_code__max"]

        # max_me_code = str(row_max_me_code) if row_max_me_code else ""
        # me_code = chng_frm_base(max_me_code, 36, 10)
        # me_code = int(me_code) if me_code else 0
        # me_code += 36
        # me_code = chng_frm_base(str(me_code), 10, 36)

        # print(me_code)

        defaults = {}
        defaults.update(kwargs)

        return super().get_form(request, obj, **defaults)

    def ajax_menu_form_search(self, request, extra_context=None):

        type = request.POST.get("type")
        result = None

        if type == "group":
            result = (
                Group.objects.all().order_by("gr_order", "pk").annotate(subject=F("gr_subject"))
            )
        elif type == "board":
            result = (
                Board.objects.all()
                .order_by("bo_order", "bo_table")
                .annotate(subject=F("bo_subject"))
            )

        result_list = []
        bbs_subject_title = ""

        if result:
            for row in result:

                bbs_subject_title = _("게시판제목") if type == "board" else _("제목")

                link = ""

                if type == "group":
                    # link = reverse("")
                    link = ""
                elif type == "board":
                    link = get_pretty_url(row.bo_table)

                row.link = link
                result_list.append(row)

        context = {"result_list": result_list, "bbs_subject_title": bbs_subject_title, "type": type}

        return TemplateResponse(request, "admin/site_menu/menu_form_search.html", context)

    def changelist_redirect(self):
        changelist_url = admin_url(Site_menu, "changelist")
        return HttpResponseRedirect(changelist_url)

    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}

        site_menu_form = SiteMenuForms(request.POST or None)
        if "csrfmiddlewaretoken" in request.POST and site_menu_form.is_valid():
            site_menu_form.save()
            # Configs.clear_cache()
            # info(request, _("Settings were successfully updated."))
            return self.changelist_redirect()

        # extra_context["sitemenu_form"] = site_menu_form
        extra_context["title"] = "{} {}".format(
            _("Change"),
            force_str(Site_menu._meta.verbose_name_plural),
        )

        return super().changelist_view(request, extra_context)

    def add_menu_form(self, request, form_url="", extra_context=None):
        return self.changeform_view(request, None, form_url, extra_context)


class New_win_Admin(ModelAdmin):
    # 관리자 리스트 페이지에서 노출되는 필드
    list_display = [
        "nw_subject",
        "nw_device",
        "nw_begin_time",
        "nw_end_time",
        "nw_disable_hours",
        "nw_left",
        "nw_top",
        "nw_width",
        "nw_height",
    ]

    exclude = ("nw_content_html",)

    def get_form(self, request, obj=None, **kwargs):
        form = super(New_win_Admin, self).get_form(request, obj, **kwargs)

        form_initials = {
            "nw_disable_hours": 24,
            "nw_left": 10,
            "nw_top": 10,
            "nw_width": 450,
            "nw_height": 500,
        }

        for k, v in form_initials.items():
            form.base_fields[k].initial = v

        # form.base_fields["nw_subject"].widget = forms.TextInput(attrs={"class": "input-control"})
        form.base_fields["nw_subject"].widget = forms.TextInput(attrs={"class": "vTextField"})

        return form


# 사이트메뉴 등록
@admin.register(ContentPage)
class ContentPageAdmin(ModelAdmin):
    list_display = ("co_id", "co_subject", "co_skin", "co_order", "co_use", "co_updated_at")
    list_filter = ("co_use", "co_skin")
    search_fields = ("co_id", "co_subject", "co_seo_title", "co_content")
    ordering = ("co_order", "co_id")


class FAQItemInline(TabularInline):
    model = FAQItem
    extra = 1
    fields = ("fa_subject", "fa_order", "fa_use")
    ordering = ("fa_order", "fa_id")


@admin.register(Editor_attachments)
class EditorAttachmentAdmin(ModelAdmin):
    list_display = ("id", "name", "file_display", "uploaded")
    search_fields = ("name", "filepath", "file")
    list_filter = ("uploaded",)
    ordering = ("-uploaded", "-id")
    readonly_fields = ("name", "file", "filepath", "uploaded")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("File"))
    def file_display(self, obj):
        return compact_identifier(obj.file or obj.filepath or "-", 36, 12)


@admin.register(FAQMaster)
class FAQMasterAdmin(ModelAdmin):
    inlines = [FAQItemInline]
    list_display = ("fm_id", "fm_subject", "fm_order", "fm_use")
    list_filter = ("fm_use",)
    search_fields = ("fm_subject", "fm_head_html", "fm_tail_html")
    ordering = ("fm_order", "fm_id")


@admin.register(FAQItem)
class FAQItemAdmin(ModelAdmin):
    list_display = ("fa_id", "master", "fa_subject", "fa_order", "fa_use")
    list_filter = ("fa_use", "master")
    search_fields = ("fa_subject", "fa_content", "master__fm_subject")
    ordering = ("master_id", "fa_order", "fa_id")


class PollChoiceInline(TabularInline):
    model = PollChoice
    extra = 2
    fields = ("num", "content", "count")
    ordering = ("num",)


@admin.register(Poll)
class PollAdmin(ModelAdmin):
    inlines = [PollChoiceInline]
    list_display = ("po_id", "po_subject", "po_date", "po_use", "po_level", "po_point")
    list_filter = ("po_use", "po_date")
    search_fields = ("po_subject", "po_etc")
    ordering = ("-po_date", "-po_id")


@admin.register(PollChoice)
class PollChoiceAdmin(ModelAdmin):
    list_display = ("id", "poll", "num", "content", "count")
    list_filter = ("poll",)
    search_fields = ("content", "poll__po_subject")
    ordering = ("poll_id", "num")


@admin.register(PollVote)
class PollVoteAdmin(ModelAdmin):
    list_display = ("id", "poll", "choice", "user", "session_key", "ip", "created_at")
    list_filter = ("poll", "choice", "created_at")
    search_fields = ("poll__po_subject", "choice__content", "user__username", "session_key", "ip")
    ordering = ("-created_at", "-id")


@admin.register(PollComment)
class PollCommentAdmin(ModelAdmin):
    list_display = ("pc_id", "poll", "pc_name", "pc_datetime", "user", "pc_ip")
    list_filter = ("poll", "pc_datetime")
    search_fields = ("poll__po_subject", "pc_name", "pc_idea", "user__username")
    ordering = ("-pc_datetime", "-pc_id")



admin.site.register(Site_menu, Site_menu_admin)

# 팝업 메뉴 등록
admin.site.register(New_win, New_win_Admin)
