<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>文渊 · ScholarMind</h2>
      </div>
      <nav class="nav-menu">
        <router-link to="/library" class="nav-item active">
          <span class="icon">📚</span> 论文文献库
        </router-link>
        <router-link to="/chat" class="nav-item">
          <span class="icon">💬</span> 文献对话调研
        </router-link>
        <router-link to="/observability" class="nav-item">
          <span class="icon">📊</span> 系统可观测页
        </router-link>
        <router-link to="/settings" class="nav-item">
          <span class="icon">⚙️</span> 系统配置中心
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <button class="logout-btn" @click="handleLogout">退出登录</button>
      </div>
    </aside>

    <!-- Main Content Area -->
    <main class="main-content">
      <header class="content-header">
        <h1>论文文献库</h1>
        <div class="user-profile">
          <span class="avatar">👤</span>
          <span class="username">项目成员</span>
        </div>
      </header>

      <div class="content-body">
        <!-- Folders & Upload Control Pane -->
        <div class="control-panel">
          <!-- Folders list -->
          <div class="folders-section">
            <div class="section-title">
              <h3>📂 文献文件夹</h3>
              <button @click="createFolder" class="add-folder-btn">+ 新建</button>
            </div>
            <ul class="folder-list">
              <li 
                v-for="folder in folders" 
                :key="folder.id" 
                :class="{ active: selectedFolderId === folder.id }"
                @click="selectedFolderId = folder.id"
              >
                <span>📁 {{ folder.name }}</span>
              </li>
            </ul>
          </div>

          <!-- Drag and Drop Upload -->
          <div 
            class="upload-section"
            :class="{ dragging: isDragging }"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleDrop"
          >
            <div class="upload-box">
              <span class="upload-icon">📤</span>
              <p>将 PDF 论文拖拽至此上传</p>
              <span class="upload-sub">或点击此处选择文件</span>
              <input type="file" ref="fileInput" @change="handleFileSelect" multiple accept=".pdf" style="display:none" />
            </div>
          </div>
        </div>

        <!-- Papers List Table -->
        <div class="papers-section">
          <div class="table-header">
            <h3>📑 论文列表</h3>
            <div class="search-box">
              <input type="text" v-model="searchQuery" placeholder="搜索论文标题/作者..." />
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
                  <td class="paper-title" @click="openPaper(paper)">{{ paper.title }}</td>
                  <td>{{ paper.authors?.join(', ') || '未知' }}</td>
                  <td>{{ paper.year || '-' }}</td>
                  <td>
                    <span :class="['status-badge', paper.status]">
                      {{ statusMap[paper.status] }}
                    </span>
                  </td>
                  <td>{{ paper.created_at }}</td>
                  <td>
                    <button class="delete-btn" @click="deletePaper(paper.id)">删除</button>
                  </td>
                </tr>
                <tr v-if="filteredPapers.length === 0">
                  <td colspan="6" class="empty-row">暂无文献数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const router = useRouter();
const authStore = useAuthStore();

const isDragging = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const searchQuery = ref('');
const selectedFolderId = ref<number | null>(null);

const statusMap: Record<string, string> = {
  pending: '排队中',
  parsing: '解析中',
  indexing: '索引中',
  done: '就绪',
  failed: '失败',
};

const folders = ref([
  { id: 1, name: '大语言模型 (LLM)' },
  { id: 2, name: '多模态与 VLM' },
  { id: 3, name: 'RAG 检索增强生成' },
]);

const papers = ref([
  {
    id: 1,
    title: 'Attention Is All You Need',
    authors: ['Vaswani et al.'],
    year: 2017,
    status: 'done',
    created_at: '2026-06-03 10:00:00',
  },
  {
    id: 2,
    title: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks',
    authors: ['Lewis et al.'],
    year: 2020,
    status: 'parsing',
    created_at: '2026-06-03 12:30:00',
  },
]);

const filteredPapers = computed(() => {
  return papers.value.filter(paper => {
    const matchesSearch = paper.title.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      paper.authors.some(auth => auth.toLowerCase().includes(searchQuery.value.toLowerCase()));
    return matchesSearch;
  });
});

function handleLogout() {
  authStore.clearAuth();
  router.push('/login');
}

function createFolder() {
  const name = prompt('请输入新文件夹名称:');
  if (name) {
    folders.value.push({
      id: Date.now(),
      name: name,
    });
  }
}

function handleDrop(e: DragEvent) {
  isDragging.value = false;
  const files = e.dataTransfer?.files;
  if (files) {
    uploadFiles(files);
  }
}

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement;
  if (target.files) {
    uploadFiles(target.files);
  }
}

