import { useState } from 'react';
import { Listbox, Transition } from '@headlessui/react';
import {
  FolderIcon,
  ChevronUpDownIcon,
  CheckIcon,
  PlusIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';
import { Dialog } from '@/components/Dialog';
import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import type { ClaudeCodeWorkspace } from '@/api/types';

interface WorkspaceSelectorProps {
  workspaces: ClaudeCodeWorkspace[];
  selectedWorkspace: string | null;
  onSelect: (name: string | null) => void;
  onCreateWorkspace: (name: string, gitUrl?: string) => Promise<void>;
  onDeleteWorkspace: (name: string, force?: boolean) => Promise<void>;
  disabled?: boolean;
}

export function WorkspaceSelector({
  workspaces,
  selectedWorkspace,
  onSelect,
  onCreateWorkspace,
  onDeleteWorkspace,
  disabled = false,
}: WorkspaceSelectorProps) {
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [workspaceToDelete, setWorkspaceToDelete] = useState<string | null>(null);
  const [newWorkspaceName, setNewWorkspaceName] = useState('');
  const [newWorkspaceGitUrl, setNewWorkspaceGitUrl] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const selectedWs = workspaces.find((w) => w.name === selectedWorkspace);

  const handleCreate = async () => {
    if (!newWorkspaceName.trim()) return;

    setIsCreating(true);
    setCreateError(null);

    try {
      await onCreateWorkspace(
        newWorkspaceName.trim(),
        newWorkspaceGitUrl.trim() || undefined
      );
      setShowCreateDialog(false);
      setNewWorkspaceName('');
      setNewWorkspaceGitUrl('');
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create workspace');
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!workspaceToDelete) return;

    setIsDeleting(true);
    try {
      await onDeleteWorkspace(workspaceToDelete);
      setShowDeleteDialog(false);
      setWorkspaceToDelete(null);
    } catch {
      // Error is handled by store
    } finally {
      setIsDeleting(false);
    }
  };

  const openDeleteDialog = (name: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setWorkspaceToDelete(name);
    setShowDeleteDialog(true);
  };

  return (
    <>
      <div className="flex items-center gap-2">
        <Listbox value={selectedWorkspace} onChange={onSelect} disabled={disabled}>
          <div className="relative flex-1">
            <Listbox.Button className="relative w-full cursor-pointer rounded-lg bg-white dark:bg-gray-800 py-2 pl-3 pr-10 text-left border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed">
              <span className="flex items-center gap-2">
                <FolderIcon className="h-5 w-5 text-gray-400" />
                <span className="block truncate text-gray-900 dark:text-gray-100">
                  {selectedWs?.name || 'Select workspace...'}
                </span>
              </span>
              <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                <ChevronUpDownIcon className="h-5 w-5 text-gray-400" />
              </span>
            </Listbox.Button>

            <Transition
              leave="transition ease-in duration-100"
              leaveFrom="opacity-100"
              leaveTo="opacity-0"
            >
              <Listbox.Options className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-lg bg-white dark:bg-gray-800 py-1 shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none">
                {workspaces.length === 0 ? (
                  <div className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400">
                    No workspaces available
                  </div>
                ) : (
                  workspaces.map((ws) => (
                    <Listbox.Option
                      key={ws.name}
                      value={ws.name}
                      className={({ active }) =>
                        `relative cursor-pointer select-none py-2 pl-10 pr-10 ${
                          active
                            ? 'bg-primary-100 dark:bg-primary-900 text-primary-900 dark:text-primary-100'
                            : 'text-gray-900 dark:text-gray-100'
                        }`
                      }
                    >
                      {({ selected }) => (
                        <>
                          <div className="flex flex-col">
                            <span className={`block truncate ${selected ? 'font-medium' : 'font-normal'}`}>
                              {ws.name}
                            </span>
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              {ws.is_git_repo && ws.current_branch && (
                                <span className="mr-2">
                                  <span className="text-green-600 dark:text-green-400">git:</span>{' '}
                                  {ws.current_branch}
                                </span>
                              )}
                              {ws.file_count} files, {ws.size_mb} MB
                            </span>
                          </div>
                          {selected && (
                            <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-primary-600 dark:text-primary-400">
                              <CheckIcon className="h-5 w-5" />
                            </span>
                          )}
                          <button
                            onClick={(e) => openDeleteDialog(ws.name, e)}
                            className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-red-500"
                          >
                            <TrashIcon className="h-4 w-4" />
                          </button>
                        </>
                      )}
                    </Listbox.Option>
                  ))
                )}
              </Listbox.Options>
            </Transition>
          </div>
        </Listbox>

        <Button
          variant="secondary"
          size="md"
          onClick={() => setShowCreateDialog(true)}
          disabled={disabled}
          title="Create new workspace"
        >
          <PlusIcon className="h-5 w-5" />
        </Button>
      </div>

      {/* Create Workspace Dialog */}
      <Dialog
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        title="Create Workspace"
      >
        <div className="space-y-4">
          <Input
            label="Workspace Name"
            value={newWorkspaceName}
            onChange={(e) => setNewWorkspaceName(e.target.value)}
            placeholder="my-project"
            disabled={isCreating}
          />
          <Input
            label="Git Repository URL (optional)"
            value={newWorkspaceGitUrl}
            onChange={(e) => setNewWorkspaceGitUrl(e.target.value)}
            placeholder="https://github.com/user/repo.git"
            disabled={isCreating}
          />
          {createError && (
            <p className="text-sm text-red-500">{createError}</p>
          )}
          <div className="flex justify-end gap-3 pt-4">
            <Button
              variant="secondary"
              onClick={() => setShowCreateDialog(false)}
              disabled={isCreating}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!newWorkspaceName.trim() || isCreating}
            >
              {isCreating ? 'Creating...' : 'Create'}
            </Button>
          </div>
        </div>
      </Dialog>

      {/* Delete Workspace Dialog */}
      <Dialog
        open={showDeleteDialog}
        onClose={() => setShowDeleteDialog(false)}
        title="Delete Workspace"
      >
        <div className="space-y-4">
          <p className="text-gray-600 dark:text-gray-300">
            Are you sure you want to delete workspace{' '}
            <span className="font-medium text-gray-900 dark:text-white">
              {workspaceToDelete}
            </span>
            ? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3 pt-4">
            <Button
              variant="secondary"
              onClick={() => setShowDeleteDialog(false)}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete'}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
