from gnu_jango.bbs.models import Group, Board
from django.db import IntegrityError

def add_sample_data():
    g1 = Group(gr_id='커뮤니티', gr_subject='커뮤니티')
    try:
        g1.save()
    except IntegrityError as e:
        pass
        
    if g1.id:
        tmp_subjects = ["공지사항", "질문답변", "자유게시판", "갤러리"]
        
        for subject in tmp_subjects:
            
            bo_skin = 'gallery' if subject == '갤러리' else 'basic'
            
            b1 = Board(group_id=g1.id, bo_table=subject, bo_subject=subject, bo_skin=bo_skin, bo_mobile_skin=bo_skin,

                        bo_list_level       = '1',
                        bo_read_level       = '1',
                        bo_write_level      = '1',
                        bo_reply_level      = '1',
                        bo_comment_level    = '1',
                        bo_html_level       = '1',
                        bo_link_level       = '1',
                        bo_count_modify     = '1',
                        bo_count_delete     = '1',
                        bo_upload_level     = '1',
                        bo_download_level   = '1',
                        bo_read_point       = '-1',
                        bo_write_point      = '5',
                        bo_comment_point    = '1',
                        bo_download_point   = '-20',
                        bo_use_category     = '0',
                        bo_category_list    = '',
                        bo_use_sideview     = '0',
                        bo_use_file_content = '0',
                        bo_use_secret       = '0',
                        bo_use_dhtml_editor = '0',
                        bo_use_rss_view     = '0',
                        bo_use_good         = '0',
                        bo_use_nogood       = '0',
                        bo_use_name         = '0',
                        bo_use_signature    = '0',
                        bo_use_ip_view      = '0',
                        bo_use_list_view    = '0',
                        bo_use_list_content = '0',
                        bo_use_email        = '0',
                        bo_table_width      = '100',
                        bo_subject_len      = '60',
                        bo_mobile_subject_len      = '30',
                        bo_page_rows        = '15',
                        bo_mobile_page_rows = '15',
                        bo_new              = '24',
                        bo_hot              = '100',
                        bo_image_width      = '835',
                        bo_content_head     = '',
                        bo_content_tail     = '',
                        bo_mobile_content_head     = '',
                        bo_mobile_content_tail     = '',
                        bo_insert_content   = '',
                        bo_gallery_cols     = '4',
                        bo_gallery_width    = '202',
                        bo_gallery_height   = '150',
                        bo_mobile_gallery_width = '125',
                        bo_mobile_gallery_height= '100',
                        bo_upload_count     = '2',
                        bo_upload_size      = '1048576',
                        bo_reply_order      = '1',
                        bo_use_search       = '0',
                        bo_order            = '0'
                       )
            b1.save()
            
    return Board.objects.all()