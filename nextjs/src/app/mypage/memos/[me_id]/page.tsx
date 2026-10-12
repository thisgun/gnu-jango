import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ me_id: "0" }];
}

interface PageProps {
  params: Promise<{ me_id: string }>;
}

export default function Page(_props: PageProps) {
  return <ClientPage />;
}
