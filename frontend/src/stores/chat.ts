import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { chatApi, type Citation } from '../api';

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  latency_ms?: number;
}

const STORAGE_KEY = 'scholarmind-conversation-id';

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([]);
  const citations = ref<Citation[]>([]);
  const _stored = localStorage.getItem(STORAGE_KEY);
  const currentConversation = ref<number | null>(
    _stored !== null ? Number(_stored) : null,
  );
  const streaming = ref(false);
  const activeCitation = ref<Citation | null>(null);
  const conversationsLoaded = ref(false);

  const currentAssistantMessage = computed(() =>
    [...messages.value].reverse().find((msg) => msg.role === 'assistant'),
  );

  function persistConversationId(id: number) {
    currentConversation.value = id;
    localStorage.setItem(STORAGE_KEY, String(id));
  }

  async function loadConversationMessages(conversationId: number) {
    try {
      const history = await chatApi.listMessages(conversationId);
      messages.value = history.map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        citations: (m.citations || []) as Citation[],
      }));
      if (history.length > 0) {
        const lastAssistant = [...history].reverse().find(
          (m: any) => m.role === 'assistant',
        );
        if (lastAssistant?.citations?.length) {
          citations.value = lastAssistant.citations as Citation[];
          activeCitation.value = citations.value[0] || null;
        }
      }
    } catch {
      messages.value = [];
    }
  }

  async function ensureConversation() {
    // If we already have a valid conversation, return it immediately — no reload
    // (reloading would overwrite pending UI messages).
    if (currentConversation.value !== null) {
      return currentConversation.value;
    }

    // Create a new conversation
    const conversation = await chatApi.createConversation({
      title: '文献调研会话',
    });
    persistConversationId(conversation.id);
    messages.value = [];
    citations.value = [];
    activeCitation.value = null;
    return conversation.id;
  }

  function appendUserMessage(content: string) {
    messages.value.push({
      id: Date.now(),
      role: 'user',
      content,
      citations: [],
    });
  }

  function startAssistantMessage() {
    const message: ChatMessage = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      citations: [],
    };
    messages.value.push(message);
    citations.value = [];
    streaming.value = true;
    return message;
  }

  function appendToken(delta: string) {
    const target = currentAssistantMessage.value;
    if (target) target.content += delta;
  }

  function appendCitation(citation: Citation) {
    const target = currentAssistantMessage.value;
    citations.value.push(citation);
    if (target) target.citations.push(citation);
    if (!activeCitation.value) activeCitation.value = citation;
  }

  function finishStreaming(latency_ms?: number) {
    const target = currentAssistantMessage.value;
    if (target) target.latency_ms = latency_ms;
    streaming.value = false;
  }

  function selectCitation(citation: Citation) {
    activeCitation.value = citation;
  }

  return {
    messages,
    citations,
    currentConversation,
    streaming,
    activeCitation,
    conversationsLoaded,
    ensureConversation,
    appendUserMessage,
    startAssistantMessage,
    appendToken,
    appendCitation,
    finishStreaming,
    selectCitation,
    persistConversationId,
    loadConversationMessages,
  };
});
