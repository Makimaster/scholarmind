import api, { API_BASE_URL, apiUrl, authHeaders } from './request';

export interface LoginPayload { username: string; password: string }
export interface RegisterPayload { username: string; email: string; password: string }
export interface User { id: number; username: string; email: string; role: string; is_active?: boolean }
export interface TokenResponse { access_token: string; token_type: string }

export interface Citation {
  paper_id: number;
  paper_title: string;
  page_num: number;
  bbox: string;
  chunk_type: 'text' | 'table' | 'figure' | 'formula' | string;
  content: string;
  image_key?: string | null;
}

export interface ChatQueryPayload {
  conversation_id: number;
  question: string;
  scope_type?: 'all' | 'folder' | 'papers';
  folder_id?: number | null;
  paper_ids?: number[] | null;
}

export interface IngestionTask {
  id: number | string;
  paper_id?: number;
  title: string;
  file_name?: string;
  status: string;
  stage?: string;
  progress: number;
  error_msg?: string | null;
  started_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QueryLog {
  id: number;
  user_id?: number;
  question: string;
  rewritten_query?: string | null;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  retrieved_chunk_ids?: string[];
  feedback?: number | null;
  created_at: string;
}

export interface SystemStats {
  paper_count: number;
  chunk_count: number;
  total_queries: number;
  average_latency_ms: number;
}

export const authApi = {
  async login(payload: LoginPayload) {
    const { data } = await api.post<TokenResponse>('/auth/login', payload);
    return data;
  },
  async register(payload: RegisterPayload) {
    const { data } = await api.post<User>('/auth/register', payload);
    return data;
  },
  async me() {
    const { data } = await api.get<User>('/auth/me');
    return data;
  },
};

export const chatApi = {
  queryUrl() { return apiUrl('/chat/query'); },
  headers: authHeaders,
  async createConversation(payload: { title?: string; folder_id?: number | null; paper_ids?: number[] }) {
    const { data } = await api.post('/chat/conversations', payload);
    return data;
  },
  async listConversations() {
    const { data } = await api.get('/chat/conversations');
    return data;
  },
  async listMessages(conversationId: number) {
    const { data } = await api.get(`/chat/conversations/${conversationId}/messages`);
    return data;
  },
};

export const paperApi = {
  async upload(files: File[], folderId?: number | null) {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    if (folderId) formData.append('folder_id', String(folderId));
    const { data } = await api.post('/papers/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
  async list(params?: { folder_id?: number; status?: string }) {
    const { data } = await api.get('/papers', { params });
    return data;
  },
  async delete(id: number) {
    const { data } = await api.delete(`/papers/${id}`);
    return data;
  },
  async progress(batchId: number | string) {
    const { data } = await api.get(`/ingest/batches/${batchId}`);
    return data;
  },
};

export const foldersApi = {
  async list() {
    const { data } = await api.get('/folders');
    return data;
  },
  async create(payload: { name: string; parent_id?: number | null }) {
    const { data } = await api.post('/folders', payload);
    return data;
  },
  async delete(id: number) {
    const { data } = await api.delete(`/folders/${id}`);
    return data;
  },
};

export const settingsApi = {
  async save(payload: Record<string, unknown>) {
    return { ok: true, payload };
  },
};

export const reviewApi = {
  generateUrl() { return apiUrl('/review/generate'); },
  headers: authHeaders,
};

export const observabilityApi = {
  async ingestion() {
    const { data } = await api.get<IngestionTask[]>('/observability/ingestion');
    return data;
  },
  async logs() {
    const { data } = await api.get<QueryLog[]>('/observability/query-logs');
    return data;
  },
  async stats() {
    const { data } = await api.get<SystemStats>('/stats/overview');
    return data;
  },
};

export { api, API_BASE_URL, apiUrl, authHeaders };
export default api;
