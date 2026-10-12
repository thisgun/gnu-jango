import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ od_id: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ od_id: string }>;
}

export default function Page(_props: PageProps) {
  return <ClientPage />;
}
