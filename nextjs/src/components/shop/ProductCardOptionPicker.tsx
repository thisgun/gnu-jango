"use client";

import { useId, useMemo, useState, type FormEvent } from "react";
import { ChevronDown, ShoppingCart } from "lucide-react";
import type { ShopProduct, ShopProductOption } from "@/lib/api";
import { formatPrice } from "@/lib/utils";
import { toastError, toastSuccess } from "@/lib/toast";
import { notifyCartChanged } from "@/lib/cart-events";
import { addCartItems } from "@/services/cart";

type OptionChoice = {
  value: string;
  price: number;
  soldOut: boolean;
};

function isEnabled(option: ShopProductOption) {
  return Number(option.io_use ?? 1) === 1;
}

function stockQty(option?: ShopProductOption) {
  return Math.max(0, Number(option?.io_stock_qty ?? 0));
}

export function hasShopBaseOptions(product: ShopProduct) {
  return (product.options ?? []).some((option) => Number(option.io_type) === 0);
}

export function hasPurchasableShopBaseOption(product: ShopProduct) {
  return (product.options ?? []).some(
    (option) =>
      Number(option.io_type) === 0 &&
      isEnabled(option) &&
      stockQty(option) >= Math.max(1, Number(product.it_buy_min_qty || 1))
  );
}

