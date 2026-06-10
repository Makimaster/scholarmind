<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header"><h2>文渊 · ScholarMind</h2></div>
      <nav class="nav-menu">
        <router-link to="/library" class="nav-item active"
          ><span>📚</span> 论文文献库</router-link
        >
        <router-link to="/chat" class="nav-item"
          ><span>💬</span> 文献对话调研</router-link
        >
        <router-link to="/observability" class="nav-item"
          ><span>📊</span> 系统可观测页</router-link
        >
        <router-link to="/settings" class="nav-item"
          ><span>⚙️</span> 系统配置中心</router-link
        >
      </nav>
      <div class="sidebar-footer">
        <button class="logout-btn" @click="authStore.logout">退出登录</button>
      </div>
    </aside>

    <main class="main-content">
      <header class="content-header">
        <h1>论文文献库</h1>
      </header>

      <div class="content-body">
        <div class="control-panel">
          <div class="folders-section">
            <div class="section-title">
              <h3>📂 文献文件夹</h3>
              <button @click="createFolder" class="add-folder-btn">
                + 新建
              </button>
            </div>
            <ul class="folder-list">
              <li
                v-for="folder in folders"
                :key="folder.id"
                :class="{ active: selectedFolderId === folder.id }"
                @click="selectedFolderId = folder.id"
                class="folder-item"
              >
                <span>📁 {{ folder.name }}</span>
                <span class="folder-count">{{ folder.paper_count }}</span>
                <button
                  class="delete-folder-btn"
                  @click.stop="confirmDeleteFolder(folder)"
                  title="删除文件夹"
                >
                  🗑️
                </button>
              </li>
            </ul>
          </div>

          <div
            class="upload-section"
            :class="{ dragging: isDragging }"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleDrop"
            @click="triggerFileSelect"
          >
            <div class="upload-box">
              <span class="upload-icon">📤</span>
              <p>将 PDF 论文拖拽至此上传</p>
              <span class="upload-sub">或点击此处选择文件</span>
              <input
                type="file"
                ref="fileInputRef"
                @change="handleFileSelect"
                multiple
                accept=".pdf"
                style="display: none"
              />
            </div>
          </div>
        </div>

        <div class="papers-section">
          <div class="table-header">
            <h3>📑 论文列表</h3>
            <div class="search-box">
              <input
                type="text"
                v-model="searchQuery"
                placeholder="搜索论文标题/作者..."
              />
            </div>
          </div>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>论文标题</th>
                  <th>作者</th>
                  <th>年份</th>
                  <th>解析状态</th>
                  <th>入库时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="paper in filteredPapers" :key="paper.id">
                  <td class="paper-title" @click="openPaper(paper)">
                    {{ paper.title }}
                  </td>
                  <td>{{ formatAuthors(paper.authors) }}</td>
                  <td>{{ paper.year || "-" }}</td>
                  <td>
                    <span :class="['status-badge', paper.status]">{{
                      statusMap[paper.status] || paper.status
                    }}</span>
                  </td>
                  <td>{{ formatBeijingTime(paper.created_at) }}</td>
                  <td>
                    <button
                      class="delete-btn"
                      @click="confirmDeletePaper(paper)"
                    >
                      删除
                    </button>
                  </td>
                </tr>
                <tr v-if="!filteredPapers.length">
                  <td colspan="6" class="empty-row">暂无文献数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>

    <div
      v-if="showFolderModal"
      class="modal-overlay"
      @click.self="showFolderModal = false"
    >
      <div class="modal-card">
        <div class="modal-header">
          <h3>📂 新建文献文件夹</h3>
          <button @click="showFolderModal = false" class="close-modal-btn">
            ×
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <input
              type="text"
              v-model="newFolderName"
              placeholder="请输入文件夹名称..."
              ref="newFolderInputRef"
              @keyup.enter="submitCreateFolder"
              autofocus
            />
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showFolderModal = false" class="btn-secondary">
            取消</button
          ><button
            @click="submitCreateFolder"
            class="btn-primary"
            :disabled="!newFolderName.trim()"
          >
            确定
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="confirmModal.show"
      class="modal-overlay"
      @click.self="closeConfirmModal(false)"
    >
      <div class="modal-card">
        <div class="modal-header">
          <h3>{{ confirmModal.title }}</h3>
          <button @click="closeConfirmModal(false)" class="close-modal-btn">
            ×
          </button>
        </div>
        <div class="modal-body">
          <p>{{ confirmModal.message }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closeConfirmModal(false)" class="btn-secondary">
            取消</button
          ><button @click="closeConfirmModal(true)" class="btn-danger">
            确定
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, nextTick } from "vue";
import { useRouter } from "vue-router";
import { paperApi, foldersApi } from "../api";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const authStore = useAuthStore();

