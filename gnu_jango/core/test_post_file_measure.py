"""Saving an attachment measures a file once and leaves no file from storage open."""
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from gnu_jango.bbs.models import Post_file
from gnu_jango.testing.factories import PostFactory


@pytest.fixture
def post(db, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return PostFactory()


def attachment(post, **values):
    return Post_file(board=post.board, post=post, bf_no=0, bf_source="hello.zip", **values)


def test_a_new_upload_is_measured(post):
    post_file = attachment(post, bf_file=SimpleUploadedFile("hello.zip", b"PK-test-bytes"))
    post_file.save()
    assert post_file.bf_filesize == len(b"PK-test-bytes")


def test_a_stored_file_of_unknown_size_is_measured_and_closed_again(post):
    post_file = attachment(post)
    post_file.bf_file.save("hello.zip", ContentFile(b"PK-test-bytes"), save=False)
    post_file.save()
    assert post_file.bf_filesize == len(b"PK-test-bytes")
    assert post_file.bf_file._file is None or post_file.bf_file.closed


def test_saving_a_measured_attachment_does_not_open_its_file(post):
    post_file = attachment(post, bf_file=SimpleUploadedFile("hello.zip", b"PK-test-bytes"))
    post_file.save()
    stored = Post_file.objects.get(pk=post_file.pk)
    with patch.object(stored.bf_file.storage, "open", side_effect=AssertionError("opened")):
        stored.bf_download += 1
        stored.save()
    assert stored.bf_filesize == len(b"PK-test-bytes")
