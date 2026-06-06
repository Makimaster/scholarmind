<template>
  <button
    class="citation-card"
    :class="{ active }"
    type="button"
    @click="$emit('select', citation)"
  >
    <span class="cite-index">[{{ index + 1 }}]</span>
    <span class="cite-main">
      <strong>{{ citation.paper_title || `Paper ${citation.paper_id}` }}</strong>
      <small>第 {{ citation.page_num || '-' }} 页 · {{ typeLabel }}</small>
      <span>{{ summary }}</span>
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { Citation } from '../api';

const props = defineProps<{
  citation: Citation;
  index: number;
  active?: boolean;
}>();

defineEmits<{ select: [citation: Citation] }>();

const typeMap: Record<string, string> = {
  text: '段落',
  table: '表格',
  figure: '图像',
  formula: '公式',
};

const typeLabel = computed(() => typeMap[props.citation.chunk_type] || props.citation.chunk_type || '片段');
const summary = computed(() => {
  const text = props.citation.content?.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || '无摘要';
  return text.length > 96 ? `${text.slice(0, 96)}…` : text;
});
</script>

<style scoped>
.citation-card {
  width: 100%;
  display: flex;
  gap: 10px;
  text-align: left;
  padding: 12px;
  border: 1px solid #dfe8e2;
  border-radius: 12px;
  background: #fbfdf9;
  color: #1a3322;
  cursor: pointer;
  transition: all .2s ease;
}
.citation-card:hover,
.citation-card.active {
  border-color: #6fcf7f;
  background: #f0faec;
  box-shadow: 0 8px 20px rgba(15, 61, 36, .08);
}
.cite-index {
  font-weight: 800;
  color: #0f7a3a;
  flex: 0 0 auto;
}
.cite-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cite-main strong {
  font-size: 13px;
  line-height: 1.35;
}
.cite-main small {
  color: #66806e;
  font-size: 12px;
}
.cite-main span {
  color: #365442;
  font-size: 12px;
  line-height: 1.45;
}
</style>
