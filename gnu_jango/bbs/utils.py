from django.db.models import Min
from urllib.parse import quote
from django.contrib.auth import get_user_model
# from django.template.defaultfilters import slugify  # new
from django.utils.text import slugify

from gnu_jango import defaults
from gnu_jango.config import config
from gnu_jango.utils import lib, editor
from gnu_jango.utils.users import (
    get_sideview,
    get_sideview_data,
    get_user_nickname,
    get_user_realname,
)

# 템플릿 폴더의 사용 테마의 경로를 얻음
def get_theme_path():
    if not getattr(config, "cf_theme"):
        return defaults.TEMPLATE_PATH + "/" + getattr(config, "cf_theme")
    else:
        return ""


# 스킨디렉토리를 list 형식으로 얻음
def get_skin_choices(skin_gubun, id, name, selected="", event=""):
    skins = []

    if not getattr(config, "cf_theme"):
        dirs = lib.get_skin_dir(skin_gubun, get_theme_path() + "/" + defaults.SKIN_DIR)
        if len(dirs) == 0:
            for dir in dirs:
                skins.append("theme/" + dir)

    skins = list(set(skins + lib.get_skin_dir(skin_gubun)))

    return skins


def get_group(**kwargs):
    pass


# 모델 board 의 한 레코드를 queryset 형식으로 얻음
def get_board(**kwargs):

    pk = kwargs.get("pk", 0)
    bo_table = kwargs.get("bo_table", "")
    board = kwargs.get("board")

    from .models import Board

    # https://tech.toktokhan.dev/2021/08/26/ORM-defer/

    # instance 형식으로 리턴한다. ( queryset 이 아님!!! )

    if board:
        row = board
    elif pk:
        row = Board.objects.get(pk=pk)
    else:
        row = Board.objects.get(bo_table=bo_table)

    # 게시판 스킨 경로를 구하여 board_skin_path 키에 추가한다.
    row.board_skin_path = get_board_skin_path(row, True)

    return row


def get_board_title(request, board):
    return (
        board.bo_mobile_subject
        if (lib.is_mobile(request) and board.bo_mobile_subject)
        else board.bo_subject
    )


# 모델 board 의 다수 레코드를 기록하거나 다수 레코드를 dict 형식으로 얻음
def get_tmp_boards(row):

    if not hasattr(get_tmp_boards, "rows"):
        get_tmp_boards.rows = {}

    get_tmp_boards.rows[row.id] = row

    return get_tmp_boards.rows


# 스킨 path
def get_skin_path():
    pass


# 게시판 스킨 경로를 얻음
def get_board_skin_path(board, is_register_statics=False):
    path = "skin/board/" + board.bo_skin + "/"

    # settings.STATICFILES_DIRS 경로에 등록했기 때문에 리턴값이 각각 다름
    if is_register_statics:
        path = "board/" + board.bo_skin + "/"

    return path


def board_display_name(board, post=None, request=None):
    if post:
        return post.wr_name

    return ""


def get_user_board_wrname(user, board):

    wr_name = get_user_nickname(user) if board.bo_use_name else get_user_realname(user)

    return wr_name


def get_next_num(is_comment=False, **kwargs):

    board_id = kwargs.get("board_id", 0)
    bo_table = kwargs.get("bo_table", "")
    board_filter = {}
    if board_id:
        board_filter["board_id"] = board_id
    elif bo_table:
        board_filter["board__bo_table"] = bo_table

    # 댓글이면 댓글테이블에서
    if is_comment:
        from .models import Comment

        # obj = Comment.objects.filter(board_id=board_id).aggregate(Min('order_num'))

        comments = Comment.objects.filter(**board_filter) if board_filter else Comment.objects.all()
        obj = comments.aggregate(Min("order_num"))

        # 가장 작은 번호를 얻어
        return int(obj["order_num__min"] or 0) - 1

    else:  # 글이면 글테이블에서
        from .models import Post

        # if board_id:
        #     obj = Post.objects.filter(board_id=board_id).aggregate(Min('wr_num'))
        # else:
        #     obj = Post.objects.filter(bo_table=bo_table).aggregate(Min('wr_num'))

        posts = Post.objects.filter(**board_filter) if board_filter else Post.objects.all()
        obj = posts.aggregate(Min("wr_num"))

    # 가장 작은 번호를 얻어
    return int(obj["wr_num__min"] or 0) - 1


def is_board_admin(board, request=None):
    if request is None:
        return False
    return bool(get_board_admin_role(request.user, board))


