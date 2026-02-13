import { AGENT_NAMES, AGENT_COLORS, AGENT_DESCRIPTIONS } from '@/utils/constants';
import type { AgentName } from '@/utils/constants';

interface AgentSelectorProps {
  selectedAgent: AgentName | null;
  onSelect: (agent: AgentName) => void;
}

export function AgentSelector({ selectedAgent, onSelect }: AgentSelectorProps) {
  const agents = Object.entries(AGENT_NAMES) as [AgentName, string][];

  return (
    <div className="space-y-2">
      {agents.map(([key, name]) => {
        const isSelected = selectedAgent === key;
        const color = AGENT_COLORS[key];
        const description = AGENT_DESCRIPTIONS[key];

        return (
          <button
            key={key}
            onClick={() => onSelect(key)}
            className={`
              w-full text-left p-4 rounded-lg border-2 transition-all
              ${
                isSelected
                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
              }
            `}
          >
            <div className="flex items-start gap-3">
              <div
                className={`
                  w-10 h-10 rounded-full ${color}
                  flex items-center justify-center text-white font-semibold flex-shrink-0
                `}
              >
                {name.charAt(0)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-gray-900 dark:text-white">
                  {name}
                </div>
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {description}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
