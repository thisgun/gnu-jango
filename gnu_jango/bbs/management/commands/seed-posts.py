from faker import Faker
from django.core.management.base import BaseCommand, CommandError
from django_seed import Seed
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from gnu_jango import defaults
from gnu_jango.bbs.models import Post, Board
from gnu_jango.bbs.utils import get_board, get_next_num
from gnu_jango.utils.cache import gnu_delete_cache

user_model_name = get_user_model()

# 구글에서 django faker 생성 으로 검색
# https://docs.djangoproject.com/en/4.0/howto/custom-management-commands/
# https://github.com/Brobin/django-seed
# https://faker.readthedocs.io/en/latest/locales/ko_KR.html


class Command(BaseCommand):
    help = _("이 커맨드를 통해 랜덤한 게시글 데이터를 만듭니다.")

    def add_arguments(self, parser):
        parser.add_argument("--number", default=2, type=int, help=_("생성할 게시글 수 입력"))
        # board_id 보다 bo_table 입력을 우선시 합니다.
        parser.add_argument("--bo_table", default=None, help=_("생성할 게시판 bo_table 입력"))
        parser.add_argument("--board_id", default=None, type=int, help=_("생성할 게시판 ID 입력"))

        # 게시글 카테고리
        parser.add_argument("--ca_name", default=None, type=int, help=_("게시글 카테고리 입력"))

    def handle(self, *args, **options):
        number = options.get("number")
        # board_id 보다 bo_table 입력을 우선시 합니다.
        bo_table = options.get("bo_table")
        board_id = options.get("board_id")
        ca_name = options.get("ca_name")
        board = None

        if bo_table:
            board = get_board(bo_table=bo_table)
        elif board_id:
            board = get_board(pk=board_id)

        if not board:
            board = Board.objects.all().first()

        if not board:
            raise CommandError(_("게시글을 생성할 게시판이 없습니다. 게시판을 먼저 만들거나 --bo_table/--board_id를 지정하세요."))

        self.stdout.write(
            _("대상 게시판: %(bo_table)s (%(bo_subject)s)")
            % {"bo_table": board.bo_table, "bo_subject": board.bo_subject}
        )
        seeder = Seed.seeder(locale="ko_KR")

        ko_kr_fake = Faker("ko.KR")

        seeder.add_entity(
            Post,
            number,
            {
                "board": board,
                "ca_name": ca_name,
                "is_notice": 0,
                "wr_ip": lambda x: seeder.faker.ipv4_private(),
                # "wr_name": lambda x: seeder.faker.name_nonbinary(),
                "wr_name": lambda x: ko_kr_fake.name_nonbinary(),
                "wr_email": lambda x: seeder.faker.email(),
                "wr_subject": lambda x: ko_kr_fake.bs(),
                # "wr_content": lambda x: seeder.faker.sentence(),
                "wr_content": lambda x: seeder.faker.paragraph(100, True),
                # "wr_content": lambda x: ko_kr_fake.text(max_nb_chars=160),
                "wr_homepage": "",
                "wr_nogood": 0,
                "wr_good": 0,
                "wr_hit": 0,
                "wr_link2_hit": 0,
                "wr_link1_hit": 0,
                "wr_link1": "",
                "wr_link2": "",
                "wr_parent": 0,
                "wr_reply": "",
                "wr_num": lambda x: get_next_num(board_id=board.id),
                "wr_file": 0,
                "wr_comment": 0,
                "wr_last": None,
                "wr_slug": None,
                "wr_datetime": timezone.now(),
            },
        )

        seeder.execute()

        self.stdout.write(
            self.style.SUCCESS(
                _("%(bo_title)s 게시판에 %(number)s 수의 게시글이 작성되었습니다.")
                % {"bo_title": board.bo_subject, "number": number}
            )
        )

        # 캐시 삭제
        cache_key = "latest-%s-%s" % (str(board.id), defaults.BBS_CACHE_ROWS)

        # 기본 LocMemCache 캐시의 경우 실행하는 주제가 달라서, 접근이 불가하여 삭제하지 못함
        gnu_delete_cache(cache_key)
