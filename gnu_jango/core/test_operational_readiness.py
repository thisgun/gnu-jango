from django.http import Http404
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from gnu_jango.core import views as core_views
from gnu_jango.core.models import MailCampaign, MailSendLog
from gnu_jango.core.tasks import send_mail_campaign_task
from gnu_jango.shop.models import ShopCategory, ShopProduct, ShopQA, ShopReview


class OperationalReadinessTests(TestCase):
    def test_api_schema_and_docs_are_exposed(self):
        schema = self.client.get(reverse("api-schema"))
        self.assertEqual(schema.status_code, 200)

        docs = self.client.get(reverse("api-docs"))
        self.assertEqual(docs.status_code, 200)

        redoc = self.client.get(reverse("api-redoc"))
        self.assertEqual(redoc.status_code, 200)

    def test_custom_error_handlers_render_safe_pages(self):
        request = RequestFactory().get("/missing")
        request.user = AnonymousUser()

        response_404 = core_views.error_404(request, Http404("missing"))
        self.assertEqual(response_404.status_code, 404)
        self.assertIn("페이지를 찾을 수 없습니다", response_404.content.decode("utf-8"))

        response_403 = core_views.error_403(request, PermissionError("forbidden"))
        self.assertEqual(response_403.status_code, 403)
        self.assertIn("접근 권한이 없습니다", response_403.content.decode("utf-8"))

        response_500 = core_views.error_500(request)
        self.assertEqual(response_500.status_code, 500)
        self.assertIn("서버 오류", response_500.content.decode("utf-8"))

    def test_shop_review_and_qna_survive_product_deletion(self):
        category = ShopCategory.objects.create(ca_id="10", ca_name="Category")
        product = ShopProduct.objects.create(
            it_id="P-DELETE",
            category=category,
            it_name="Product to delete",
            it_price=1000,
        )
        review = ShopReview.objects.create(
            product=product,
            is_subject="Review remains",
            is_content="Review content",
        )
        qna = ShopQA.objects.create(
            product=product,
            iq_subject="Question remains",
            iq_question="Question content",
        )

        product.delete()
        review.refresh_from_db()
        qna.refresh_from_db()

        self.assertIsNone(review.product_id)
        self.assertIsNone(qna.product_id)

    @override_settings(
        MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    )
    def test_mail_campaign_task_records_delivery_logs(self):
        campaign = MailCampaign.objects.create(
            title="Operational mail",
            recipient_group="test",
            subject="Queue test",
            body="Queued body",
            from_email="webmaster@example.com",
            recipient_count=1,
            status="sending",
        )

        result = send_mail_campaign_task.run(campaign.pk, [{"email": "member@example.com"}])
        campaign.refresh_from_db()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(campaign.status, "sent")
        self.assertEqual(campaign.sent_count, 1)
        self.assertEqual(campaign.failed_count, 0)
        self.assertEqual(MailSendLog.objects.filter(campaign=campaign, status="success").count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["member@example.com"])
