import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ mb_id: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ mb_id: string }>;
}

export default async function Page({ params }: PageProps) {
  const { mb_id } = await params;

  return <ClientPage mbId={mb_id} />;
}
