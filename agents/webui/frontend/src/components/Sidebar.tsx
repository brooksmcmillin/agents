import { useState } from 'react';
import { PlusIcon } from '@heroicons/react/24/outline';
import { Button } from './Button';
import { ConversationList } from './ConversationList';
import { NewConversationDialog } from './NewConversationDialog';

export function Sidebar() {
  const [showNewDialog, setShowNewDialog] = useState(false);

  return (
    <>
      <aside className="w-80 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <Button
            onClick={() => setShowNewDialog(true)}
            className="w-full"
            size="md"
          >
            <PlusIcon className="h-5 w-5 mr-2" />
            New Conversation
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          <ConversationList />
        </div>
      </aside>

      <NewConversationDialog
        open={showNewDialog}
        onClose={() => setShowNewDialog(false)}
      />
    </>
  );
}
