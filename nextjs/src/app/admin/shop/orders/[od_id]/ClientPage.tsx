"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { toastSuccess, toastError } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { Order } from "@/lib/types";

const ORDER_STATUSES = [
  "주문",
  "입금",
  "준비",
  "배송",
  "완료",
  "취소",
  "교환요청",
  "반품요청",
  "교환",
  "반품",
  "품절",
];

export default function AdminOrderDetailPage() {
  const router = useRouter();
  const odId = useRuntimeRouteParam("od_id", "/admin/shop/orders/:od_id");

  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [newStatus, setNewStatus] = useState("");
  const [trackingNumber, setTrackingNumber] = useState("");
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    async function fetchOrder() {
      try {
        const res = await api.get<Order>(`/admin/shop/orders/${odId}`);
        if (res.data) {
          setOrder(res.data);
          setNewStatus(res.data.od_status);
        }
      } catch {
        toastError("주문 정보를 불러올 수 없습니다.");
        runtimeRouterPush(router, "/admin/shop/orders");
      } finally {
        setLoading(false);
      }
    }

    fetchOrder();
  }, [odId, router]);

  async function handleStatusUpdate() {
    setUpdating(true);
    try {
      await api.patch(`/admin/shop/orders/${odId}`, {
        od_status: newStatus,
        tracking_number: trackingNumber,
      });
      toastSuccess("주문 상태가 변경되었습니다.");
      setOrder((prev) => (prev ? { ...prev, od_status: newStatus } : prev));
    } catch {
      toastError("상태 변경에 실패했습니다.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleCancel() {
    if (!confirm("이 주문을 취소/환불 처리하시겠습니까?")) return;
    setUpdating(true);
    try {
      await api.patch(`/admin/shop/orders/${odId}/cancel`, {});
      toastSuccess("취소/환불 처리되었습니다.");
      setOrder((prev) => (prev ? { ...prev, od_status: "취소" } : prev));
      setNewStatus("취소");
    } catch {
      toastError("취소/환불 처리에 실패했습니다.");
    } finally {
      setUpdating(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-muted-foreground">로딩 중...</p>
      </div>
    );
  }

  if (!order) return null;

  const totalItemPrice =
    order.items?.reduce((sum, item) => sum + item.ct_price * item.ct_qty, 0) ??
    0;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">주문 상세 - {odId}</h1>
        <Badge
          variant={
            order.od_status === "취소"
              ? "destructive"
              : order.od_status === "완료"
                ? "outline"
                : "default"
          }
        >
          {order.od_status}
        </Badge>
      </div>

      {/* Order Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">주문 정보</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">주문번호:</span>{" "}
              <span className="font-medium">{order.od_id}</span>
            </div>
            <div>
              <span className="text-muted-foreground">주문일시:</span>{" "}
              {order.od_datetime}
            </div>
            <div>
              <span className="text-muted-foreground">결제방법:</span>{" "}
              {order.od_settle_case}
            </div>
            <div>
              <span className="text-muted-foreground">PG:</span> {order.od_pg}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Buyer Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">주문자 / 배송 정보</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-6 text-sm">
            <div className="space-y-2">
              <h4 className="font-semibold">주문자</h4>
              <p>
                {order.od_name} / {order.od_tel}
              </p>
              <p>{order.od_hp}</p>
              <p>{order.od_email}</p>
              <p>
                ({order.od_zip}) {order.od_addr1} {order.od_addr2}{" "}
                {order.od_addr3}
              </p>
            </div>
            <div className="space-y-2">
              <h4 className="font-semibold">받는 분</h4>
              <p>
                {order.od_b_name} / {order.od_b_tel}
              </p>
              <p>{order.od_b_hp}</p>
              <p>
                ({order.od_b_zip}) {order.od_b_addr1} {order.od_b_addr2}{" "}
                {order.od_b_addr3}
              </p>
            </div>
          </div>
          {order.od_memo && (
            <div className="mt-4 text-sm">
              <span className="text-muted-foreground">메모:</span>{" "}
              {order.od_memo}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Order Items */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">주문 상품</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>상품명</TableHead>
                <TableHead>옵션</TableHead>
                <TableHead>단가</TableHead>
                <TableHead>수량</TableHead>
                <TableHead>소계</TableHead>
                <TableHead>상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {order.items && order.items.length > 0 ? (
                order.items.map((item) => (
                  <TableRow key={item.ct_id}>
                    <TableCell className="font-medium">
                      {item.it_name}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {item.ct_option || "-"}
                    </TableCell>
                    <TableCell>{item.ct_price.toLocaleString()}원</TableCell>
                    <TableCell>{item.ct_qty}</TableCell>
                    <TableCell>
                      {(item.ct_price * item.ct_qty).toLocaleString()}원
                    </TableCell>
                    <TableCell>{item.ct_status}</TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="text-center text-muted-foreground"
                  >
                    상품 정보가 없습니다.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          <Separator className="my-4" />

          <div className="space-y-1 text-sm text-right">
            <p>
              상품금액: <strong>{totalItemPrice.toLocaleString()}원</strong>
            </p>
            <p>
              배송비:{" "}
              <strong>
                {(order.od_send_cost + order.od_send_cost2).toLocaleString()}원
              </strong>
            </p>
            <p>
              쿠폰할인:{" "}
              <strong>-{order.od_coupon.toLocaleString()}원</strong>
            </p>
            <p>
              포인트 사용:{" "}
              <strong>-{order.od_point.toLocaleString()}원</strong>
            </p>
            <Separator className="my-2" />
            <p className="text-base">
              총 결제금액:{" "}
              <strong className="text-primary">
                {order.od_receipt_price.toLocaleString()}원
              </strong>
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Status Change & Actions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">상태 변경</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-end gap-3">
            <div className="w-48 space-y-2">
              <Label>주문 상태</Label>
              <Select value={newStatus} onValueChange={setNewStatus}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ORDER_STATUSES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1 space-y-2">
              <Label htmlFor="tracking">운송장 번호</Label>
              <Input
                id="tracking"
                placeholder="운송장 번호를 입력하세요"
                value={trackingNumber}
                onChange={(e) => setTrackingNumber(e.target.value)}
              />
            </div>
            <Button onClick={handleStatusUpdate} disabled={updating}>
              {updating ? "처리 중..." : "상태 변경"}
            </Button>
          </div>

          <Separator />

          <div className="flex items-center justify-between">
            <Button
              variant="destructive"
              onClick={handleCancel}
              disabled={updating || order.od_status === "취소"}
            >
              취소/환불
            </Button>
            <Button
              variant="outline"
              onClick={() => runtimeRouterPush(router, "/admin/shop/orders")}
            >
              목록으로
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
