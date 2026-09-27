"use client";

import { useState } from "react";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi, useMutation } from "@/hooks/useApi";
import { leadsApi } from "@/lib/leadsApi";
import { formatDateTime } from "@/lib/utils";

// Free-text, human-only (never AI-generated) — CLAUDE.md.
export default function LeadNotesPage({ params }: { params: { id: string } }) {
  const { data, loading, error, refetch } = useApi(() => leadsApi.notes(params.id), [params.id], {
    fallbackError: "Failed to load notes",
  });
  const create = useMutation(leadsApi.createNote, "Could not save the note");
  const [draft, setDraft] = useState("");

  const notes = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));

  const addNote = async () => {
    const body = draft.trim();
    if (!body) return;
    if (await create.mutate({ leadId: params.id, body })) {
      setDraft("");
      refetch();
    }
  };

  return (
    <Panel title="Notes">
      <div className="mb-4 flex flex-col gap-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a note…"
          rows={3}
          className="w-full rounded-lg border border-gray-300 p-3 text-sm outline-none focus:border-gray-500"
        />
        {create.error && <p className="text-sm text-red-600">{create.error}</p>}
        <button
          onClick={addNote}
          disabled={create.pending || draft.trim() === ""}
          className="self-end rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {create.pending ? "Saving…" : "Add Note"}
        </button>
      </div>

      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={notes.length === 0}
        loadingMessage="Loading notes…"
        emptyMessage="No notes yet."
      >
        <div className="divide-y divide-gray-100">
          {notes.map((note) => (
            <div key={note.id} className="py-2.5">
              <p className="text-sm text-gray-700">{note.body}</p>
              <p className="mt-0.5 text-xs text-gray-400">{formatDateTime(note.created_at)}</p>
            </div>
          ))}
        </div>
      </AsyncBoundary>
    </Panel>
  );
}
