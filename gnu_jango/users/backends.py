from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

# https://rahmanfadhil.com/django-login-with-email/
# https://docs.djangoproject.com/en/4.1/topics/auth/customizing/

UserModel = get_user_model()


class EmailBackend(ModelBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # 이메일로 로그인이 가능하게 함
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD) or kwargs.get(
                UserModel.get_email_field_name()
            )
        if username is None or password is None:
            return
        try:
            # user = UserModel._default_manager.get_by_natural_key(username)
            user = UserModel.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except UserModel.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a nonexistent user (#20760).
            UserModel().set_password(password)
        except UserModel.MultipleObjectsReturned:
            user = (
                UserModel.objects.filter(
                    Q(username__iexact=username) | Q(email__iexact=username)
                )
                .order_by("id")
                .first()
            )
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user


# class EmailBackend(ModelBackend):

#     def get_by_natural_key(self, username):
#         return self.get(**{self.model.USERNAME_FIELD: username})

#     def authenticate(self, request, username=None, password=None, **kwargs):
#         try:
#             user = UserModel.objects.get(Q(username__iexact=username) | Q(email__iexact=username))
#         except UserModel.DoesNotExist:
#             UserModel().set_password(password)
#             return
#         except UserModel.MultipleObjectsReturned:
#             user = UserModel.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).order_by('id').first()

#         if user.check_password(password) and self.user_can_authenticate(user):
#             return user
