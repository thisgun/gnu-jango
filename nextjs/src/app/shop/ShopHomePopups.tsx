"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { ShopPopup } from "@/lib/api";
import { getShopHomeData } from "@/services/shop-home";

const PopupContent = dynamic(() => import("./ShopPopupContent"), { ssr: false });

export function ShopHomePopups({ popups: initialPopups }: { popups: ShopPopup[] }) {
  const [popups, setPopups] = useState(initialPopups);
  useEffect(() => {
    let active = true;
    getShopHomeData().then(home => { if (active) setPopups(home.popups); }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  return popups.length ? <PopupContent popups={popups} /> : null;
}
