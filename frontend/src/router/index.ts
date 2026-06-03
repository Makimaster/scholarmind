import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/library',
      name: 'Library',
      component: () => import('../views/Library.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('../views/Chat.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/observability',
      name: 'Observability',
      component: () => import('../views/Observability.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('../views/Settings.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/library',
    },
  ],
});

// Navigation guard
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore();
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next('/login');
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/library');
  } else {
    next();
  }
});

export default router;