function uploadFiles(files: FileList) {
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    papers.value.push({
      id: Date.now() + i,
      title: file.name.replace('.pdf', ''),
      authors: ['待解析'],
      year: undefined,
      status: 'pending',
      created_at: new Date().toISOString().replace('T', ' ').substring(0, 19),
    });
  }
}

function deletePaper(id: number) {
  if (confirm('确认删除此文献吗？其对应的向量与解析内容均将被彻底清理。')) {
    papers.value = papers.value.filter(p => p.id !== id);
  }
}

function openPaper(paper: any) {
  router.push({ path: '/chat', query: { paperId: paper.id } });
}
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background-color: #f7f9f8;
  font-family: 'Inter', sans-serif;
  color: #1a3322;
}

/* Sidebar */
.sidebar {
  width: 260px;
  background-color: #0f3d24;
  color: #ffffff;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 30px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sidebar-header h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  background: linear-gradient(135deg, #a2f26d 0%, #ffffff 100%);
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
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
  font-weight: 600;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.nav-item:hover, .nav-item.active {
  color: #ffffff;
  background-color: rgba(255, 255, 255, 0.12);
}

.sidebar-footer {
  padding: 24px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.logout-btn {
  width: 100%;
  padding: 10px;
  background-color: transparent;
  color: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.logout-btn:hover {
  color: #ffffff;
  border-color: #ffffff;
  background-color: rgba(255, 255, 255, 0.05);
}

/* Main Content */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow-y: auto;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 40px;
  background-color: #ffffff;
  border-bottom: 1px solid #e1e6e3;
}

.content-header h1 {
  font-size: 24px;
  font-weight: 700;
  margin: 0;
  color: #0f3d24;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
}

.content-body {
  padding: 40px;
  display: flex;
  flex-direction: column;
  gap: 30px;
}

/* Control Panel */
.control-panel {
  display: flex;
  gap: 30px;
}

.folders-section {
  flex: 1;
  background: #ffffff;
  padding: 20px;
  border-radius: 12px;
  border: 1px solid #e1e6e3;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}

.section-title h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f3d24;
}

.add-folder-btn {
  background: none;
  border: none;
  color: #1c7243;
  font-weight: 600;
  cursor: pointer;
}

.folder-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.folder-list li {
  padding: 10px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.3s ease;
  font-weight: 500;
}

.folder-list li:hover {
  background-color: #f0f4f1;
}

.folder-list li.active {
  background-color: #e3ece6;
  color: #0f3d24;
  font-weight: 600;
}

.upload-section {
  flex: 2;
  background: #ffffff;
  border: 2px dashed #b8c7be;
  border-radius: 12px;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.upload-section.dragging, .upload-section:hover {
  border-color: #1c7243;
  background-color: #f0f7f3;
}

.upload-box {
  text-align: center;
}

.upload-icon {
  font-size: 32px;
  display: block;
  margin-bottom: 10px;
}

.upload-box p {
  margin: 0 0 5px 0;
  font-weight: 600;
}

.upload-sub {
  font-size: 12px;
  color: #667e6e;
}

/* Papers List */
.papers-section {
  background: #ffffff;
  padding: 24px;
  border-radius: 12px;
  border: 1px solid #e1e6e3;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.table-header h3 {
  margin: 0;
  font-size: 18px;
  color: #0f3d24;
}

.search-box input {
  padding: 8px 16px;
  border: 1px solid #c2cdc6;
  border-radius: 20px;
  outline: none;
  font-size: 14px;
  width: 250px;
  transition: all 0.3s ease;
}

.search-box input:focus {
  border-color: #1c7243;
  width: 300px;
}

.table-container {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

th {
  padding: 12px 16px;
  border-bottom: 2px solid #e1e6e3;
  color: #556c5c;
  font-weight: 600;
  font-size: 14px;
}

td {
  padding: 16px;
  border-bottom: 1px solid #f0f3f1;
  font-size: 14px;
}

.paper-title {
  font-weight: 600;
  color: #1c7243;
  cursor: pointer;
}

.paper-title:hover {
  text-decoration: underline;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.done {
  background-color: #d1f2d9;
  color: #0f6c2c;
}

.status-badge.parsing, .status-badge.indexing {
  background-color: #ffebd1;
  color: #b35900;
}

.status-badge.pending {
  background-color: #e2e8f0;
  color: #4a5568;
}

.status-badge.failed {
  background-color: #fed7d7;
  color: #9b2c2c;
}

.delete-btn {
  background: none;
  border: none;
  color: #c53030;
  cursor: pointer;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
}

.delete-btn:hover {
  background-color: #fff5f5;
}

.empty-row {
  text-align: center;
  color: #667e6e;
  padding: 30px;
}
</style>
