import { useState } from "react";
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
      <div className="text-xs text-zinc-300">{SAYS[tab]}</div>
      {tab === "Assistant" && <AssistantSettings />}
      {tab === "Providers" && <ProviderSettings />}
    </div>
  );
}
