"use client";

import { useEffect, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { ApiError } from "@/lib/api";
import {
  fetchPluginSlot,
  pluginActionApiPath,
  runPluginAction,
  type PluginWidget,
  type PluginWidgetAction,
} from "@/services/plugin-slots";
import { useAuthStore } from "@/store/auth";

/**
 * The widgets plugins put in a theme slot (e.g. "home.sidebar"), drawn as sidebar boxes.
 * Adding a plugin needs no theme rebuild: the widgets come from the API as data.
 */
export function PluginSlot({ name }: { name: string }) {
  const isInitialized = useAuthStore((state) => state.isInitialized);
  const memberId = useAuthStore((state) => state.user?.mb_id ?? "");
  const [widgets, setWidgets] = useState<PluginWidget[]>([]);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!isInitialized) return;
    let active = true;
    fetchPluginSlot(name)
      .then((found) => {
        if (active) setWidgets(found);
      })
      .catch(() => {
        if (active) setWidgets([]);
      });
    return () => {
      active = false;
    };
  }, [isInitialized, memberId, name, version]);

  if (!widgets.length) return null;
  return (
    <>
      {widgets.map((widget, index) => (
        <PluginWidgetBox key={`${widget.plugin}-${index}`} widget={widget} onDone={() => setVersion((value) => value + 1)} />
      ))}
    </>
  );
}

function PluginWidgetBox({ widget, onDone }: { widget: PluginWidget; onDone: () => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const titleId = `plugin-${widget.plugin}-title`;

  async function run(action: PluginWidgetAction) {
    setPending(true);
    setError("");
    try {
      await runPluginAction(action);
      onDone();
    } catch (cause) {
      setError(cause instanceof ApiError || cause instanceof Error ? cause.message : "요청을 처리하지 못했습니다.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-plugin-widget"
      aria-labelledby={titleId}
    >
      <header className="solune-sidebar-widget-head">
        <h2 id={titleId}>{widget.title}</h2>
      </header>
      <div className="solune-sidebar-widget-body">
        {widget.body ? <p className="solune-plugin-body">{widget.body}</p> : null}
        {widget.stats.length ? (
          <dl className="solune-plugin-stats">
            {widget.stats.map((stat) => (
              <div key={stat.label}>
                <dt>{stat.label}</dt>
                <dd>{stat.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {widget.actions.length ? (
          <div className="solune-plugin-actions">
            {widget.actions.map((action) => {
              const className = `btn btn-sm btn-block ${action.primary ? "btn-primary" : "btn-outline"}`;
              if (action.method === "GET") {
                return (
                  <Link key={action.label} href={action.url} className={className}>
                    {action.label}
                  </Link>
                );
              }
              if (!pluginActionApiPath(action)) return null;
              return (
                <button key={action.label} type="button" className={className} disabled={pending} onClick={() => void run(action)}>
                  {pending ? "처리 중…" : action.label}
                </button>
              );
            })}
          </div>
        ) : null}
        {error ? (
          <p className="solune-poll-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
