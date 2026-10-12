import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ qa_id: "0" }];
}

interface PageProps {
  params: Promise<{ qa_id: string }>;
}

export default async function Page({ params }: PageProps) {
  const { qa_id } = await params;

  return <ClientPage qaId={qa_id} />;
}
