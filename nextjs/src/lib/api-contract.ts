// Types of the v1 API taken from the generated OpenAPI types (src/types/api.gen.ts).
// Only operations with a declared response contract (gnu_jango/api/contracts/) resolve to a real
// type; the others resolve to `never`, which makes accidental use visible.
import type { components, paths } from "@/types/api.gen";

type JsonBody<Operation> = Operation extends {
  responses: { 200: { content: { "application/json": infer Body } } };
}
  ? Body
  : never;

type GetBody<Path extends keyof paths> = JsonBody<paths[Path]["get"]>;

/** `data` of the `api_response` envelope a GET operation returns. */
export type ApiData<Path extends keyof paths> = GetBody<Path> extends { data: infer Data } ? Data : never;

/** `meta` of the `api_response` envelope a GET operation returns. */
export type ApiMeta<Path extends keyof paths> = GetBody<Path> extends { meta: infer Meta } ? Meta : never;

export type ApiSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type SiteSettings = ApiData<"/api/v1/settings">;
