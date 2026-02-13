import { useState } from 'react';
import { Dialog } from './Dialog';
import { Button } from './Button';
import { Input } from './Input';
import { AgentSelector } from './AgentSelector';
import { useConversationStore } from '@/store/conversationStore';
import type { AgentName } from '@/utils/constants';

interface NewConversationDialogProps {
  open: boolean;
  onClose: () => void;
}

export function NewConversationDialog({ open, onClose }: NewConversationDialogProps) {
  const [selectedAgent, setSelectedAgent] = useState<AgentName | null>(null);
  const [title, setTitle] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const { createConversation } = useConversationStore();

  const handleCreate = async () => {
    if (!selectedAgent) return;

    setIsCreating(true);
    try {
      await createConversation(selectedAgent, title || undefined);
      onClose();
      setSelectedAgent(null);
      setTitle('');
    } catch (error) {
      console.error('Failed to create conversation:', error);
    } finally {
      setIsCreating(false);
    }
  };

  const handleClose = () => {
    if (!isCreating) {
      onClose();
      setSelectedAgent(null);
      setTitle('');
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} title="New Conversation" maxWidth="lg">
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
            Select an agent
          </label>
          <AgentSelector selectedAgent={selectedAgent} onSelect={setSelectedAgent} />
        </div>

        <Input
          label="Title (optional)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="My conversation..."
        />

        <div className="flex justify-end gap-2 pt-4">
          <Button variant="secondary" onClick={handleClose} disabled={isCreating}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={!selectedAgent || isCreating}>
            {isCreating ? 'Creating...' : 'Create'}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