def get_board_admin_role(user, board):
    """Return the Gnuboard admin role for this board, if the user has one."""
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    if user.is_superuser:
        return "super"

    username = user.get_username()
    group = getattr(board, "group", None)
    if group and group.gr_admin and group.gr_admin == username:
        return "group"
    if board and board.bo_admin and board.bo_admin == username:
        return "board"
    return ""


def get_board_admin(board):
    if not board or not board.bo_admin:
        return []
    user_model = get_user_model()
    return list(user_model.objects.filter(username=board.bo_admin).values_list("pk", flat=True))


def is_group_admin(user_id, group):
    if not group or not group.gr_admin:
        return False
    user_model = get_user_model()
    username = user_model.objects.filter(pk=user_id).values_list("username", flat=True).first()
    return bool(username and username == group.gr_admin)


def cut_str(str, int_len, suffix="…"):
    str_len = len(str)

    if str_len > int_len:
        return str[:int_len] + suffix
    else:
        return str


def view_file_link(file, width, height, content="", **kwargs):

    board = kwargs.get("board") or []
    # 파일의 폭이 게시판설정의 이미지폭 보다 크다면 게시판설정 폭으로 맞추고 비율에 따라 높이를 계산
    if board and width > board.bo_image_width and board.bo_image_width:
        rate = int(board.bo_image_width) / int(width)
        width = int(board.bo_image_width)
        height = int(height * rate)

    attrs = []

    if width:
        attrs.append("width='" + str(width) + "'")
        attrs.append("height='" + str(height) + "'")

    img = ""

    if board and file.bf_type > 0:
        attr_href = "#"
        img = '<a href="' + attr_href + '" target="_blank" class="view_image">'
        img += '<img src="' + file.url + '" alt="' + content + '"' + " ".join(attrs) + ">"
        img += "</a>"

    return img


def get_bbs_file(post_file_list, board, post):
    # files 는 파일을 다 저장하며, only_images 는 이미지 파일만 저장, only_files는 이미지파일을 제외한 나머지 파일들을 저장한다.
    image_files = []
    etc_files = []
    files = []

    if post_file_list:
        for post_file in post_file_list:
            if post_file.bf_file:

                post_file.url = post_file.bf_file.url
                post_file.href = "/api/v1/boards/%s/%s/files/%s/download" % (
                    quote(board.bo_table), post.legacy_wr_id or post.pk, post_file.bf_no
                )
                post_file.path = ""
                post_file.size = post_file.bf_filesize
                post_file.datetime = post_file.bf_datetime
                post_file.source = post_file.bf_source
                post_file.content = post_file.bf_content
                post_file.view = view_file_link(
                    post_file,
                    post_file.bf_width,
                    post_file.bf_height,
                    post_file.content,
                    board=board,
                )
                post_file.file = post_file.bf_file
                post_file.image_width = post_file.bf_width if post_file.bf_width else 640
                post_file.image_height = post_file.bf_height if post_file.bf_height else 480
                post_file.image_type = post_file.bf_type
                post_file.download = post_file.bf_download

            files.append(post_file)

            if post_file.bf_type > 0:
                image_files.append(post_file)
            else:
                etc_files.append(post_file)

    return files, image_files, etc_files


# 제목을 변환
def conv_subject(subject, len, suffix=""):
    return cut_str(subject, len, suffix)


def get_bbs_view(post, board, skin_url, **kwargs):

    kwargs["is_detailview"] = 1
    return get_bbs_list(post, board, skin_url, 255, **kwargs)


def api_Serializer_post(post, request=None):

    # Keep this cache request-scoped to avoid stale data across users or requests.
    cache = None
    if request is not None and post.id is not None:
        cache = getattr(request, "_gnu_jango_api_serializer_posts", None)
        if cache is None:
            cache = {}
            setattr(request, "_gnu_jango_api_serializer_posts", cache)

        if post.id in cache:
            return cache[post.id]

    board = get_board(pk=post.board_id)

    serialized_post = get_bbs_list(post, board, "", request=request)

    if cache is not None:
        cache[post.id] = serialized_post

    return serialized_post

