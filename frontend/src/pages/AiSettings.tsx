import { useState } from "react";
import Help from "../components/Help";
import AssistantSettings from "./AssistantSettings";
import ProviderSettings from "./ProviderSettings";

// Both halves of NASQuay's AI under one tab, as two tabs of their own because they are
// not the same thing: the assistant is a chat panel whose model resonance chooses and
// whose calls run through the signed-in person's browser; providers are models NASQuay
// calls itself, from the worker, for routines that run with nobody signed in.
const TABS = ["Assistant", "Providers"] as const;
type Tab = (typeof TABS)[number];

const SAYS: Record<Tab, string> = {
  Assistant:
    "A chat panel on NASQuay's pages. Resonance chooses the model; anything it asks for runs as the person signed in.",
  Providers:
    "Models NASQuay calls itself, for routines that run on a schedule with nobody signed in.",
};

export default function AiSettings() {
  const [tab, setTab] = useState<Tab>("Assistant");

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-zinc-600">
        {TABS.map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={
              name === tab
                ? "px-3 py-1 text-sm border border-amber-500 border-b-0 text-amber-400"
                : "px-3 py-1 text-sm border border-transparent text-zinc-200 hover:border-zinc-600"
            }
          >
            {name}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-300">{SAYS[tab]}</span>
        <Help>
          <p>NASQuay uses AI in two unrelated ways, and they are set up separately.</p>
          <p>The <span className="text-zinc-200">assistant</span> is a chat panel from a resonance server, framed in NASQuay's own pages. Resonance chooses its model. Everything the panel asks for runs through the signed-in person's browser, as that person, so their role decides it and it lands in the audit log under their name.</p>
          <p><span className="text-zinc-200">Providers</span> are models NASQuay calls itself, from the worker, with nobody signed in — for AI routines and for the written summary on a report. They are never used by the panel.</p>
          <p>Neither is required. Routines with fixed steps and every report work with no AI configured at all.</p>
        </Help>
      </div>
      {tab === "Assistant" && <AssistantSettings />}
      {tab === "Providers" && <ProviderSettings />}
    </div>
  );
}
