/**
 * API Client — Axios with JWT auto-refresh
 */
import axios, { AxiosInstance, AxiosError } from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost/api'

// ─── Axios instance ───────────────────────────────────────────────────
const api: AxiosInstance = axios.create({
  baseURL: API_URL,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// ─── Request interceptor — attach token ───────────────────────────────
api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token')
    if (token) config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ─── Response interceptor — auto refresh ─────────────────────────────
let isRefreshing = false
let queue: Array<(token: string) => void> = []

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as any

    // تجاهل أخطاء الـ refresh endpoint نفسه لتجنب infinite loop
    if (original?.url?.includes('/auth/refresh')) {
      return Promise.reject(error)
    }

    if (error.response?.status === 401 && !original._retry) {
      if (isRefreshing) {
        return new Promise((resolve) => {
          queue.push((token) => {
            original.headers.Authorization = `Bearer ${token}`
            resolve(api(original))
          })
        })
      }
      original._retry = true
      isRefreshing = true
      try {
        const refresh = localStorage.getItem('refresh_token')
        if (!refresh) throw new Error('No refresh token')
        const { data } = await axios.post(`${API_URL}/auth/refresh`, { refresh_token: refresh })
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)
        queue.forEach((cb) => cb(data.access_token))
        queue = []
        original.headers.Authorization = `Bearer ${data.access_token}`
        return api(original)
      } catch {
        // احذف التوكنات فقط — بدون مسح كل localStorage
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        // أعد للـ login فقط إذا لم نكن هناك بالفعل
        if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
          window.location.href = '/login'
        }
      } finally {
        isRefreshing = false
      }
    }
    return Promise.reject(error)
  }
)

export default api

// ─── Auth ─────────────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string, totp_code?: string) =>
    api.post('/auth/login', { email, password, totp_code }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
  setup2fa: () => api.post('/auth/2fa/setup'),
  verify2fa: (code: string) => api.post('/auth/2fa/verify', null, { params: { code } }),
}

// ─── Projects ─────────────────────────────────────────────────────────
export const projectsApi = {
  list: () => api.get('/projects'),
  create: (data: { name: string; description?: string }) => api.post('/projects', data),
  update: (id: string, data: any) => api.patch(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
}

// ─── Documents ────────────────────────────────────────────────────────
export const docsApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/documents`),
  upload: (projectId: string, formData: FormData) =>
    api.post(`/projects/${projectId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  delete: (projectId: string, docId: string) =>
    api.delete(`/projects/${projectId}/documents/${docId}`),
}

// ─── Chat ─────────────────────────────────────────────────────────────
export const chatApi = {
  send: (projectId: string, message: string, conversationId?: string) =>
    api.post(`/projects/${projectId}/chat`, { message, conversation_id: conversationId }),
  listConversations: (projectId: string) =>
    api.get(`/projects/${projectId}/conversations`),
  getMessages: (conversationId: string) =>
    api.get(`/conversations/${conversationId}/messages`),
}

// ─── Dashboard ────────────────────────────────────────────────────────
export const dashApi = {
  stats: () => api.get('/dashboard/stats'),
}

// ─── Users / IAM ──────────────────────────────────────────────────────
export const usersApi = {
  list: () => api.get('/users'),
  myPerms: () => api.get('/users/me/perms'),
  get: (id: string) => api.get(`/users/${id}`),
  create: (body: {
    email: string; full_name: string; password: string
    role: string; allowed_depts?: string[]
  }) => api.post('/users', body),
  update: (id: string, body: {
    full_name?: string; is_active?: boolean
    role?: string; allowed_depts?: string[]
  }) => api.patch(`/users/${id}`, body),
  changeDepts: (id: string, depts: string[]) => api.patch(`/users/${id}/depts`, { allowed_depts: depts }),
  deactivate: (id: string) => api.delete(`/users/${id}`),
  resetPw: (id: string, password: string) => api.post(`/users/${id}/reset`, { new_password: password }),
}

// ─── ERP Integrations ─────────────────────────────────────────────────
export const erpApi = {
  connect: (body: {
    name: string; system: string; base_url: string; auth_type: string
    api_key?: string; username?: string; password?: string
    database?: string; client_id?: string; client_secret?: string; extra?: any
  }) => api.post('/erp/connect', body),
  listSystems: () => api.get('/erp/systems'),
  health: () => api.get('/erp/health'),
  fetch: (body: { system_name: string; data_type: string; params?: any }) =>
    api.post('/erp/fetch', body),
  action: (body: { system_name: string; action: string; params: any }) =>
    api.post('/erp/action', body),
  chat: (body: { question: string; project_id?: string; employee_id?: string }) =>
    api.post('/erp/chat', body),
  disconnect: (name: string) => api.delete(`/erp/${name}`),
}

// ─── Document Status Polling ──────────────────────────────────────────
export const docStatusApi = {
  check: (projectId: string, docId: string) =>
    api.get(`/projects/${projectId}/documents/${docId}/status`),
}

// ─── Notifications ────────────────────────────────────────────────────
export const notificationApi = {
  list: () => api.get('/notifications'),
  markRead: (id: string) => api.post(`/notifications/${id}/read`),
  markAllRead: () => api.post('/notifications/read-all'),
}

// ─── Auto-Organizer — in-chat file upload ─────────────────────────────
export const autoOrganizerApi = {
  uploadInChat: (file: File, conversationId?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    if (conversationId) fd.append('conversation_id', conversationId)
    return api.post('/chat/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
    })
  },
}

// ─── Admin Portal ─────────────────────────────────────────────────────
export const adminApi = {
  stats: () => api.get('/admin/stats'),
  listOrganizations: (limit = 50, offset = 0) =>
    api.get('/admin/organizations', { params: { limit, offset } }),
  listPending: () => api.get('/admin/pending'),
  approveUser: (userId: string) => api.post(`/admin/users/${userId}/approve`),
  rejectUser: (userId: string, reason: string) =>
    api.post(`/admin/users/${userId}/reject`, { reason }),
  // Exports
  exportWord: () => api.get('/admin/export/word', { responseType: 'blob' }),
  exportPptx: () => api.get('/admin/export/pptx', { responseType: 'blob' }),
  exportPowerBi: () => api.get('/admin/export/powerbi'),
}

// ─── Organization Management ──────────────────────────────────────────
export const orgApi = {
  invite: (email: string, role: string) => api.post('/org/invite', { email, role }),
  getTeam: () => api.get('/org/team'),
  getInvitation: (token: string) => api.get(`/org/invitations/${token}`),
  acceptInvitation: (data: { token: string; full_name: string; password: string }) =>
    api.post('/org/accept-invitation', data),
}
// ─── Analytics ────────────────────────────────────────────────────────
export const analyticsApi = {
  getSummary: (days: number = 30) => api.get(`/analytics/summary?days=${days}`),
}
