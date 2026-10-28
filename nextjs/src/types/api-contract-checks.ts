// Compile-time checks that the hand-written frontend types still match the API contract.
// `npm run typecheck` fails here when a typed v1 response (src/types/api.gen.ts) drops, renames or
// retypes a field a frontend type relies on. Fix the frontend type or the API, then regenerate.
import type { ApiData, ApiMeta } from "@/lib/api-contract";
import type { ShopCategory, ShopProduct } from "@/lib/api";
import type { Board, PaginationMeta, Post } from "@/lib/types";
import type { PublicSettings, publicSettingsSchema } from "@/lib/schemas";

type Expect<T extends true> = T;
type IsNever<T> = [T] extends [never] ? true : false;
type Assignable<From, To> = [From] extends [To] ? true : false;

// GET /api/v1/settings -> services/settings.ts (validated with publicSettingsSchema)
type SettingsKeysNotSent = Exclude<keyof (typeof publicSettingsSchema)["shape"], keyof ApiData<"/api/v1/settings">>;
export type SettingsKeysAreSent = Expect<IsNever<SettingsKeysNotSent>>;
export type SettingsResponseFitsFrontend = Expect<Assignable<ApiData<"/api/v1/settings">, PublicSettings>>;

// Hand-written response types (lib/types.ts, lib/api.ts): every field they require must be sent
// with a compatible type.
type BoardRow = ApiData<"/api/v1/boards">[number];
type PostRow = ApiData<"/api/v1/boards/{bo_table}/posts">[number];
type CategoryRow = ApiData<"/api/v1/shop/categories">[number];
type ProductRow = ApiData<"/api/v1/shop/products">[number];
export type BoardRowFitsBoard = Expect<Assignable<BoardRow, Board>>;
export type PostRowFitsPost = Expect<Assignable<PostRow, Post>>;
export type PostDetailFitsPost = Expect<Assignable<ApiData<"/api/v1/posts/{bo_table}/{wr_id}">, Post>>;
export type CategoryRowFitsShopCategory = Expect<Assignable<CategoryRow, ShopCategory>>;
export type ProductRowFitsShopProduct = Expect<Assignable<ProductRow, ShopProduct>>;
export type ProductDetailFitsShopProduct = Expect<Assignable<ApiData<"/api/v1/shop/products/{it_id}">, ShopProduct>>;
export type ProductMetaFitsPagination = Expect<Assignable<ApiMeta<"/api/v1/shop/products">, PaginationMeta>>;
export type PostMetaFitsPagination = Expect<Assignable<ApiMeta<"/api/v1/boards/{bo_table}/posts">, PaginationMeta>>;
