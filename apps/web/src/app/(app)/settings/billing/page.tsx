"use client";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { billingApi } from "@/lib/billingApi";
import { humanize } from "@/lib/utils";

export default function BillingPage() {
  // Every billing endpoint is require_role(ADMIN); nav.ts keeps other roles off
  // this route entirely.
  const subscription = useApi(() => billingApi.subscription(), [], {
    fallbackError: "Failed to load the subscription",
  });
  const usage = useApi(() => billingApi.usage(), [], { fallbackError: "Failed to load usage" });

  const sub = subscription.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Billing</h1>
        <p className="mt-1 text-sm text-gray-500">Plan and usage.</p>
      </div>

      <Panel title="Subscription">
        <AsyncBoundary
          loading={subscription.loading}
          error={subscription.error}
          // The endpoint returns null (not an error) when the tenant has no
          // subscription row yet.
          isEmpty={!sub}
          loadingMessage="Loading your plan…"
          emptyMessage="No active subscription."
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-lg font-semibold text-gray-900">{sub?.plan_name}</p>
              <p className="text-sm text-gray-500">
                {sub?.user_limit} users · {sub?.ai_credit_limit.toLocaleString()} AI credits
              </p>
            </div>
            <span
              className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                sub?.status === "active" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
              }`}
            >
              {humanize(sub?.status ?? "")}
            </span>
          </div>
        </AsyncBoundary>
      </Panel>

      <Panel title="Usage This Period">
        <AsyncBoundary loading={usage.loading} error={usage.error} loadingMessage="Loading usage…">
          <div className="space-y-4">
            {/* GET /billing/usage currently returns only a record count — the
                per-metric breakdown (users, AI credits) needs a server-side
                aggregation over usage_records before it can be charted. */}
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Usage records this period</span>
              <span className="font-medium text-gray-900">{usage.data?.records ?? 0}</span>
            </div>
            {sub && (
              <p className="text-xs text-gray-400">
                Plan allows {sub.user_limit} users and {sub.ai_credit_limit.toLocaleString()} AI credits. Per-metric
                consumption isn&apos;t aggregated server-side yet.
              </p>
            )}
          </div>
        </AsyncBoundary>
      </Panel>
    </div>
  );
}
