"""Courier list and delivery inquiry links (YoungCart extend/shop.extend.php G5_DELIVERY_COMPANY,
lib/shop.lib.php get_delivery_inquiry / get_delivery_company)."""
from urllib.parse import quote

SELF_DELIVERY = "자체배송"

# (name, tracking URL prefix the invoice number is appended to, customer phone)
DELIVERY_COMPANIES = (
    ("경동택배", "https://kdexp.com/service/delivery/etc/delivery.do?barcode=", "1899-5368"),
    ("대신택배", "https://www.ds3211.co.kr/freight/internalFreightSearch.ht?billno=", "043-222-4582"),
    ("로젠택배", "https://www.ilogen.com/m/personal/trace.pop/", "1588-9988"),
    ("우체국", "https://m.epost.go.kr/postal/mobile/mobile.trace.RetrieveDomRigiTraceList.comm?ems_gubun=E&sid1=", "1588-1300"),
    ("한진택배", "https://www.hanjin.co.kr/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038&schLang=KR&wblnumText2=", "1588-0011"),
    ("롯데택배", "https://www.lotteglogis.com/open/tracking?invno=", "1588-2121"),
    ("CJ대한통운", "https://trace.cjlogistics.com/next/tracking.html?wblNo=", "1588-1255"),
    ("GS25편의점택배", "https://www.cvsnet.co.kr/invoice/tracking.do?invoice_no=", "1577-1287"),
    ("합동택배", "https://hdexp.co.kr/deliverySearch2.hd?barcode=", "1899-3392"),
    ("CU편의점택배", "https://www.cupost.co.kr/postbox/delivery/localResult.cupost?invoice_no=", "1577-1287"),
    ("천일택배", "http://www.chunil.co.kr/HTrace/HTrace.jsp?transNo=", "1877-6606"),
    ("건영택배", "https://www.kunyoung.com/goods/goods_01.php?mulno=", "031-460-2700"),
    ("우리택배", "http://www.honamlogis.co.kr/04estimate/songjang_list.php?c_search1=", "031-376-6070"),
    ("일양로지스", "https://www.ilyanglogis.com/functionality/popup_result.asp?hawb_no=", "1588-0002"),
    ("EMS", "https://service.epost.go.kr/trace.RetrieveEmsRigiTraceList.comm?POST_CODE=", "1588-1300"),
    ("DHL", "https://www.dhl.com/kr-ko/home/tracking.html?tracking-id=", "1588-1588-0001"),
    ("FedEx", "https://www.fedex.com/fedextrack/?trknbr=", "02-3496-7777"),
    ("UPS", "https://www.fedex.com/fedextrack/?trknbr=", "02-3496-7777"),
)


def find_delivery_company(company):
    """The courier entry for ``company``: an exact name, else YoungCart's partial match."""
    company = str(company or "").strip()
    if not company:
        return None
    for entry in DELIVERY_COMPANIES:
        if entry[0] == company:
            return entry
    # get_delivery_inquiry: strpos(entry, company) over "name^url^tel"
    for entry in DELIVERY_COMPANIES:
        if company in entry[0]:
            return entry
    return None


def delivery_inquiry(company, invoice):
    """``{"url", "tel"}`` for an invoice of a listed courier; empty strings otherwise
    (self delivery, an unknown courier, or no invoice)."""
    invoice = str(invoice or "").strip()
    entry = find_delivery_company(company) if invoice else None
    if not entry:
        return {"url": "", "tel": ""}
    name, url, tel = entry
    return {"url": f"{url}{quote(invoice, safe='-')}", "tel": tel}


def delivery_company_choices(current=""):
    """The admin select: none, self delivery, then the courier list (get_delivery_company)."""
    choices = [("", "없음"), (SELF_DELIVERY, SELF_DELIVERY)] + [(name, name) for name, _url, _tel in DELIVERY_COMPANIES]
    current = str(current or "").strip()
    if current and current not in {value for value, _label in choices}:
        # keep an imported or older value selectable instead of silently dropping it
        choices.append((current, current))
    return choices


def delivery_company_form_field(current="", *, label, widget=None, help_text=""):
    """A select of the courier list for an admin form; a stored value off the list stays selectable."""
    from django import forms

    return forms.ChoiceField(
        label=label,
        choices=delivery_company_choices(current),
        required=False,
        help_text=help_text,
        **({"widget": widget} if widget else {}),
    )
