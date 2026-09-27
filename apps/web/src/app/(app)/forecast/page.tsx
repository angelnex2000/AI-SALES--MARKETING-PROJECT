"use client";

import { Panel, StatCard } from "@/components/ui";
import { money } from "@/lib/utils";

const FORECAST_CURRENCIES = [
  { currency: "USD", open_pipeline: 1250000, weighted_forecast: 485000, closed_won: 320000, confidence: 0.84 },
  { currency: "EUR", open_pipeline: 620000, weighted_forecast: 240000, closed_won: 180000, confidence: 0.81 },
  { currency: "INR", open_pipeline: 45000000, weighted_forecast: 17500000, closed_won: 12000000, confidence: 0.79 },
];

const TOP_DEALS = [
  { id: "deal-101", title: "MedCare Enterprise Automation", account: "MedCare Hospital", amount: "$350,000", stage: "Proposal", prob: "75%", forecast: "$262,500" },
  { id: "deal-102", title: "Northwind Supply Chain AI", account: "Northwind Logistics", amount: "€180,000", stage: "Qualified", prob: "50%", forecast: "€90,000" },
  { id: "deal-103", title: "Brightpath Learning Platform", account: "Brightpath Learning", amount: "₹4,500,000", stage: "Negotiation", prob: "85%", forecast: "₹3,825,000" },
  { id: "deal-104", title: "Cobalt Payments AI Layer", account: "Cobalt Fintech", amount: "$210,000", stage: "Discovery", prob: "30%", forecast: "$63,000" },
];

export default function ForecastPage() {
  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
          <span>SALES MANAGEMENT</span> <span>/</span> <span>REVENUE FORECASTING</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
          AI Revenue Forecasting Engine
        </h1>
        <p className="text-sm text-slate-400 mt-1 max-w-2xl">
          Weighted pipeline forecasting powered by Module 12. Evaluates deal stage probabilities, backtested MAPE (16.1%), and multi-currency pipeline breakdowns without compounding FX errors.
        </p>
      </div>

      {/* Accuracy & Model Stats Bar */}
      <div className="glass-panel p-4 rounded-2xl flex flex-wrap items-center justify-between gap-4 border border-indigo-500/20 bg-indigo-500/5 text-xs text-slate-300">
        <div className="flex items-center gap-3">
          <span className="text-xl">📈</span>
          <div>
            <span className="font-semibold text-white">Model Architecture: </span>
            <span className="text-indigo-300 font-mono">Weighted Pipeline (rescaled prior_shape_measured_level)</span>
          </div>
        </div>

        <div className="flex items-center gap-6 font-mono">
          <div>
            <span className="text-slate-400">Holdout MAPE: </span>
            <span className="text-emerald-400 font-bold">0.161 (16.1%)</span>
          </div>
          <div>
            <span className="text-slate-400">Holdout R²: </span>
            <span className="text-emerald-400 font-bold">0.35</span>
          </div>
          <div>
            <span className="text-slate-400">Backtested Deals: </span>
            <span className="text-indigo-300">23,446</span>
          </div>
        </div>
      </div>

      {/* Currency Forecast Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {FORECAST_CURRENCIES.map((c) => (
          <div key={c.currency} className="glass-panel glass-panel-hover p-5 rounded-2xl border border-slate-800 space-y-4">
            <div className="flex items-center justify-between">
              <span className="font-mono font-bold text-lg text-white">{c.currency} Pipeline</span>
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                {(c.confidence * 100).toFixed(0)}% Confidence
              </span>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-slate-800/60 text-slate-400">
                <span>Open Pipeline Amount</span>
                <span className="font-mono font-semibold text-slate-200">{c.currency} {c.open_pipeline.toLocaleString()}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/60 text-slate-400">
                <span>AI Weighted Forecast</span>
                <span className="font-mono font-bold text-indigo-400 text-sm">{c.currency} {c.weighted_forecast.toLocaleString()}</span>
              </div>
              <div className="flex justify-between py-1 text-slate-400">
                <span>Closed Won Realized</span>
                <span className="font-mono font-semibold text-emerald-400">{c.currency} {c.closed_won.toLocaleString()}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Top Opportunity Deal Predictions Table */}
      <Panel title="Top Deal Close Probabilities" subtitle="Highest-impact pipeline opportunities evaluated by Module 12">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="border-b border-slate-800 bg-slate-900/80 text-slate-400 uppercase font-mono">
              <tr>
                <th className="py-3 px-4">Opportunity</th>
                <th className="py-3 px-4">Account / Lead</th>
                <th className="py-3 px-4">Total Amount</th>
                <th className="py-3 px-4">Stage</th>
                <th className="py-3 px-4">Win Probability</th>
                <th className="py-3 px-4 text-right">Weighted Forecast</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-sans">
              {TOP_DEALS.map((deal) => (
                <tr key={deal.id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-4 font-semibold text-white">{deal.title}</td>
                  <td className="py-3 px-4 text-slate-300">{deal.account}</td>
                  <td className="py-3 px-4 font-mono text-slate-200">{deal.amount}</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700 text-[11px]">
                      {deal.stage}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono font-semibold text-emerald-400">{deal.prob}</td>
                  <td className="py-3 px-4 text-right font-mono font-bold text-indigo-400">{deal.forecast}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
