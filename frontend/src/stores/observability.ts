import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { observabilityApi, type IngestionTask, type QueryLog, type SystemStats } from '../api';

export const useObservabilityStore = defineStore('observability', () => {
  const ingestionTasks = ref<IngestionTask[]>([]);
  const queryLogs = ref<QueryLog[]>([]);
  const stats = ref<SystemStats | null>(null);
  const loading = ref(false);

  const totalQueries = computed(() => stats.value?.total_queries ?? queryLogs.value.length);
  const averageLatency = computed(() => stats.value?.average_latency_ms ?? 0);
  const successRate = computed(() => {
    if (!ingestionTasks.value.length) return 100;
    const failed = ingestionTasks.value.filter((task) => task.status === 'failed' || task.stage === 'failed').length;
    return Math.round(((ingestionTasks.value.length - failed) / ingestionTasks.value.length) * 100);
  });
  const paperCount = computed(() => stats.value?.paper_count ?? 0);
  const chunkCount = computed(() => stats.value?.chunk_count ?? 0);

  async function fetchIngestion() {
    ingestionTasks.value = await observabilityApi.ingestion();
  }

  async function fetchQueryLogs() {
    queryLogs.value = await observabilityApi.logs();
  }

  async function fetchStats() {
    try {
      stats.value = await observabilityApi.stats();
    } catch { /* stats not critical */ }
  }

  async function refreshAll() {
    loading.value = true;
    try {
      await Promise.all([fetchIngestion(), fetchQueryLogs(), fetchStats()]);
    } finally {
      loading.value = false;
    }
  }

  return {
    ingestionTasks,
    queryLogs,
    stats,
    loading,
    totalQueries,
    averageLatency,
    successRate,
    paperCount,
    chunkCount,
    fetchIngestion,
    fetchQueryLogs,
    fetchStats,
    refreshAll,
  };
});
