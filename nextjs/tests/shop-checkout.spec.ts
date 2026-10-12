import { test, expect, request as pwRequest } from '@playwright/test';

/**
 * 쇼핑몰 결제 종단 시나리오 — Playwright API 호출만으로 검증.
 * UI 클릭 없이도 prepare → confirm → 주문 상세까지 흐름 보장.
 *
 *   - env 기반 테스트 계정 로그인
 *   - 상품 카트 추가
 *   - PG prepare → confirm (KCP test 사이트코드)
 *   - 주문 상세 GET → od_status='주문', od_receipt_price 일치
 *
 * CI 환경에선 PHP API (/api/v1) 가 같이 떠 있어야 통과. dev 머신 외에선
 * skip 처리 권장 (test.skip).
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? process.env.LOCAL_APP_URL ?? 'http://127.0.0.20';
const API = `${BASE.replace(/\/+$/, '')}/api/v1`;
const PRODUCT_ID =
  process.env.SHOP_E2E_PRODUCT_ID ?? process.env.LOCAL_SMOKE_SHOP_PRODUCT_ID ?? '1446772772';
const loginId = process.env.LOCAL_SMOKE_LOGIN_ID || process.env.E2E_LOGIN_ID || '';
const loginPassword = process.env.LOCAL_SMOKE_LOGIN_PASSWORD || process.env.E2E_LOGIN_PASSWORD || '';

async function login(req: Awaited<ReturnType<typeof pwRequest.newContext>>) {
  const r = await req.post(`${API}/auth/login`, {
    data: { mb_id: loginId, mb_password: loginPassword },
  });
  if (!r.ok()) throw new Error(`login failed: ${r.status()}`);
  const body = await r.json();
  return body.data.token as string;
}

test.describe('쇼핑몰 결제 종단 흐름', () => {
  test.skip(!process.env.RUN_SHOP_E2E, 'shop e2e — RUN_SHOP_E2E=1 set 시만 실행');
  test.skip(!loginId || !loginPassword, 'Set LOCAL_SMOKE_LOGIN_ID and LOCAL_SMOKE_LOGIN_PASSWORD to run shop e2e.');

  test('KCP 신용카드 prepare → confirm → 주문 상세 일치', async () => {
    const req = await pwRequest.newContext();
    const token = await login(req);
    const headers = { Authorization: `Bearer ${token}` };

    // 카트 추가
    await req.post(`${API}/shop/cart`, {
      headers,
      data: { it_id: PRODUCT_ID, ct_qty: 1 },
    });

    // prepare
    const prepRes = await req.post(`${API}/shop/payment/prepare`, {
      headers,
      data: {
        od_name: '최고관리자',
        od_hp: '010-2222-3332',
        od_zip1: '062',
        od_zip2: '53',
        od_addr1: '서울 강남구 도곡로1길 14',
        od_settle_case: '신용카드',
      },
    });
    expect(prepRes.ok(), 'prepare ok').toBeTruthy();
    const prep = await prepRes.json();
    const orderId = prep.data.order_id;
    const amount = prep.data.amount;

    // confirm — KCP T0000 시뮬레이션
    const confRes = await req.post(`${API}/shop/payment/confirm`, {
      headers,
      data: {
        pg_service: 'kcp',
        order_id: orderId,
        amount,
        res_cd: '0000',
        enc_info: 'X',
        enc_data: 'Y',
        tran_cd: '00100000',
        site_cd: 'T0000',
      },
    });
    expect(confRes.ok(), 'confirm ok').toBeTruthy();

    // 주문 상세
    const detRes = await req.get(`${API}/shop/orders/${orderId}`, { headers });
    expect(detRes.ok(), 'detail ok').toBeTruthy();
    const det = await detRes.json();
    expect(det.data.od_status).toBe('주문');
    expect(det.data.od_receipt_price).toBe(amount);
  });

  test('주문 취소 — 재고/포인트 복구', async () => {
    const req = await pwRequest.newContext();
    const token = await login(req);
    const headers = { Authorization: `Bearer ${token}` };

    const before = await (await req.get(`${API}/shop/points/summary`, { headers })).json();
    const balBefore = before.data.balance as number;

    await req.post(`${API}/shop/cart`, {
      headers,
      data: { it_id: PRODUCT_ID, ct_qty: 1 },
    });

    const prep = await (
      await req.post(`${API}/shop/payment/prepare`, {
        headers,
        data: {
          od_name: '최고관리자',
          od_hp: '010-2222-3332',
          od_zip1: '062',
          od_zip2: '53',
          od_addr1: '서울 강남구 도곡로1길 14',
          od_settle_case: '신용카드',
          point_use: 1000,
        },
      })
    ).json();

    await req.post(`${API}/shop/payment/confirm`, {
      headers,
      data: {
        pg_service: 'kcp',
        order_id: prep.data.order_id,
        amount: prep.data.amount,
        res_cd: '0000',
        enc_info: 'X',
        enc_data: 'Y',
        tran_cd: '00100000',
        site_cd: 'T0000',
      },
    });

    const paid = await (await req.get(`${API}/shop/points/summary`, { headers })).json();
    expect(paid.data.balance, 'point used').toBe(balBefore - 1000);

    // 취소
    const cancelRes = await req.patch(`${API}/shop/orders/${prep.data.order_id}`, {
      headers,
      data: { reason: 'e2e 취소 테스트' },
    });
    expect(cancelRes.ok(), 'cancel ok').toBeTruthy();

    const after = await (await req.get(`${API}/shop/points/summary`, { headers })).json();
    expect(after.data.balance, 'point refunded').toBe(balBefore);
  });
});
