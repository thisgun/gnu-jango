import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ pp_id: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ pp_id: string }>;
}

export default function Page(_props: PageProps) {
  return <ClientPage />;
}
