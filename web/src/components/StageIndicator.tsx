import { Check, Circle, Loader2, X, AlertCircle } from 'lucide-react';
import type { PipelineStage } from '../types';

const statusConfig = {
  pending:   { icon: Circle,      color: 'text-text-muted',  bg: 'bg-border-subtle' },
  running:   { icon: Loader2,     color: 'text-running',     bg: 'bg-running/10' },
  completed: { icon: Check,       color: 'text-success',     bg: 'bg-success/10' },
  failed:    { icon: AlertCircle, color: 'text-error',       bg: 'bg-error/10' },
  cancelled: { icon: X,           color: 'text-warning',     bg: 'bg-warning/10' },
};

export function StageIndicator({ stage }: { stage: PipelineStage }) {
  const config = statusConfig[stage.status];
  const Icon = config.icon;
  const isRunning = stage.status === 'running';

  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border-subtle ${config.bg} transition-all duration-300`}>
      <Icon
        size={18}
        className={`${config.color} shrink-0 ${isRunning ? 'animate-spin' : ''}`}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{stage.label}</span>
          <span className={`text-xs ${config.color}`}>{stage.detail || stage.status}</span>
        </div>
        {isRunning && (
          <div className="mt-1.5 h-1 bg-border rounded-full overflow-hidden">
            <div
              className="h-full bg-accent rounded-full transition-all duration-500 ease-out"
              style={{ width: `${stage.progress}%` }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
