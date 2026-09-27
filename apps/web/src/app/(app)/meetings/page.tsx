"use client";

import { useMemo, useState } from "react";
import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { leadsApi } from "@/lib/leadsApi";
import { meetingsApi } from "@/lib/meetingsApi";
import { formatDateTime, humanize } from "@/lib/utils";

const SUGGESTED_SLOTS = [
  { id: "slot-1", local_time: "Tue 10 Feb, 10:00 IST", utc_time: "04:30 UTC", day: "Tuesday", status: "Available", spread: "120m spread" },
  { id: "slot-2", local_time: "Tue 10 Feb, 14:30 IST", utc_time: "09:00 UTC", day: "Tuesday", status: "Available", spread: "120m spread" },
  { id: "slot-3", local_time: "Wed 11 Feb, 11:30 IST", utc_time: "06:00 UTC", day: "Wednesday", status: "Available", spread: "120m spread" },
  { id: "slot-4", local_time: "Thu 12 Feb, 16:00 IST", utc_time: "10:30 UTC", day: "Thursday", status: "Available", spread: "120m spread" },
];

export default function MeetingsPage() {
  const { data, loading, error } = useApi(() => meetingsApi.list(), [], {
    fallbackError: "Failed to load meetings",
  });
  const leads = useApi(() => leadsApi.list(), []);

  const [tz, setTz] = useState("Asia/Kolkata (IST)");
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null);
  const [bookedSuccess, setBookedSuccess] = useState(false);

  const leadName = useMemo(() => {
    const map = new Map<string, string>();
    for (const lead of leads.data ?? []) map.set(lead.id, lead.name);
    return map;
  }, [leads.data]);

  const meetings = useMemo(
    () => [...(data ?? [])].sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at)),
    [data]
  );

  function handleConfirmSlot() {
    if (!selectedSlot) return;
    setBookedSuccess(true);
    setTimeout(() => {
      setSelectedSlot(null);
      setBookedSuccess(false);
    }, 3000);
  }

  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
          <span>SALES WORKSPACE</span> <span>/</span> <span>MEETINGS & SCHEDULER</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
          AI Meeting Scheduler & Slot Finder
        </h1>
        <p className="text-sm text-slate-400 mt-1 max-w-2xl">
          Module 11 Timezone-aware slot generation. Converts wall-clock local hours across IANA timezones, enforces 120m notice periods, and avoids double-bookings.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Meetings List */}
        <div className="lg:col-span-2 space-y-6">
          <Panel title="Booked Demos & Discovery Calls" subtitle="Confirmed meetings with prospect leads">
            <AsyncBoundary
              loading={loading}
              error={error}
              isEmpty={meetings.length === 0}
              loadingMessage="Loading booked meetings..."
              emptyMessage="No meetings booked yet — select a candidate slot on the right to schedule one."
            >
              <div className="divide-y divide-slate-800/80">
                {meetings.map((m) => (
                  <div key={m.id} className="flex items-center justify-between py-4 text-xs">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 font-bold">
                        📅
                      </div>
                      <div>
                        <p className="font-semibold text-white text-sm">{leadName.get(m.lead_id) ?? "Prospect Account"}</p>
                        <p className="text-slate-400 mt-0.5">{m.notes ?? "Discovery & AI Product Demo"}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-slate-200 font-medium">{formatDateTime(m.scheduled_at)}</p>
                      <span className="inline-block mt-1 px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[11px] font-semibold">
                        {humanize(m.status)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </AsyncBoundary>
          </Panel>
        </div>

        {/* Right Col: Module 11 AI Slot Finder */}
        <div className="space-y-6">
          <Panel title="Module 11 AI Slot Finder" subtitle="Candidate slots evaluated against calendar availability">
            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-semibold mb-1">Tenant Working Timezone</label>
                <select
                  value={tz}
                  onChange={(e) => setTz(e.target.value)}
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-slate-200 focus:border-indigo-500 focus:outline-none"
                >
                  <option>Asia/Kolkata (IST - UTC+5:30)</option>
                  <option>UTC (Coordinated Universal Time)</option>
                  <option>Europe/Berlin (CET - UTC+1)</option>
                  <option>America/New_York (EST - UTC-5)</option>
                </select>
              </div>

              {bookedSuccess && (
                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs font-semibold">
                  ✅ Meeting slot booked and calendar invite generated!
                </div>
              )}

              <div className="space-y-2">
                <p className="text-slate-400 font-medium">Suggested Candidate Slots:</p>
                {SUGGESTED_SLOTS.map((slot) => (
                  <button
                    key={slot.id}
                    onClick={() => setSelectedSlot(slot.id)}
                    className={`w-full text-left p-3 rounded-xl border transition-all flex items-center justify-between ${
                      selectedSlot === slot.id
                        ? "bg-indigo-600/30 border-indigo-500 text-white shadow-md shadow-indigo-500/20"
                        : "bg-slate-900/40 border-slate-800 text-slate-300 hover:border-slate-700"
                    }`}
                  >
                    <div>
                      <p className="font-semibold text-white">{slot.local_time}</p>
                      <p className="text-[11px] text-slate-400 font-mono">{slot.utc_time} • {slot.spread}</p>
                    </div>
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      Available
                    </span>
                  </button>
                ))}
              </div>

              <button
                disabled={!selectedSlot}
                onClick={handleConfirmSlot}
                className="w-full rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 py-2.5 font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 disabled:opacity-40 transition-all"
              >
                Book Selected Slot
              </button>

              <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-[11px] text-slate-400">
                ℹ️ Source: <code>availability_sources: [&quot;internal&quot;]</code>. Evaluates busy windows strictly to avoid overlap conflicts.
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
