from django.template import Library

register = Library()


@register.simple_tag
def post_file_html(fileform):
    return fileform.as_p()
