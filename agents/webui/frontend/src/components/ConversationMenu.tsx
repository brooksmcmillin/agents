import { Fragment, useState } from 'react';
import { Menu, Transition } from '@headlessui/react';
import {
  EllipsisVerticalIcon,
  PencilIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';
import { Dialog } from './Dialog';
import { Button } from './Button';
import { Input } from './Input';
import { useConversationStore } from '@/store/conversationStore';

interface ConversationMenuProps {
  conversationId: string;
  currentTitle: string | null;
}

export function ConversationMenu({ conversationId, currentTitle }: ConversationMenuProps) {
  const [isRenaming, setIsRenaming] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [newTitle, setNewTitle] = useState(currentTitle || '');
  const { updateConversationTitle, deleteConversation } = useConversationStore();

  const handleRename = async () => {
    if (newTitle.trim()) {
      await updateConversationTitle(conversationId, newTitle.trim());
      setIsRenaming(false);
    }
  };

  const handleDelete = async () => {
    await deleteConversation(conversationId);
    setIsDeleting(false);
  };

  return (
    <>
      <Menu as="div" className="relative">
        <Menu.Button className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700">
          <EllipsisVerticalIcon className="h-5 w-5 text-gray-500 dark:text-gray-400" />
        </Menu.Button>

        <Transition
          as={Fragment}
          enter="transition ease-out duration-100"
          enterFrom="transform opacity-0 scale-95"
          enterTo="transform opacity-100 scale-100"
          leave="transition ease-in duration-75"
          leaveFrom="transform opacity-100 scale-100"
          leaveTo="transform opacity-0 scale-95"
        >
          <Menu.Items className="absolute right-0 mt-1 w-48 origin-top-right rounded-lg bg-white dark:bg-gray-800 shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none z-10">
            <div className="py-1">
              <Menu.Item>
                {({ active }) => (
                  <button
                    onClick={() => {
                      setNewTitle(currentTitle || '');
                      setIsRenaming(true);
                    }}
                    className={`
                      ${active ? 'bg-gray-100 dark:bg-gray-700' : ''}
                      flex items-center gap-2 w-full px-4 py-2 text-sm text-gray-700 dark:text-gray-300
                    `}
                  >
                    <PencilIcon className="h-4 w-4" />
                    Rename
                  </button>
                )}
              </Menu.Item>
              <Menu.Item>
                {({ active }) => (
                  <button
                    onClick={() => setIsDeleting(true)}
                    className={`
                      ${active ? 'bg-gray-100 dark:bg-gray-700' : ''}
                      flex items-center gap-2 w-full px-4 py-2 text-sm text-red-600 dark:text-red-400
                    `}
                  >
                    <TrashIcon className="h-4 w-4" />
                    Delete
                  </button>
                )}
              </Menu.Item>
            </div>
          </Menu.Items>
        </Transition>
      </Menu>

      {/* Rename Dialog */}
      <Dialog
        open={isRenaming}
        onClose={() => setIsRenaming(false)}
        title="Rename Conversation"
      >
        <div className="space-y-4">
          <Input
            label="Title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Conversation title..."
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setIsRenaming(false)}>
              Cancel
            </Button>
            <Button onClick={handleRename} disabled={!newTitle.trim()}>
              Save
            </Button>
          </div>
        </div>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={isDeleting}
        onClose={() => setIsDeleting(false)}
        title="Delete Conversation"
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Are you sure you want to delete this conversation? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setIsDeleting(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={handleDelete}>
              Delete
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
