from django import forms, template


from captcha.fields import ReCaptchaField

register = template.Library()


class DefaultCheckForm(forms.Form):
    captcha = ReCaptchaField()


@register.simple_tag
def capcha_html():

    # https://github.com/torchbox/django-recaptcha/issues/189
    # https://github.com/torchbox/django-recaptcha/issues/211

    # captcha = fields.ReCaptchaField(
    #     widget=widgets.ReCaptchaV2Checkbox(attrs={"name": "captcha-name"})
    # )

    form = DefaultCheckForm()
    html = form.as_p()

    return html
