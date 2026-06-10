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

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([
    {
      id: 1,
      role: 'assistant',
      content: '您好！我是您的跨语言文献调研助手“文渊”。请问有什么关于论文、公式或图表的问题我可以帮您解答？',
      citations: [],
    },
  ]);
  const citations = ref<Citation[]>([]);
  const currentConversation = ref<number | null>(null);
  const streaming = ref(false);
  const activeCitation = ref<Citation | null>(null);

  const currentAssistantMessage = computed(() => [...messages.value].reverse().find((msg) => msg.role === 'assistant'));

  async function ensureConversation() {
    if (currentConversation.value !== null) return currentConversation.value;
    const conversation = await chatApi.createConversation({ title: '文献调研会话' });
    currentConversation.value = conversation.id;
    return conversation.id;
  }

  function appendUserMessage(content: string) {
    messages.value.push({ id: Date.now(), role: 'user', content, citations: [] });
  }

  function startAssistantMessage() {
    const message: ChatMessage = { id: Date.now() + 1, role: 'assistant', content: '', citations: [] };
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
    ensureConversation,
    appendUserMessage,
    startAssistantMessage,
    appendToken,
    appendCitation,
    finishStreaming,
    selectCitation,
  };
});
