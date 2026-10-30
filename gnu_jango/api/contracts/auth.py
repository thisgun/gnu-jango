"""Response contract of ``GET /api/v1/auth/me`` (``v1_auth.me_view``).

An anonymous request gets 401 (``api_error``); only the signed-in 200 shape is described here.
"""

from rest_framework import serializers


class CurrentMemberSerializer(serializers.Serializer):
    """``v1_auth.member_payload`` plus ``_own_contact_payload`` (the member's own phone/address)."""

    mb_no = serializers.IntegerField()
    mb_id = serializers.CharField()
    mb_name = serializers.CharField(allow_blank=True)
    mb_nick = serializers.CharField(allow_blank=True)
    mb_email = serializers.CharField(allow_blank=True)
    mb_level = serializers.IntegerField()
    mb_point = serializers.IntegerField()
    # absolute icon (or avatar) URL, or ""
    mb_icon_path = serializers.CharField(allow_blank=True)
    # ISO 8601 datetimes as plain strings ("" when unset)
    mb_datetime = serializers.CharField(allow_blank=True)
    mb_today_login = serializers.CharField()
    # 1 / 0 int flag
    mb_open = serializers.IntegerField()
    mb_open_date = serializers.CharField(allow_blank=True)
    mb_mailling = serializers.IntegerField()
    mb_mailling_date = serializers.CharField(allow_blank=True)
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    mb_hp = serializers.CharField(allow_blank=True)
    # always "": Profile keeps a single phone number (mb_hp)
    mb_tel = serializers.CharField(allow_blank=True)
    mb_zip = serializers.CharField(allow_blank=True)
    # mb_zip split after its third character
    mb_zip1 = serializers.CharField(allow_blank=True)
    mb_zip2 = serializers.CharField(allow_blank=True)
    mb_addr1 = serializers.CharField(allow_blank=True)
    mb_addr2 = serializers.CharField(allow_blank=True)
    # always ""
    mb_addr3 = serializers.CharField(allow_blank=True)
    mb_addr_jibeon = serializers.CharField(allow_blank=True)


class AuthMeSerializer(serializers.Serializer):
    member = CurrentMemberSerializer()
    is_super_admin = serializers.BooleanField()
