import { formatTokenCount } from '@/utils/formatters';

interface TokenBadgeProps {
  count: number | null | undefined;
  className?: string;
}

export function TokenBadge({ count, className = '' }: TokenBadgeProps) {
  if (!count) return null;

  return (
    <span
      className={`
        inline-flex items-center px-2 py-0.5 rounded text-xs font-medium
        bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300
        ${className}
      `}
      title={`${count} tokens`}
    >
      {formatTokenCount(count)}
    </span>
  );
}
