<template>
  <aside class="preview-panel">
    <header class="preview-header">
      <h2>引用溯源</h2>
      <p>点击回答中的角标或引用卡片查看原文证据</p>
    </header>

    <div v-if="citation" class="preview-body">
      <div class="meta-card">
        <span class="type-pill">{{ typeLabel }}</span>
        <h3>{{ citation.paper_title || `Paper ${citation.paper_id}` }}</h3>
        <p>第 {{ citation.page_num || '-' }} 页 · {{ citation.bbox || '无 bbox' }}</p>
      </div>

      <div class="content-card">
        <p v-if="citation.chunk_type === 'text'" class="text-block">{{ citation.content }}</p>
        <div v-else-if="citation.chunk_type === 'table'" class="table-block" v-html="safeHtml"></div>
        <div v-else-if="citation.chunk_type === 'figure'" class="figure-block">
          <img v-if="figureUrl" :src="figureUrl" :style="{ transform: `scale(${zoom})` }" alt="引用图像"
               @error="imageLoadError = true" />
          <div v-if="imageLoadError" class="empty-figure">图片暂不可用</div>
          <div v-else-if="props.citation?.image_key && !figureUrl" class="empty-figure">图片加载中...</div>
          <div v-else-if="!props.citation?.image_key" class="empty-figure">暂无图片</div>
          <p>{{ citation.content }}</p>
          <div class="zoom-actions">
            <button @click="zoom = Math.max(0.6, zoom - 0.2)">缩小</button>
            <button @click="zoom = Math.min(2.4, zoom + 0.2)">放大</button>
          </div>
        </div>
        <div v-else-if="citation.chunk_type === 'formula'" class="formula-block" v-html="formulaHtml"></div>
        <pre v-else class="text-block">{{ citation.content }}</pre>
      </div>
    </div>

    <div v-else class="preview-empty">
      <div class="empty-icon">⌖</div>
      <p>暂无选中的引用。回答生成后，点击 [1]、[2] 或底部引用卡片查看段落、表格、图片与公式。</p>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import DOMPurify from 'dompurify';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import type { Citation } from '../api';
import { paperApi } from '../api';

const props = defineProps<{ citation: Citation | null }>();
const zoom = ref(1);
const imageLoadError = ref(false);
const figureUrl = ref('');

watch(() => props.citation, async (citation) => {
  zoom.value = 1;
  imageLoadError.value = false;
  figureUrl.value = '';
  if (!citation?.image_key) return;
  try {
    figureUrl.value = await paperApi.figureUrl(citation.image_key);
  } catch {
    imageLoadError.value = true;
  }
}, { immediate: true });

const typeMap: Record<string, string> = { text: '文本段落', table: 'HTML 表格', figure: '论文图像', formula: '公式' };
const typeLabel = computed(() => props.citation ? (typeMap[props.citation.chunk_type] || props.citation.chunk_type) : '');
const safeHtml = computed(() => DOMPurify.sanitize(props.citation?.content || '', { USE_PROFILES: { html: true } }));
const formulaHtml = computed(() => {
  try {
    return katex.renderToString(props.citation?.content || '', { displayMode: true, throwOnError: false });
  } catch {
    return DOMPurify.sanitize(`<code>${props.citation?.content || ''}</code>`);
  }
});
</script>

<style scoped>
.preview-panel { width: 360px; border-left: 1px solid #dfe8e2; background: #fbfdf9; display: flex; flex-direction: column; }
.preview-header { padding: 22px; border-bottom: 1px solid #dfe8e2; }
.preview-header h2 { margin: 0 0 6px; color: #0f3d24; }
.preview-header p { margin: 0; color: #66806e; font-size: 13px; }
.preview-body { padding: 18px; overflow: auto; display: flex; flex-direction: column; gap: 16px; }
.meta-card, .content-card { background: #fff; border: 1px solid #e1e8e3; border-radius: 14px; padding: 16px; box-shadow: 0 8px 22px rgba(15,61,36,.05); }
.type-pill { display: inline-flex; padding: 4px 10px; border-radius: 999px; background: #e8f8e2; color: #0f7a3a; font-size: 12px; font-weight: 700; }
.meta-card h3 { margin: 10px 0 8px; font-size: 16px; color: #0f3d24; }
.meta-card p { margin: 0; color: #66806e; font-size: 12px; }
.text-block { white-space: pre-wrap; line-height: 1.7; color: #243b2c; }
.table-block :deep(table) { width: 100%; border-collapse: collapse; font-size: 12px; }
.table-block :deep(td), .table-block :deep(th) { border: 1px solid #d7e2da; padding: 8px; }
.figure-block { overflow: auto; text-align: center; }
.figure-block img { max-width: 100%; transform-origin: top center; transition: transform .2s ease; }
.figure-block p { text-align: left; color: #365442; line-height: 1.6; }
.zoom-actions { display: flex; gap: 8px; justify-content: center; }
.zoom-actions button { border: 1px solid #cfe0d3; background: #fff; border-radius: 8px; padding: 6px 10px; cursor: pointer; }
.formula-block { overflow-x: auto; }
.preview-empty { margin: auto; padding: 28px; text-align: center; color: #66806e; }
.empty-icon { font-size: 42px; color: #8fbd75; margin-bottom: 14px; }
.empty-figure { padding: 40px; border-radius: 12px; background: #f1f5f0; color: #66806e; }
</style>
