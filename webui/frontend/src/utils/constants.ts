export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export const AGENT_NAMES = {
  chatbot: 'Chatbot',
  pr: 'PR Agent',
  tasks: 'Task Manager',
  security: 'Security Researcher',
  business: 'Business Advisor',
} as const;

export const AGENT_COLORS = {
  chatbot: 'bg-blue-500',
  pr: 'bg-purple-500',
  tasks: 'bg-green-500',
  security: 'bg-red-500',
  business: 'bg-yellow-500',
} as const;

export const AGENT_DESCRIPTIONS = {
  chatbot: 'General-purpose assistant with access to all tools',
  pr: 'PR and content strategy specialist',
  tasks: 'Task management and organization',
  security: 'AI security research expert with RAG knowledge',
  business: 'Business strategy and monetization advisor',
} as const;

export type AgentName = keyof typeof AGENT_NAMES;
