import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ bo_table: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ bo_table: string }>;
}

export default async function Page({ params }: PageProps) {
  const { bo_table } = await params;

  return <ClientPage boTable={bo_table} />;
}
