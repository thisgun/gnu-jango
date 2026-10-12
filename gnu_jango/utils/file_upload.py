import datetime
import os
import uuid

from django.conf import settings

def file_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    d = datetime.datetiem.now()
    filepath = d.strftime("%Y/%m/%d")
    suffix = d.strftime("%Y%m%d%H%M%S")
    filename = "%s_%s.%s" % (uuid.uuid4().hex, suffix, ext)
    return os.path.join(filepath, filename)

# https://thecodelearners.com/python-django-multiple-files-validation-and-uploads/
#This function uploads multiple files and returns the name of file
def file_upload_interface(request, file_list, dir_path = "uploads/", allowed_mime_types=[]):
    if not isinstance(file_list, list):
        file_list=list(file_list)
    directory = os.path.join(settings.BASE_DIR, dir_path)
    info={
        "files" : []
    }
    for file in file_list:
        file_name= file._name
        file_mime = file.content_type.split('/')[1]
        path= "{}{}".format(directory, file_name)

        is_allowed_to_upload=False
        #check allowed mime types if that file does not belong to mime type remove it
        if len(allowed_mime_types) > 0:
            if file_mime in  allowed_mime_types:
                is_allowed_to_upload=True
        else:
            is_allowed_to_upload=True

        if is_allowed_to_upload is True:
            with open(path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
                info["files"].append(file_name)
    return info