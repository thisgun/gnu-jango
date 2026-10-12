"use client";

import { useId } from "react";
import { Button } from "@/components/ui/button";
import {
  KOREAN_PHONE_PATTERN,
  KOREAN_ZIP_PATTERN,
  normalizeKoreanZipInput,
} from "@/lib/address-validation";
import { type AddressForm } from "./orderAddressHelpers";

export type AddressFieldUpdater = (
  field: keyof AddressForm,
  value: string
) => void;
export type PostcodeTarget = "orderer" | "recipient";

type AddressFieldsProps = {
  inputClassName: string;
  address: AddressForm;
  updateAddress: AddressFieldUpdater;
  postcodeTarget: PostcodeTarget;
  openPostcode: (target: PostcodeTarget) => void;
};

export function AddressFields({
  inputClassName,
  address,
  updateAddress,
  postcodeTarget,
  openPostcode,
}: AddressFieldsProps) {
  // One instance renders for the orderer and one for the recipient, so ids must be unique per instance.
  const uid = useId();
  const id = (field: string) => `${uid}-${field}`;

  return (
    <>
      <div className="sm:col-span-2">
        <label htmlFor={id("name")} className="mb-1 block text-sm font-medium">
          이름 <span className="text-red-700">*</span>
        </label>
        <input
          id={id("name")}
          type="text"
          value={address.name}
          onChange={(event) => updateAddress("name", event.target.value)}
          required
          className={inputClassName}
        />
      </div>
      <div>
        <label htmlFor={id("tel")} className="mb-1 block text-sm font-medium">전화번호</label>
        <input
          id={id("tel")}
          type="tel"
          value={address.tel}
          onChange={(event) => updateAddress("tel", event.target.value)}
          placeholder="02-000-0000"
          pattern={KOREAN_PHONE_PATTERN}
          title="전화번호를 올바르게 입력해 주세요."
          className={inputClassName}
        />
      </div>
      <div>
        <label htmlFor={id("hp")} className="mb-1 block text-sm font-medium">
          휴대폰번호 <span className="text-red-700">*</span>
        </label>
        <input
          id={id("hp")}
          type="tel"
          value={address.hp}
          onChange={(event) => updateAddress("hp", event.target.value)}
          placeholder="010-0000-0000"
          pattern={KOREAN_PHONE_PATTERN}
          title="휴대폰 번호를 올바르게 입력해 주세요."
          required
          className={inputClassName}
        />
      </div>
      <div className="sm:col-span-2">
        <label htmlFor={id("zip")} className="mb-1 block text-sm font-medium">
          우편번호 <span className="text-red-700">*</span>
        </label>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
          <input
            id={id("zip")}
            type="text"
            value={address.zip}
            onChange={(event) =>
              updateAddress("zip", normalizeKoreanZipInput(event.target.value))
            }
            placeholder="우편번호"
            inputMode="numeric"
            maxLength={5}
            pattern={KOREAN_ZIP_PATTERN}
            title="우편번호 5자리를 입력해 주세요."
            required
            className={`${inputClassName} w-full sm:max-w-[140px]`}
          />
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
            onClick={() => openPostcode(postcodeTarget)}
          >
            우편번호 검색
          </Button>
        </div>
      </div>
      <div className="sm:col-span-2">
        <label htmlFor={id("addr1")} className="mb-1 block text-sm font-medium">
          기본주소 <span className="text-red-700">*</span>
        </label>
        <input
          id={id("addr1")}
          type="text"
          value={address.addr1}
          onChange={(event) => updateAddress("addr1", event.target.value)}
          required
          className={inputClassName}
        />
      </div>
      <div>
        <label htmlFor={id("addr2")} className="mb-1 block text-sm font-medium">상세주소</label>
        <input
          id={id("addr2")}
          type="text"
          value={address.addr2}
          onChange={(event) => updateAddress("addr2", event.target.value)}
          placeholder="상세주소"
          className={inputClassName}
        />
      </div>
      <div>
        <label htmlFor={id("addr3")} className="mb-1 block text-sm font-medium">참고항목</label>
        <input
          id={id("addr3")}
          type="text"
          value={address.addr3}
          onChange={(event) => updateAddress("addr3", event.target.value)}
          placeholder="(건물명)"
          className={inputClassName}
        />
      </div>
    </>
  );
}
