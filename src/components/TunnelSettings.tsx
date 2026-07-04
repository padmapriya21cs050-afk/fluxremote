import React from "react";

interface TunnelSettingsProps {
  enabled: boolean;
  provider: "Cloudflare" | "Ngrok" | "Tailscale";
  url: string;
  token: string;
  onEnabledChange: (value: boolean) => void;
  onProviderChange: (provider: "Cloudflare" | "Ngrok" | "Tailscale") => void;
  onUrlChange: (value: string) => void;
  onTokenChange: (value: string) => void;
  onSave: () => void;
  saved: boolean;
}

export default function TunnelSettings({
  enabled,
  provider,
  url,
  token,
  onEnabledChange,
  onProviderChange,
  onUrlChange,
  onTokenChange,
  onSave,
  saved,
}: TunnelSettingsProps) {
  return (
    <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6 space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white">Tunnel Settings</h2>
        <p className="text-sm text-slate-400">Route client traffic through an external tunnel URL.</p>
      </div>

      <div className="grid gap-4">
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-2">Tunnel mode</div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onEnabledChange(true)}
              className={`px-3 py-2 rounded-lg text-xs font-semibold ${enabled ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
            >
              Enabled
            </button>
            <button
              type="button"
              onClick={() => onEnabledChange(false)}
              className={`px-3 py-2 rounded-lg text-xs font-semibold ${!enabled ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
            >
              Disabled
            </button>
          </div>
        </div>

        <div>
          <div className="text-xs font-semibold text-slate-300 mb-2">Provider</div>
          <select
            value={provider}
            onChange={(event) => onProviderChange(event.target.value as any)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500"
          >
            <option>Cloudflare</option>
            <option>Ngrok</option>
            <option>Tailscale</option>
          </select>
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-300 block mb-2">Tunnel URL</label>
          <input
            type="text"
            value={url}
            onChange={(event) => onUrlChange(event.target.value)}
            placeholder="https://example.trycloudflare.com"
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-300 block mb-2">Authorization token (optional)</label>
          <input
            type="text"
            value={token}
            onChange={(event) => onTokenChange(event.target.value)}
            placeholder="Bearer token for tunnel endpoint"
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      <button
        type="button"
        onClick={onSave}
        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-lg transition"
      >
        {saved ? "✓ Saved" : "Save Tunnel Settings"}
      </button>
    </div>
  );
}