const isDragging = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);
const searchQuery = ref("");
const selectedFolderId = ref<number | null>(null);
const folders = ref<any[]>([]);
const papers = ref<any[]>([]);
const showFolderModal = ref(false);
const newFolderName = ref("");
const newFolderInputRef = ref<HTMLInputElement | null>(null);
const confirmModal = ref({
  show: false,
  title: "",
  message: "",
  onConfirm: null as (() => void) | null,
});

function formatAuthors(authors: unknown): string {
  if (!authors) return '未知';
  if (Array.isArray(authors)) return authors.join(', ');
  if (typeof authors === 'string') {
    try {
      const parsed = JSON.parse(authors);
      return Array.isArray(parsed) ? parsed.join(', ') : authors;
    } catch { return authors; }
  }
  return String(authors);
}

const statusMap: Record<string, string> = {
  queued: "排队中",
  pending: "排队中",
  parsing: "解析中",
  indexing: "索引中",
  done: "就绪",
  completed: "就绪",
  failed: "失败",
};
const activeStatuses = new Set(["queued", "pending", "parsing", "indexing"]);
let refreshTimer: number | undefined;

const filteredPapers = computed(() =>
  papers.value.filter((p) => {
    if (selectedFolderId.value && p.folder_id !== selectedFolderId.value)
      return false;
    const q = searchQuery.value.toLowerCase();
    return (
      !q ||
      p.title?.toLowerCase().includes(q) ||
      (p.authors || "").toLowerCase().includes(q)
    );
  }),
);

async function loadData() {
  const [p, f] = await Promise.all([paperApi.list(), foldersApi.list()]);
  papers.value = p;
  folders.value = f;
}

function stopRefreshPolling() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
    refreshTimer = undefined;
  }
}

function hasActivePapers() {
  return papers.value.some((paper) => activeStatuses.has(String(paper.status || "")));
}

function startRefreshPolling() {
  stopRefreshPolling();
  refreshTimer = window.setInterval(async () => {
    await loadData();
    if (!hasActivePapers()) stopRefreshPolling();
  }, 2000);
}

function parseBackendTime(value: string) {
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value)) {
    return new Date(`${value}Z`);
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) {
    return new Date(`${value.replace(" ", "T")}Z`);
  }
  return new Date(value);
}

