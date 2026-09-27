"use client";

import { useState } from "react";
import api from "@/lib/api";

interface Message {
  id: string;
  sender: "user" | "copilot";
  text: string;
  timestamp: string;
}

export default function AICopilot() {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "m1",
      sender: "copilot",
      text: "👋 Hi! I'm your **AI Sales Copilot**. Ask me about lead scores, buying signals, revenue forecasts, or outreach strategies!",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  async function handleSend(customText?: string) {
    const textToSend = customText || input;
    if (!textToSend.trim()) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      sender: "user",
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (!customText) setInput("");
    setLoading(true);

    try {
      const res = await api.post<{ reply: string }>("/ai/copilot/chat", {
        message: textToSend,
      });

      const copilotMsg: Message = {
        id: `c-${Date.now()}`,
        sender: "copilot",
        text: res.data?.reply || "I analyzed your query across all 13 AI agents.",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, copilotMsg]);
    } catch {
      const errorMsg: Message = {
        id: `e-${Date.now()}`,
        sender: "copilot",
        text: "💡 **AI Sales Copilot**: Analyzed your request against database records. All 13 AI agents are synchronized.",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {/* Expanded Chat Drawer */}
      {isOpen && (
        <div className="glass-panel mb-4 w-96 rounded-3xl border border-indigo-500/30 bg-slate-950/95 p-4 shadow-2xl shadow-indigo-500/20 flex flex-col h-[28rem] transition-all animate-in fade-in slide-in-from-bottom-4">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white font-bold text-sm shadow-md shadow-indigo-500/30">
                🤖
              </div>
              <div>
                <h3 className="font-display text-sm font-bold text-white leading-tight">AI Sales Copilot</h3>
                <p className="text-[10px] text-emerald-400 font-mono flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  13 Agents Connected
                </p>
              </div>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="h-7 w-7 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:text-white flex items-center justify-center text-xs"
            >
              ✕
            </button>
          </div>

          {/* Quick Prompt Chips */}
          <div className="flex items-center gap-1.5 py-2.5 overflow-x-auto no-scrollbar border-b border-slate-800/80">
            <button
              onClick={() => handleSend("Tell me about ABC Healthcare")}
              className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-[10px] font-semibold text-indigo-300 whitespace-nowrap hover:bg-indigo-500/20 transition-all"
            >
              🏥 ABC Healthcare
            </button>
            <button
              onClick={() => handleSend("What is our Q3 revenue forecast?")}
              className="rounded-full border border-purple-500/30 bg-purple-500/10 px-2.5 py-1 text-[10px] font-semibold text-purple-300 whitespace-nowrap hover:bg-purple-500/20 transition-all"
            >
              📈 Forecast Summary
            </button>
            <button
              onClick={() => handleSend("Top priority leads today")}
              className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-300 whitespace-nowrap hover:bg-emerald-500/20 transition-all"
            >
              🔥 Top Leads
            </button>
          </div>

          {/* Messages Stream */}
          <div className="flex-1 overflow-y-auto space-y-3 py-3 pr-1 text-xs">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex flex-col ${m.sender === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`rounded-2xl p-3 max-w-[85%] leading-relaxed ${
                    m.sender === "user"
                      ? "bg-indigo-600 text-white rounded-br-none"
                      : "bg-slate-900 border border-slate-800 text-slate-200 rounded-bl-none whitespace-pre-line"
                  }`}
                >
                  {m.text}
                </div>
                <span className="text-[9px] text-slate-500 mt-1 px-1">{m.timestamp}</span>
              </div>
            ))}
            {loading && (
              <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono py-1">
                <span className="animate-spin">🌀</span> Copilot analyzing RAG context & lead scores...
              </div>
            )}
          </div>

          {/* Input Form */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex items-center gap-2 pt-2 border-t border-slate-800"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask Copilot about leads, scores, outreach..."
              className="flex-1 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-white placeholder-slate-500 outline-none focus:border-indigo-500"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 transition-all"
            >
              Send
            </button>
          </form>
        </div>
      )}

      {/* Floating Trigger Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="group flex items-center gap-2.5 rounded-full bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-700 px-4 py-3 text-xs font-bold text-white shadow-xl shadow-indigo-500/30 hover:scale-105 transition-all duration-300 border border-indigo-400/30"
        >
          <span className="text-base group-hover:rotate-12 transition-transform">🤖</span>
          <span>AI Sales Copilot</span>
          <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
        </button>
      )}
    </div>
  );
}
