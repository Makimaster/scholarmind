import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { observabilityApi, type IngestionTask, type QueryLog } from '../api';

export const useObservabilityStore = defineStore('observability', () => {
  const ingestionTasks = ref<IngestionTask[]>([]);
  const queryLogs = ref<QueryLog[]>([]);
  const loading = ref(false);

  const totalQueries = computed(() => queryLogs.value.length);
  const averageLatency = computed(() => {
    if (!queryLogs.value.length) return 0;
    return Math.round(queryLogs.value.reduce((sum, log) => sum + (log.latency_ms || 0), 0) / queryLogs.value.length);
  });
  const averageTokens = computed(() => {
    if (!queryLogs.value.length) return 0;
    const total = queryLogs.value.reduce((sum, log) => sum + (log.prompt_tokens || 0) + (log.completion_tokens || 0), 0);
    return Math.round(total / queryLogs.value.length);
  });
  const successRate = computed(() => {
    if (!ingestionTasks.value.length) return 100;
    const failed = ingestionTasks.value.filter((task) => task.status === 'failed' || task.stage === 'failed').length;
    return Math.round(((ingestionTasks.value.length - failed) / ingestionTasks.value.length) * 100);
  });

  async function fetchIngestion() {
    ingestionTasks.value = await observabilityApi.ingestion();
  }

  async function fetchQueryLogs() {
    queryLogs.value = await observabilityApi.logs();
  }

  async function refreshAll() {
    loading.value = true;
    try {
      await Promise.all([fetchIngestion(), fetchQueryLogs()]);
    } finally {
      loading.value = false;
    }
  }

  return {
    ingestionTasks,
    queryLogs,
    loading,
    totalQueries,
    averageLatency,
    averageTokens,
    successRate,
    fetchIngestion,
    fetchQueryLogs,
    refreshAll,
  };
});
