from django.urls import reverse

# Register your models here.

def admin_url(model, url, object_id=None):
    """
    Returns the URL for the given model and admin url name.
    """
    opts = model._meta
    url = f"admin:{opts.app_label}_{opts.object_name.lower()}_{url}"
    args = ()
    if object_id is not None:
        args = (object_id,)
    return reverse(url, args=args)