def get_bbs_list(row, board, skin_url="", subject_len=40, **kwargs):

    files = kwargs.get("files") or []
    request = kwargs.get("request") or None
    is_detailview = kwargs.get("is_detailview") or 0
    params = kwargs.get("params", {})

    if subject_len:
        row.subject = conv_subject(row.wr_subject, subject_len, "...")
    else:
        row.subject = conv_subject(row.wr_subject, board.bo_subject_len, "...")

    row.sideview_data = {}

    # 설정된 자리수 만큼만 이름 출력
    temp_name = row.wr_name[: getattr(config, "cf_cut_name")]

    if board.bo_use_sideview:
        # rest api 를 사용하기 위해 데이터를 sideview_data 에 저장한다.
        row.sideview_data = get_sideview_data(
            row.user_id, temp_name, row.wr_email, row.wr_homepage, request=request
        )
        # html 형식으로 sideview를 저장
        row.name = get_sideview(
            row.user_id, temp_name, row.wr_email, row.wr_homepage, request=request
        )
    else:
        row.name = '<span class="%s">%s</span>' % (
            "sv_user" if row.user_id else "sv_guest",
            lib.get_text(temp_name),
        )

    row.is_notice = 0
    row.ca_name_href = "#"
    row.ca_name = ""
    row.href = lib.get_params_merge_url(params, row.get_absolute_url())
    row.icon_reply = ""
    row.icon_secret = ""
    row.icon_new = ""
    row.file_count = 0
    row.icon_hot = ""
    row.icon_file = ""
    row.icon_link = ""
    row.comment_cnt = ""

    editor_contents = editor.editor_view_html("wr_content", row.wr_content, True)

    row.content = editor_contents["html"]
    row.editor_media = editor_contents["media"]

    if row.wr_comment:
        row.comment_cnt = '<span class="cnt_cmt">' + str(row.wr_comment) + "</span>"

    row.datetime2 = ""
    row.num = 0
    row.ip = row.wr_ip
    row.datetime = str(row.wr_datetime)[0:10]

    if row.datetime == defaults.TIME_YMD:
        row.datetime2 = str(row.wr_datetime)[11:16]
    else:
        row.datetime2 = str(row.wr_datetime)[5:10]

    row.link = row.link_href = row.link_hit = {}
    # 링크
    for i in range(1, defaults.BBS_LINK_COUNT + 1):
        row.link[i] = getattr(row, f"wr_link{i}", "")
        row.link_href[i] = "#"
        row.link_hit[i] = int(getattr(row, f"wr_link{i}_hit", 0))

    if row.wr_link1 or row.wr_link2:
        row.icon_link = '<i class="fa fa-link" aria-hidden="true"></i> '

    # 해당 글 전체파일, 해당 글 이미지파일만, 해당 글 이미지파일을 제외한 첨부파일
    row.files, row.image_files, row.etc_files = get_bbs_file(files, board, row)

    # print(files)

    row.file_count = len(row.files)
    if row.file_count:
        row.icon_file = '<i class="fa fa-download" aria-hidden="true"></i> '

    return row


def get_pretty_url(bo_table, post_id=0, **kwargs):

    board_pk = kwargs.get("board_pk")

    if bo_table == "Board" and board_pk:
        board = get_board(pk=board_pk)

        bo_table = board.bo_table

    # The Next.js site's short board URLs (core.views.nextjs25_short_board_theme serves them).
    if post_id:
        return "/%s/%s" % (quote(str(bo_table)), int(post_id))

    return "/%s/" % quote(str(bo_table))


def get_image_type_number(mimetype):
    imageTypeDict = {
        0: "UNKNOWN",
        1: "image/gif",
        2: "image/jpeg",
        3: "image/png",
        4: "application/x-shockwave-flash",
        5: "image/psd",
        6: "image/bmp",
        7: "image/tiff",
        8: "image/tiff",
        9: "application/octet-stream",
        10: "image/jp2",
        11: "application/octet-stream",
        12: "application/octet-stream",
        13: "application/x-shockwave-flash",
        14: "image/iff",
        15: "image/vnd.wap.wbmp",
        16: "image/xbm",
        17: "image/vnd.microsoft.icon",
        18: "image/webp",
    }

    for key, value in imageTypeDict.items():
        if value == mimetype:
            return key

    return 0

def generate_wr_slug(wr_subject, othis_pk=0, board_id=None):
    from .models import Post

    base_slug = slugify(wr_subject, allow_unicode=True) or "post"
    wr_slug = base_slug
    queryset = Post.objects.all()

    if board_id:
        queryset = queryset.filter(board_id=board_id)

    if othis_pk:
        queryset = queryset.exclude(pk=othis_pk)

    suffix = 1
    while queryset.filter(wr_slug=wr_slug).exists():
        wr_slug = "%s-%s" % (base_slug, suffix)
        suffix += 1

    return wr_slug
