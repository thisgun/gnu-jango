"use client";

import { ArrowRight, ChevronDown } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { sanitizeCommerceHtml, sanitizeInlineHtml } from "@/lib/sanitize";
import type { FaqItem } from "@/lib/types";

function plainFaqSubject(value: string): string {
  const sanitized = sanitizeInlineHtml(value);
  return sanitized.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

export default function FaqPanel({ faqs }: { faqs: FaqItem[] }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-reference-panel solune-faq-panel" aria-labelledby="home-faq-heading">
      <div className="solune-panel-head">
        <h2 id="home-faq-heading" className="solune-panel-title">자주 묻는 질문</h2>
        <Link href="/faq" className="solune-panel-more">더보기 <ArrowRight size={13} aria-hidden="true" /></Link>
      </div>
      {faqs.length > 0 ? (
        <div className="solune-faq-list">
          {faqs.map((faq, index) => (
            <details key={faq.fa_id} name="home-faq" className="solune-faq-item" open={index === 0}>
              <summary className="solune-faq-q">
                <span className="badge badge-primary badge-soft badge-sm solune-faq-badge" aria-hidden="true">Q</span>
                <span className="solune-faq-subject" dangerouslySetInnerHTML={{ __html: plainFaqSubject(faq.fa_subject) }} />
                <ChevronDown size={15} className="solune-faq-chevron" aria-hidden="true" />
              </summary>
              <div className="solune-faq-a" dangerouslySetInnerHTML={{ __html: sanitizeCommerceHtml(faq.fa_content) }} />
            </details>
          ))}
        </div>
      ) : (
        <div className="solune-panel-body"><p className="solune-empty">등록된 FAQ가 없습니다.</p></div>
      )}
    </section>
  );
}

