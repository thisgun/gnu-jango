from django.core.paginator import Paginator
from gnu_jango.config import config


class Gnu_Paginator(Paginator):
    def __init__(self, object_list, per_page, orphans=0, allow_empty_first_page=True, **kwargs):
        super().__init__(object_list, per_page, orphans, allow_empty_first_page)

        is_mobile = kwargs.get("is_mobile", 0)
        current_page = kwargs.get("current_page", 0)

        write_pages = config.cf_mobile.pages if is_mobile else config.cf_write_pages
        start_page = ((int)((current_page - 1) / write_pages) * write_pages) + 1
        end_page = start_page + write_pages - 1

        if end_page >= self.num_pages:
            end_page = self.num_pages

        self.start_page = int(start_page)
        self.before_page = int(start_page) - 1
        self.end_page = int(end_page)
        self.next_page = int(end_page) + 1
        self.write_pages = write_pages
        self.current_page = int(current_page)
        self.loop_page = range(start_page, end_page + 1)