function formatBeijingTime(value?: string | null) {
  if (!value) return "-";
  const date = parseBackendTime(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function triggerFileSelect() {
  fileInputRef.value?.click();
}

function createFolder() {
  newFolderName.value = "";
  showFolderModal.value = true;
  nextTick(() => newFolderInputRef.value?.focus());
}

async function submitCreateFolder() {
  const name = newFolderName.value.trim();
  if (!name) return;
  await foldersApi.create({ name });
  showFolderModal.value = false;
  await loadData();
}

function confirmDeleteFolder(folder: { id: number; name: string }) {
  confirmModal.value = {
    show: true,
    title: "🗑️ 删除文献文件夹",
    message: `确定要删除文件夹 "${folder.name}" 吗？文件夹中的文献不会被删除。`,
    onConfirm: async () => {
      await foldersApi.delete(folder.id);
      if (selectedFolderId.value === folder.id) selectedFolderId.value = null;
      await loadData();
    },
  };
}

function confirmDeletePaper(paper: { id: number; title: string }) {
  confirmModal.value = {
    show: true,
    title: "🗑️ 删除文献",
    message: `确定要删除 "${paper.title}" 吗？内容将被彻底清除，不可恢复。`,
    onConfirm: async () => {
      await paperApi.delete(paper.id);
      await loadData();
    },
  };
}

function closeConfirmModal(isConfirmed: boolean) {
  if (isConfirmed && confirmModal.value.onConfirm)
    confirmModal.value.onConfirm();
  confirmModal.value.show = false;
}

function handleDrop(e: DragEvent) {
  isDragging.value = false;
  if (e.dataTransfer?.files) uploadFiles(e.dataTransfer.files);
}
function handleFileSelect(e: Event) {
  const t = e.target as HTMLInputElement;
  if (t.files) uploadFiles(t.files);
  t.value = "";
}

async function uploadFiles(files: FileList) {
  await paperApi.upload(Array.from(files), selectedFolderId.value);
  await loadData();
  startRefreshPolling();
}

function openPaper(paper: any) {
  // TODO: 后续可以传递 paperId 让后端建立 scoped 会话
  router.push({ path: "/chat", query: { paperId: paper.id } });
}
onMounted(async () => {
  await loadData();
  if (hasActivePapers()) startRefreshPolling();
});
onUnmounted(stopRefreshPolling);
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background: #f7f9f8;
  color: #1a3322;
}
.sidebar {
  width: 260px;
  background: #0f3d24;
  color: #fff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.sidebar-header {
  padding: 30px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.sidebar-header h2 {
  margin: 0;
  font-size: 20px;
  background: linear-gradient(135deg, #a2f26d, #fff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.nav-menu {
  flex: 1;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.nav-item {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
  font-weight: 700;
  border-radius: 8px;
}
.nav-item:hover,
.nav-item.active {
  color: #fff;
  background: rgba(255, 255, 255, 0.12);
}
.sidebar-footer {
  padding: 24px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}
.logout-btn {
  width: 100%;
  padding: 10px;
  background: transparent;
  color: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  cursor: pointer;
}
.main-content {
  flex: 1;
  height: 100vh;
  overflow: auto;
}
.content-header {
  padding: 20px 40px;
  background: #fff;
  border-bottom: 1px solid #e1e6e3;
}
.content-header h1 {
  color: #0f3d24;
}
.content-body {
  padding: 34px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.control-panel {
  display: flex;
  gap: 24px;
}
.folders-section {
  flex: 1;
  background: #fff;
  border: 1px solid #e1e6e3;
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 8px 22px rgba(15, 61, 36, 0.04);
}
.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.add-folder-btn {
  border: 0;
  background: #0f3d24;
  color: #fff;
  border-radius: 8px;
  padding: 8px 14px;
  font-weight: 700;
}
.folder-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}
.folder-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
}
.folder-item:hover,
.folder-item.active {
  background: #edf8ec;
}
.folder-count {
  font-size: 12px;
  color: #66806e;
}
.delete-folder-btn {
  background: transparent;
  border: 0;
  cursor: pointer;
}
.upload-section {
  flex: 1;
}
.upload-box {
  border: 2px dashed #cfe0d3;
  border-radius: 14px;
  padding: 40px;
  text-align: center;
  cursor: pointer;
}
.upload-box p {
  margin: 0;
  color: #0f3d24;
  font-weight: 700;
}
.upload-sub {
  font-size: 13px;
  color: #66806e;
}
.papers-section {
  background: #fff;
  border: 1px solid #e1e6e3;
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 8px 22px rgba(15, 61, 36, 0.04);
}
.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.table-container {
  overflow: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 12px;
  border-bottom: 1px solid #edf2ee;
  text-align: left;
  font-size: 13px;
}
th {
  color: #667e6e;
}
.paper-title {
  cursor: pointer;
  color: #0f7a3a;
  font-weight: 700;
}
.status-badge {
  padding: 4px 10px;
  border-radius: 999px;
  background: #eef8ea;
  color: #0f7a3a;
  font-size: 12px;
}
.status-badge.queued,
.status-badge.pending {
  background: #fff7dd;
  color: #8a5a00;
}
.status-badge.parsing,
.status-badge.indexing {
  background: #eaf3ff;
  color: #1f5f9f;
}
.status-badge.done,
.status-badge.completed {
  background: #eef8ea;
  color: #0f7a3a;
}
.status-badge.failed {
  background: #fff0f0;
  color: #a71d24;
}
.delete-btn {
  background: transparent;
  color: #c44848;
  border: 0;
}
.empty-row {
  text-align: center;
  color: #667e6e;
  padding: 24px;
}
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 100;
}
.modal-card {
  background: #fff;
  border-radius: 16px;
  padding: 28px;
  min-width: 360px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.close-modal-btn {
  border: 0;
  background: transparent;
  font-size: 20px;
}
.modal-body {
  margin: 16px 0;
}
.modal-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
.btn-primary,
.btn-danger,
.btn-secondary {
  border: 0;
  border-radius: 8px;
  padding: 10px 18px;
  font-weight: 700;
}
.btn-primary {
  background: #0f3d24;
  color: #fff;
}
.btn-secondary {
  background: #e1e8e3;
  color: #243b2c;
}
.btn-danger {
  background: #a71d24;
  color: #fff;
}
.form-group input {
  width: 100%;
  padding: 12px;
  border: 1px solid #e1e8e3;
  border-radius: 10px;
  font-size: 14px;
}
</style>
