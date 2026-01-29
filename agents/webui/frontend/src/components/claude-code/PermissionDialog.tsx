import { Dialog } from '@/components/Dialog';
import { Button } from '@/components/Button';
import {
  ShieldExclamationIcon,
  CommandLineIcon,
  PencilSquareIcon,
  DocumentIcon,
} from '@heroicons/react/24/outline';
import type { ClaudeCodePermissionRequest } from '@/api/types';

interface PermissionDialogProps {
  permission: ClaudeCodePermissionRequest | null;
  onApprove: () => void;
  onDeny: () => void;
}

export function PermissionDialog({ permission, onApprove, onDeny }: PermissionDialogProps) {
  if (!permission) return null;

  const getIcon = () => {
    switch (permission.tool_type) {
      case 'bash':
        return <CommandLineIcon className="h-8 w-8 text-yellow-500" />;
      case 'edit':
      case 'write':
        return <PencilSquareIcon className="h-8 w-8 text-blue-500" />;
      case 'read':
        return <DocumentIcon className="h-8 w-8 text-green-500" />;
      default:
        return <ShieldExclamationIcon className="h-8 w-8 text-yellow-500" />;
    }
  };

  const getTitle = () => {
    switch (permission.tool_type) {
      case 'bash':
        return 'Execute Command';
      case 'edit':
        return 'Edit File';
      case 'write':
        return 'Create/Write File';
      case 'read':
        return 'Read File';
      default:
        return 'Permission Required';
    }
  };

  return (
    <Dialog open={true} onClose={onDeny} title={getTitle()} maxWidth="lg">
      <div className="space-y-4">
        <div className="flex items-start gap-4">
          <div className="flex-shrink-0 p-2 bg-gray-100 dark:bg-gray-700 rounded-lg">
            {getIcon()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
              Claude Code is requesting permission to:
            </p>
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-3 font-mono text-sm overflow-x-auto">
              {permission.command && (
                <div className="mb-2">
                  <span className="text-gray-500 dark:text-gray-400">Command: </span>
                  <span className="text-gray-900 dark:text-gray-100">{permission.command}</span>
                </div>
              )}
              {permission.file_path && (
                <div className="mb-2">
                  <span className="text-gray-500 dark:text-gray-400">File: </span>
                  <span className="text-gray-900 dark:text-gray-100">{permission.file_path}</span>
                </div>
              )}
              <div className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
                {permission.description}
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
          <Button variant="secondary" onClick={onDeny}>
            Deny
          </Button>
          <Button onClick={onApprove}>
            Approve
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
