export default function ShopLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="naver-shell min-h-screen">
      <main className="site-container px-4 pb-8 pt-4">{children}</main>
    </div>
  );
}
