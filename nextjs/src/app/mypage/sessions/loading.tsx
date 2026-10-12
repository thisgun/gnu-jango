export default function LoginSessionsLoading() {
  return (
    <div className="space-y-4">
      <div className="h-8 w-36 animate-pulse rounded bg-muted" />
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="h-24 animate-pulse rounded-md border bg-muted/40" />
      ))}
    </div>
  );
}
