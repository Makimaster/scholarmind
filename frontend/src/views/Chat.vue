<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header"><h2>文渊 · ScholarMind</h2></div>
      <nav class="nav-menu">
        <router-link to="/library" class="nav-item"><span>📚</span> 论文文献库</router-link>
        <router-link to="/chat" class="nav-item active"><span>💬</span> 文献对话调研</router-link>
        <router-link to="/observability" class="nav-item"><span>📊</span> 系统可观测页</router-link>
        <router-link to="/settings" class="nav-item"><span>⚙️</span> 系统配置中心</router-link>
      </nav>
      <div class="sidebar-footer"><button class="logout-btn" @click="authStore.logout">退出登录</button></div>
    </aside>

    <div class="chat-container-wrapper">
      <section class="chat-panel">
        <header class="panel-header">
          <div>
            <h1>文献智能调研对话</h1>
            <span class="scope-badge">检索范围：{{ scopeLabel }}</span>
          </div>
        </header>

        <div ref="messageListRef" class="message-list">
          <article v-for="msg in chatStore.messages" :key="msg.id" :class="['message-item', msg.role]">
            <div class="avatar-box">{{ msg.role === 'user' ? '👤' : '文' }}</div>
            <div class="message-bubble">
              <div class="message-sender">{{ msg.role === 'user' ? '提问者' : '文渊 AI 助手' }}</div>
              <div class="message-content" v-html="renderMessage(msg.content, msg.citations)"></div>
              <div v-if="msg.role === 'assistant' && msg.citations.length" class="citations-footer">
                <CitationCard
                  v-for="(cite, idx) in msg.citations"
                  :key="`${msg.id}-${idx}`"
                  :citation="cite"
                  :index="idx"
                  :active="chatStore.activeCitation === cite"
                  @select="chatStore.selectCitation"
                />
              </div>
            </div>
          </article>
        </div>

        <footer class="input-panel">
          <form class="input-form" @submit.prevent="sendMessage">
            <textarea
              v-model="inputQuery"
              placeholder="请输入您的学术调研问题，Enter 发送，Shift+Enter 换行..."
              :disabled="chatStore.streaming"
              @keydown="handleKeydown"
            ></textarea>
            <button type="submit" class="send-btn" :disabled="chatStore.streaming || !inputQuery.trim()">
              {{ chatStore.streaming ? '生成中...' : '发送' }}
            </button>
          </form>
        </footer>
      </section>

      <PreviewPanel :citation="chatStore.activeCitation" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';
import { useRoute } from 'vue-router';
import DOMPurify from 'dompurify';
import { chatApi, type Citation } from '../api';
import CitationCard from '../components/CitationCard.vue';
import PreviewPanel from '../components/PreviewPanel.vue';
import { useAuthStore } from '../stores/auth';
import { useChatStore } from '../stores/chat';

const route = useRoute();
const authStore = useAuthStore();
const chatStore = useChatStore();
const inputQuery = ref('');
const messageListRef = ref<HTMLDivElement | null>(null);

const scopedPaperIds = computed(() => {
  const rawPaperId = route.query.paperId;
  const values = Array.isArray(rawPaperId) ? rawPaperId : rawPaperId ? [rawPaperId] : [];
  return values
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value) && value > 0);
});

const scopeLabel = computed(() => (scopedPaperIds.value.length ? '当前选中文献' : '当前用户知识库'));

