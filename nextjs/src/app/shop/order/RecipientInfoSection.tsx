"use client";

import {
  type AddressForm,
  type AddressSelection,
  type SavedAddress,
} from "./orderAddressHelpers";
import type { AddressFieldUpdater, PostcodeTarget } from "./OrderAddressFields";
import { RecipientAddressDetails } from "./RecipientAddressDetails";
import { RecipientAddressSelector } from "./RecipientAddressSelector";
import { RecipientDeliveryOptions } from "./RecipientDeliveryOptions";

type RecipientInfoSectionProps = {
  inputClassName: string;
  addressSelection: AddressSelection;
  handleAddressSelection: (selection: AddressSelection) => void;
  savedAddresses: SavedAddress[];
  openAddressModal: () => void;
  recipient: AddressForm;
  updateRecipient: AddressFieldUpdater;
  openPostcode: (target: PostcodeTarget) => void;
  isMemberOrder: boolean;
  paymentMethod: string;
  cashReceiptEnabled: boolean;
  canRequestCashReceipt: boolean;
  saveAsNewAddress: boolean;
  setSaveAsNewAddress: (checked: boolean) => void;
  newAddressSubject: string;
  setNewAddressSubject: (value: string) => void;
  newAddressDefault: boolean;
  setNewAddressDefault: (checked: boolean) => void;
  memo: string;
  setMemo: (value: string) => void;
  hopeDate: string;
  setHopeDate: (value: string) => void;
  taxRequest: boolean;
  setTaxRequest: (checked: boolean) => void;
  taxCompany: string;
  setTaxCompany: (value: string) => void;
  taxBusinessNo: string;
  setTaxBusinessNo: (value: string) => void;
  taxInvoiceEmail: string;
  setTaxInvoiceEmail: (value: string) => void;
  cashRequest: boolean;
  setCashRequest: (checked: boolean) => void;
  cashReceiptType: "income" | "expense";
  setCashReceiptType: (value: "income" | "expense") => void;
  cashReceiptIdentityNumber: string;
  setCashReceiptIdentityNumber: (value: string) => void;
};

export function RecipientInfoSection({
  inputClassName,
  addressSelection,
  handleAddressSelection,
  savedAddresses,
  openAddressModal,
  recipient,
  updateRecipient,
  openPostcode,
  isMemberOrder,
  paymentMethod,
  cashReceiptEnabled,
  canRequestCashReceipt,
  saveAsNewAddress,
  setSaveAsNewAddress,
  newAddressSubject,
  setNewAddressSubject,
  newAddressDefault,
  setNewAddressDefault,
  memo,
  setMemo,
  hopeDate,
  setHopeDate,
  taxRequest,
  setTaxRequest,
  taxCompany,
  setTaxCompany,
  taxBusinessNo,
  setTaxBusinessNo,
  taxInvoiceEmail,
  setTaxInvoiceEmail,
  cashRequest,
  setCashRequest,
  cashReceiptType,
  setCashReceiptType,
  cashReceiptIdentityNumber,
  setCashReceiptIdentityNumber,
}: RecipientInfoSectionProps) {
  return (
    <section className="shop-order-section shop-order-section--recipient box-border w-full min-w-0 rounded-lg border p-4 sm:p-6">
      <RecipientAddressSelector
        addressSelection={addressSelection}
        handleAddressSelection={handleAddressSelection}
        savedAddresses={savedAddresses}
        openAddressModal={openAddressModal}
      />
      <RecipientAddressDetails
        inputClassName={inputClassName}
        addressSelection={addressSelection}
        recipient={recipient}
        updateRecipient={updateRecipient}
        openPostcode={openPostcode}
        isMemberOrder={isMemberOrder}
        saveAsNewAddress={saveAsNewAddress}
        setSaveAsNewAddress={setSaveAsNewAddress}
        newAddressSubject={newAddressSubject}
        setNewAddressSubject={setNewAddressSubject}
        newAddressDefault={newAddressDefault}
        setNewAddressDefault={setNewAddressDefault}
      />
      <RecipientDeliveryOptions
        inputClassName={inputClassName}
        memo={memo}
        setMemo={setMemo}
        hopeDate={hopeDate}
        setHopeDate={setHopeDate}
        isMemberOrder={isMemberOrder}
        paymentMethod={paymentMethod}
        cashReceiptEnabled={cashReceiptEnabled}
        canRequestCashReceipt={canRequestCashReceipt}
        taxRequest={taxRequest}
        setTaxRequest={setTaxRequest}
        taxCompany={taxCompany}
        setTaxCompany={setTaxCompany}
        taxBusinessNo={taxBusinessNo}
        setTaxBusinessNo={setTaxBusinessNo}
        taxInvoiceEmail={taxInvoiceEmail}
        setTaxInvoiceEmail={setTaxInvoiceEmail}
        cashRequest={cashRequest}
        setCashRequest={setCashRequest}
        cashReceiptType={cashReceiptType}
        setCashReceiptType={setCashReceiptType}
        cashReceiptIdentityNumber={cashReceiptIdentityNumber}
        setCashReceiptIdentityNumber={setCashReceiptIdentityNumber}
      />
    </section>
  );
}