export function ProductCardOptionPicker({ product }: { product: ShopProduct }) {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [selections, setSelections] = useState<string[]>([]);
  const [quantity, setQuantity] = useState(
    Math.max(1, Number(product.it_buy_min_qty || 1))
  );
  const [adding, setAdding] = useState(false);
  const minQuantity = Math.max(1, Number(product.it_buy_min_qty || 1));
  const configuredMax = Math.max(0, Number(product.it_buy_max_qty || 0));
  const baseOptions = useMemo(
    () =>
      (product.options ?? []).filter(
        (option) => Number(option.io_type) === 0 && isEnabled(option)
      ),
    [product.options]
  );
  const parsedOptions = useMemo(
    () =>
      baseOptions.map((option) => ({
        option,
        levels: String(option.io_id || "").split("\x1e"),
      })),
    [baseOptions]
  );
  const optionSubjects = useMemo(() => {
    const configured = (product.it_option_subject || "")
      .split(",")
      .map((subject) => subject.trim())
      .filter(Boolean);
    if (configured.length > 0) return configured;

    const levelCount = parsedOptions.reduce(
      (count, option) => Math.max(count, option.levels.length),
      0
    );
    return Array.from({ length: levelCount }, (_, index) => `선택 옵션 ${index + 1}`);
  }, [parsedOptions, product.it_option_subject]);
  const selectedIoId = selections.filter(Boolean).join("\x1e");
  const selectedOption = parsedOptions.find(
    ({ option, levels }) =>
      levels.length === optionSubjects.length &&
      option.io_id === selectedIoId &&
      stockQty(option) >= minQuantity
  )?.option;
  const selectedStock = stockQty(selectedOption);
  const quantityLimits = [configuredMax, selectedStock].filter((value) => value > 0);
  const quantityMax = quantityLimits.length > 0
    ? Math.max(minQuantity, Math.min(...quantityLimits))
    : 0;
  const safeQuantity = Math.max(
    minQuantity,
    quantityMax > 0 ? Math.min(quantityMax, Math.floor(quantity)) : Math.floor(quantity)
  );
  const totalPrice = selectedOption
    ? (product.it_price + selectedOption.io_price) * safeQuantity
    : product.it_price * safeQuantity;

  const getAvailableValues = (levelIndex: number): OptionChoice[] => {
    const filtered = parsedOptions.filter(({ levels }) => {
      for (let index = 0; index < levelIndex; index += 1) {
        if (levels[index] !== selections[index]) return false;
      }
      return levels.length > levelIndex;
    });
    const lastLevel = levelIndex === optionSubjects.length - 1;
    const values = new Map<string, OptionChoice>();

    for (const { option, levels } of filtered) {
      const value = levels[levelIndex];
      if (!value) continue;
      const choice = {
        value,
        price: lastLevel ? option.io_price : 0,
        soldOut: lastLevel && stockQty(option) < minQuantity,
      };
      const previous = values.get(value);
      values.set(
        value,
        previous
          ? {
              ...previous,
              price: previous.price || choice.price,
              soldOut: previous.soldOut || choice.soldOut,
            }
          : choice
      );
    }

    return [...values.values()];
  };

  const handleAddToCart = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedOption) {
      toastError("구매할 옵션을 선택해주세요.");
      return;
    }
    if (configuredMax > 0 && safeQuantity > configuredMax) {
      toastError(`최대 ${configuredMax}개까지 구매할 수 있습니다.`);
      return;
    }
    if (safeQuantity > stockQty(selectedOption)) {
      toastError(`선택한 옵션의 재고는 ${stockQty(selectedOption)}개입니다.`);
      return;
    }

    setAdding(true);
    try {
      await addCartItems(product.it_id, [
        { io_id: selectedOption.io_id, ct_qty: safeQuantity, io_type: 0 },
      ]);
      notifyCartChanged();
      toastSuccess("장바구니에 담았습니다.");
      setOpen(false);
      setSelections([]);
      setQuantity(minQuantity);
    } catch (error) {
      toastError(error instanceof Error ? error.message : "장바구니에 담지 못했습니다.");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        type="button"
        className="btn btn-outline btn-primary btn-sm min-h-10 w-full whitespace-nowrap"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${product.it_name} 옵션 선택 후 장바구니 담기`}
        onClick={() => setOpen((current) => !current)}
      >
        <ShoppingCart aria-hidden="true" className="size-4" />
        옵션 선택
        <ChevronDown aria-hidden="true" className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <form
          id={panelId}
          className="mt-2 space-y-2 rounded-box border border-base-300 bg-base-100 p-2 sm:p-3"
          aria-label={`${product.it_name} 옵션 선택`}
          onSubmit={(event) => void handleAddToCart(event)}
        >
          {optionSubjects.map((subject, levelIndex) => (
            <div key={`${product.it_id}:${levelIndex}`}>
              <label className="mb-1 block text-xs font-semibold" htmlFor={`${panelId}-${levelIndex}`}>
                {subject}
              </label>
              <select
                id={`${panelId}-${levelIndex}`}
                className="select select-bordered select-xs sm:select-sm w-full ps-2 pe-6 text-[11px] sm:ps-3 sm:pe-8 sm:text-xs"
                value={selections[levelIndex] || ""}
                disabled={levelIndex > 0 && !selections[levelIndex - 1]}
                onChange={(event) => {
                  setSelections((current) => {
                    const next = [...current];
                    next[levelIndex] = event.target.value;
                    for (let index = levelIndex + 1; index < optionSubjects.length; index += 1) {
                      next[index] = "";
                    }
                    return next;
                  });
                  setQuantity(minQuantity);
                }}
              >
                <option value="">선택해주세요</option>
                {getAvailableValues(levelIndex).map((choice) => (
                  <option
                    key={choice.value}
                    value={choice.value}
                    disabled={choice.soldOut}
                  >
                    {choice.value}
                    {choice.price > 0
                      ? ` (+${formatPrice(choice.price)})`
                      : choice.price < 0
                        ? ` (${formatPrice(choice.price)})`
                        : ""}
                    {choice.soldOut ? " [품절]" : ""}
                  </option>
                ))}
              </select>
            </div>
          ))}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="whitespace-nowrap text-xs font-semibold" htmlFor={`${panelId}-quantity`}>
              수량
            </label>
            <input
              id={`${panelId}-quantity`}
              className="input input-bordered input-sm w-20 text-center"
              type="number"
              min={minQuantity}
              max={quantityMax > 0 ? quantityMax : undefined}
              value={safeQuantity}
              onChange={(event) => {
                const next = Math.floor(Number(event.target.value));
                setQuantity(Number.isFinite(next) ? Math.max(minQuantity, next) : minQuantity);
              }}
            />
          </div>

          <p className="text-right text-xs text-base-content/70">
            합계 <strong className="text-sm text-base-content">{formatPrice(totalPrice)}</strong>
          </p>
          <div className="flex flex-col gap-2">
            <button
              type="submit"
              className="btn btn-primary btn-sm w-full whitespace-nowrap"
              disabled={!selectedOption || adding}
            >
              {adding ? "담는 중…" : "장바구니 담기"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm w-full"
              disabled={adding}
              onClick={() => setOpen(false)}
            >
              닫기
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