function renderMessage(content: string, citations: Citation[]) {
  const escaped = DOMPurify.sanitize(content.replace(/\n/g, '<br>'));
  return escaped.replace(/\[(\d+)]/g, (_match, rawIndex) => {
    const index = Number(rawIndex) - 1;
    if (!citations[index]) return `[${rawIndex}]`;
    return `<button class="inline-cite" data-cite-index="${index}">[${rawIndex}]</button>`;
  });
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

async function scrollToBottom() {
  await nextTick();
  if (messageListRef.value) messageListRef.value.scrollTop = messageListRef.value.scrollHeight;
}

async function sendMessage() {
  const question = inputQuery.value.trim();
  if (!question || chatStore.streaming) return;
  inputQuery.value = '';
  chatStore.appendUserMessage(question);
  chatStore.startAssistantMessage();
  await scrollToBottom();

  try {
    const conversationId = await chatStore.ensureConversation();
    const paperIds = scopedPaperIds.value;
    const response = await fetch(chatApi.queryUrl(), {
      method: 'POST',
      headers: chatApi.headers(),
      body: JSON.stringify({
        conversation_id: conversationId,
        question,
        scope_type: paperIds.length ? 'papers' : 'all',
        folder_id: null,
        paper_ids: paperIds,
      }),
    });

    if (!response.ok || !response.body) {
      chatStore.appendToken(`请求失败：${response.status}`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) handleSseBlock(block);
      await scrollToBottom();
    }
    if (buffer.trim()) handleSseBlock(buffer);
  } catch {
    chatStore.appendToken('请求失败，请稍后重试。');
  } finally {
    chatStore.finishStreaming();
    await scrollToBottom();
  }
}

function handleSseBlock(block: string) {
  const eventLine = block.split('\n').find((line) => line.startsWith('event:'));
  const dataLine = block.split('\n').find((line) => line.startsWith('data:'));
  if (!eventLine || !dataLine) return;
  const event = eventLine.replace('event:', '').trim();
  let payload: any;
  try {
    payload = JSON.parse(dataLine.replace('data:', '').trim());
  } catch {
    return;
  }
  if (event === 'cite') chatStore.appendCitation(payload as Citation);
  if (event === 'token') chatStore.appendToken(payload.delta || '');
  if (event === 'done') chatStore.finishStreaming(payload.latency_ms);
}

function handleInlineCitationClick(event: MouseEvent) {
  const target = event.target as HTMLElement;
  const index = target.dataset.citeIndex;
  if (index === undefined) return;
  const citation = chatStore.citations[Number(index)];
  if (citation) chatStore.selectCitation(citation);
}

nextTick(() => messageListRef.value?.addEventListener('click', handleInlineCitationClick));
</script>

<style scoped>
.app-layout { display:flex; height:100vh; background:#f7f9f8; color:#1a3322; overflow:hidden; }
.sidebar { width:260px; background:#0f3d24; color:#fff; display:flex; flex-direction:column; flex-shrink:0; }
.sidebar-header { padding:30px 24px; border-bottom:1px solid rgba(255,255,255,.1); }
.sidebar-header h2 { margin:0; font-size:20px; background:linear-gradient(135deg,#a2f26d,#fff); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.nav-menu { flex:1; padding:24px 16px; display:flex; flex-direction:column; gap:10px; }
.nav-item { display:flex; gap:12px; padding:12px 16px; color:rgba(255,255,255,.75); text-decoration:none; font-weight:700; border-radius:8px; }
.nav-item:hover,.nav-item.active { color:#fff; background:rgba(255,255,255,.12); }
.sidebar-footer { padding:24px 16px; border-top:1px solid rgba(255,255,255,.1); }
.logout-btn { width:100%; padding:10px; background:transparent; color:rgba(255,255,255,.7); border:1px solid rgba(255,255,255,.2); border-radius:8px; cursor:pointer; }
.chat-container-wrapper { flex:1; display:flex; min-width:0; }
.chat-panel { flex:1; min-width:0; display:flex; flex-direction:column; }
.panel-header { padding:22px 34px; background:#fff; border-bottom:1px solid #e1e6e3; }
.panel-header h1 { margin:0 0 8px; font-size:24px; color:#0f3d24; }
.scope-badge { padding:5px 10px; border-radius:999px; background:#eef8ea; color:#2d7142; font-size:12px; }
.message-list { flex:1; overflow:auto; padding:28px 34px; display:flex; flex-direction:column; gap:22px; }
.message-item { display:flex; gap:14px; max-width:900px; }
.message-item.user { align-self:flex-end; flex-direction:row-reverse; }
.avatar-box { width:38px; height:38px; display:grid; place-items:center; border-radius:12px; background:#0f3d24; color:#fff; font-weight:800; flex:0 0 auto; }
.message-item.user .avatar-box { background:#84b85c; }
.message-bubble { background:#fff; border:1px solid #e1e8e3; border-radius:18px; padding:16px; box-shadow:0 10px 24px rgba(15,61,36,.05); }
.message-item.user .message-bubble { background:#eaf8e6; }
.message-sender { font-weight:800; color:#0f3d24; margin-bottom:8px; font-size:13px; }
.message-content { line-height:1.8; }
.message-content :deep(.inline-cite) { border:0; background:#e1f6d7; color:#0f7a3a; font-weight:800; border-radius:6px; cursor:pointer; margin:0 2px; }
.citations-footer { margin-top:14px; display:grid; gap:10px; }
.input-panel { padding:18px 34px; background:#fff; border-top:1px solid #e1e6e3; }
.input-form { display:flex; gap:12px; align-items:flex-end; }
textarea { flex:1; min-height:54px; max-height:150px; resize:vertical; border:1px solid #dce7df; border-radius:14px; padding:14px 16px; font-size:15px; outline:none; }
textarea:focus { border-color:#70c36b; box-shadow:0 0 0 3px rgba(112,195,107,.15); }
.send-btn { padding:15px 24px; border:0; border-radius:14px; background:#0f3d24; color:#fff; font-weight:800; cursor:pointer; }
.send-btn:disabled { background:#8aa696; cursor:not-allowed; }
</style>
