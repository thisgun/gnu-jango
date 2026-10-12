import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ mb_id: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ mb_id: string }>;
}

export default function Page(_props: PageProps) {
  return <ClientPage />;
}
