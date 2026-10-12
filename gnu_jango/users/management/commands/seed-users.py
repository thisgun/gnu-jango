from django.core.management.base import BaseCommand
from django_seed import Seed
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

user_model_name = get_user_model()

# 구글에서 django faker 생성 으로 검색


class Command(BaseCommand):
    help = _("이 커맨드를 통해 랜덤한 테스트 유저 데이터를 만듭니다.")

    def add_arguments(self, parser):
        parser.add_argument("--number", default=2, type=int, help=_("유저를 생성할 수 입력"))

    def handle(self, *args, **options):
        number = options.get("number")
        seeder = Seed.seeder(locale="ko_KR")
        seeder.add_entity(
            user_model_name,
            number,
            {
                "is_staff": False,
                "is_superuser": False,
                "username": lambda x: seeder.faker.name(),
                "email": lambda x: seeder.faker.email(),
            },
        )
        seeder.execute()
        self.stdout.write(self.style.SUCCESS(_("%(number)s 명의 유저가 작성되었습니다.") % {"number": number}))
