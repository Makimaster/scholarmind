<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header"><h2>文渊 · ScholarMind</h2></div>
      <nav class="nav-menu">
        <router-link to="/library" class="nav-item"><span>📚</span> 论文文献库</router-link>
        <router-link to="/chat" class="nav-item"><span>💬</span> 文献对话调研</router-link>
        <router-link to="/observability" class="nav-item active"><span>📊</span> 系统可观测页</router-link>
        <router-link to="/settings" class="nav-item"><span>⚙️</span> 系统配置中心</router-link>
      </nav>
      <div class="sidebar-footer"><button class="logout-btn" @click="authStore.logout">退出登录</button></div>
    </aside>

    <main class="main-content">
      <header class="content-header">
        <h1>系统可观测数据</h1>
        <button class="refresh-btn" :disabled="store.loading" @click="store.refreshAll">{{ store.loading ? '刷新中...' : '立即刷新' }}</button>
      </header>

      <div class="content-body">
        <div class="metrics-grid">
          <div class="metric-card"><span>总问答数</span><strong>{{ store.totalQueries }}</strong></div>
          <div class="metric-card"><span>平均延迟</span><strong>{{ store.averageLatency }}ms</strong></div>
          <div class="metric-card"><span>平均 Token</span><strong>{{ store.averageTokens }}</strong></div>
          <div class="metric-card"><span>导入成功率</span><strong>{{ store.successRate }}%</strong></div>
        </div>

        <section class="observability-section">
          <h3>文档解析与入库流水线</h3>
          <div v-if="store.ingestionTasks.length" class="tasks-container">
            <article v-for="task in store.ingestionTasks" :key="task.id" class="task-progress-card">
              <div class="task-meta">
                <span class="task-name">📄 {{ task.title || task.file_name }}</span>
                <span :class="['stage-tag', task.stage || task.status]">{{ stageLabel(task.stage || task.status) }}</span>
              </div>
              <div class="progress-bar-wrapper"><div class="progress-bar-fill" :style="{ width: `${task.progress || 0}%` }"></div></div>
              <div class="task-foot">
                <span>{{ task.progress || 0 }}% 已完成</span>
                <span v-if="task.error_msg" class="task-error">错误：{{ task.error_msg }}</span>
                <span>{{ formatTime(task.started_at || task.created_at) }}</span>
              </div>
            </article>
          </div>
          <div v-else class="empty-list">目前没有入库任务。</div>
        </section>

        <section class="observability-section">
          <h3>问答检索日志</h3>
          <div class="table-container">
            <table>
              <thead><tr><th>提问</th><th>响应时间</th><th>Prompt</th><th>Completion</th><th>时间</th></tr></thead>
              <tbody>
                <tr v-for="log in store.queryLogs" :key="log.id">
                  <td class="question-text">{{ log.question }}</td>
                  <td>{{ log.latency_ms }} ms</td>
                  <td>{{ log.prompt_tokens }}</td>
                  <td>{{ log.completion_tokens }}</td>
                  <td>{{ formatTime(log.created_at) }}</td>
                </tr>
                <tr v-if="!store.queryLogs.length"><td colspan="5" class="empty-row">暂无查询日志</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import { useAuthStore } from '../stores/auth';
import { useObservabilityStore } from '../stores/observability';

const authStore = useAuthStore();
const store = useObservabilityStore();
let timer: number | undefined;

const stageMap: Record<string, string> = { queued: '排队中', parsing: '解析中', indexing: '索引中', done: '完成', failed: '失败', pending: '等待中' };
function stageLabel(stage?: string) { return stageMap[stage || ''] || stage || '未知'; }
function parseBackendTime(value: string) {
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value)) {
    return new Date(`${value}Z`);
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) {
    return new Date(`${value.replace(' ', 'T')}Z`);
  }
  return new Date(value);
}
function formatTime(value?: string | null) {
  if (!value) return '-';
  const date = parseBackendTime(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

onMounted(async () => {
  await store.refreshAll();
  timer = window.setInterval(() => store.refreshAll(), 5000);
});
onUnmounted(() => { if (timer) window.clearInterval(timer); });
</script>

<style scoped>
.app-layout{display:flex;min-height:100vh;background:#f7f9f8;color:#1a3322}.sidebar{width:260px;background:#0f3d24;color:#fff;display:flex;flex-direction:column}.sidebar-header{padding:30px 24px;border-bottom:1px solid rgba(255,255,255,.1)}.sidebar-header h2{margin:0;font-size:20px;background:linear-gradient(135deg,#a2f26d,#fff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.nav-menu{flex:1;padding:24px 16px;display:flex;flex-direction:column;gap:10px}.nav-item{display:flex;gap:12px;padding:12px 16px;color:rgba(255,255,255,.75);text-decoration:none;font-weight:700;border-radius:8px}.nav-item:hover,.nav-item.active{color:#fff;background:rgba(255,255,255,.12)}.sidebar-footer{padding:24px 16px;border-top:1px solid rgba(255,255,255,.1)}.logout-btn{width:100%;padding:10px;background:transparent;color:rgba(255,255,255,.7);border:1px solid rgba(255,255,255,.2);border-radius:8px;cursor:pointer}.main-content{flex:1;height:100vh;overflow:auto}.content-header{padding:20px 40px;background:#fff;border-bottom:1px solid #e1e6e3;display:flex;justify-content:space-between;align-items:center}.content-header h1{margin:0;color:#0f3d24}.refresh-btn{border:0;background:#0f3d24;color:#fff;border-radius:10px;padding:10px 16px;font-weight:800}.content-body{padding:34px;display:flex;flex-direction:column;gap:28px}.metrics-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.metric-card{background:#fff;border:1px solid #e1e6e3;border-radius:14px;padding:20px;box-shadow:0 8px 22px rgba(15,61,36,.04)}.metric-card span{display:block;color:#667e6e;font-size:13px;margin-bottom:10px}.metric-card strong{font-size:26px;color:#0f3d24}.observability-section{background:#fff;border:1px solid #e1e6e3;border-radius:14px;padding:22px;box-shadow:0 8px 22px rgba(15,61,36,.04)}.observability-section h3{margin:0 0 18px}.tasks-container{display:flex;flex-direction:column;gap:14px}.task-progress-card{border:1px solid #edf2ee;border-radius:12px;padding:14px}.task-meta,.task-foot{display:flex;justify-content:space-between;gap:12px;color:#667e6e;font-size:13px}.task-name{font-weight:800;color:#1a3322}.stage-tag{padding:4px 10px;border-radius:999px;background:#eef8ea;color:#0f7a3a}.stage-tag.failed{background:#fff0f0;color:#a71d24}.progress-bar-wrapper{height:9px;background:#edf2ee;border-radius:999px;overflow:hidden;margin:12px 0}.progress-bar-fill{height:100%;background:linear-gradient(90deg,#0f7a3a,#a2f26d)}.task-error{color:#a71d24}.table-container{overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:12px;border-bottom:1px solid #edf2ee;text-align:left}th{color:#667e6e;font-size:12px}.question-text{max-width:520px}.empty-list,.empty-row{text-align:center;color:#667e6e;padding:24px}
</style>
