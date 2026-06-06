import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import router from '../router';
import { authApi, type User } from '../api';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'));
  const user = ref<User | null>(null);
  const loading = ref(false);

  const isAuthenticated = computed(() => !!token.value);

  function setToken(newToken: string) {
    token.value = newToken;
    localStorage.setItem('token', newToken);
  }

  function clearAuth() {
    token.value = null;
    user.value = null;
    localStorage.removeItem('token');
  }

  async function bootstrap() {
    if (!token.value || user.value) return;
    try {
      user.value = await authApi.me();
    } catch {
      clearAuth();
    }
  }

  async function login(username: string, password: string) {
    loading.value = true;
    try {
      const data = await authApi.login({ username, password });
      setToken(data.access_token);
      user.value = await authApi.me();
    } finally {
      loading.value = false;
    }
  }

  async function register(username: string, email: string, password: string) {
    loading.value = true;
    try {
      await authApi.register({ username, email, password });
      await login(username, password);
    } finally {
      loading.value = false;
    }
  }

  function logout() {
    clearAuth();
    router.push('/login');
  }

  return {
    token,
    user,
    loading,
    isAuthenticated,
    setToken,
    clearAuth,
    bootstrap,
    login,
    register,
    logout,
  };
});
