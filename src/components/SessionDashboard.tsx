import React from "react";

interface SessionDashboardProps {
  connection: string;
  websocketState: string;
  hostStatus: string;
  viewerStatus: string;
  ping: number;
  fps: number;
  bandwidth: number;
  cpu: number;
  memory: number;
  resolution: string;
  onReconnect: () => void;
}

export default function SessionDashboard({
  connection,
  websocketState,
  hostStatus,
  viewerStatus,
  ping,
  fps,
  bandwidth,
  cpu,
  memory,
  resolution,
  onReconnect,
}: SessionDashboardProps) {
  return (
    <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-white">Session Dashboard</h3>
          <p className="text-xs text-slate-400">Live connection and performance metrics</p>
        </div>
        <button
          onClick={onReconnect}
          className="text-[10px] px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded-lg text-white font-semibold"
        >
          Reconnect
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs text-slate-400">
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Connection</div>
          <div>{connection}</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">WebSocket</div>
          <div>{websocketState}</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Host</div>
          <div>{hostStatus}</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Viewer</div>
          <div>{viewerStatus}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs text-slate-400">
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Ping</div>
          <div>{ping} ms</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">FPS</div>
          <div>{fps}</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Bandwidth</div>
          <div>{bandwidth} kbps</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Resolution</div>
          <div>{resolution}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs text-slate-400">
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">CPU</div>
          <div>{cpu.toFixed(1)}%</div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-slate-200">Memory</div>
          <div>{memory.toFixed(1)}%</div>
        </div>
      </div>
    </div>
  );
}
