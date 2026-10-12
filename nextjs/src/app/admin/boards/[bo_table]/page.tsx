import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ bo_table: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ bo_table: string }>;
}

export default function Page(_props: PageProps) {
  return <ClientPage />;
}
