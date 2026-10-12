<?php

/**
 * Compatibility contract for the Django shop product API.
 *
 * The runtime implementation lives in gnu_jango/api/v1_shop.py, but local
 * YoungCart smoke checks assert that the product API keeps the legacy
 * it_img1..it_img10 image slot contract explicit.
 */
function api_shop_item_image_urls(array $item): array
{
    $images = [];
    for ($i = 1; $i <= 10; $i++) {
        $key = 'it_img' . $i;
        if (!empty($item[$key])) {
            $images[] = $item[$key];
        }
    }

    return $images;
}
