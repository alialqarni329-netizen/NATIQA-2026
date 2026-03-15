import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi, usersApi } from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────
export interface User {
  id: string
  email: string
  full_name: string
  role: string
  totp_enabled: boolean
  allowed_depts: string[]
}
export interface Permissions {
  role: string
  allowed_depts: string[]
  can_upload: boolean
  can_delete: boolean
  can_admin: boolean
  see_all_depts: boolean
}
interface AuthState {
  user: User | null
  permissions: Permissions | null
  isLoading: boolean
  login: (email: string, password: string, totp?: string) => Promise<{ require_2fa?: boolean }>
  logout: () => Promise<void>
  fetchMe: () => Promise<void>
  fetchPerms: () => Promise<void>
  isAdmin: () => boolean
  isOrgAdmin: () => boolean
  canAccessDept: (dept: string) => boolean
}

// ─── Default permissions (fallback before API responds) ────────────────
const DEFAULT_PERMS: Permissions = {
  role: 'viewer',
  allowed_depts: ['general'],
  can_upload: false,
  can_delete: false,
  can_admin: false,
  see_all_depts: false,
}

// ─── Super admin permissions (full access) ────────────────────────────
const SUPER_ADMIN_PERMS: Permissions = {
  role: 'super_admin',
  allowed_depts: ['financial', 'hr', 'legal', 'technical', 'admin', 'general'],
  can_upload: true,
  can_delete: true,
  can_admin: true,
  see_all_depts: true,
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      permissions: null,
      isLoading: false,

      login: async (email, password, totp) => {
        set({ isLoading: true })
        try {
          const { data } = await authApi.login(email, password, totp)
          localStorage.setItem('access_token', data.access_token)
          localStorage.setItem('refresh_token', data.refresh_token)

          // ⚠️ DEV: حط permissions كاملة مباشرة للـ super_admin بدون API call
          // TODO: remove before going to production
          const role = data.user?.role
          const perms =
            role === 'super_admin' || role === 'admin'
              ? SUPER_ADMIN_PERMS
              : null

          set({ user: data.user, permissions: perms, isLoading: false })

          // جلب الصلاحيات من API فقط إذا مو super_admin
          if (!perms) get().fetchPerms()

          return {}
        } catch (err: any) {
          set({ isLoading: false })
          const detail = err.response?.data?.detail
          if (typeof detail === 'object' && detail.require_2fa)
            return { require_2fa: true }
          throw err
        }
      },

      logout: async () => {
        try { await authApi.logout() } catch { }
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null, permissions: null })
      },

      fetchMe: async () => {
        try {
          const { data } = await authApi.me()
          set({ user: data })
          get().fetchPerms()
        } catch {
          set({ user: null, permissions: null })
        }
      },

      fetchPerms: async () => {
        try {
          const { data } = await usersApi.myPerms()
          set({ permissions: data })
        } catch {
          set({ permissions: DEFAULT_PERMS })
        }
      },

      isAdmin: () => {
        const r = get().user?.role
        return r === 'admin' || r === 'super_admin'
      },
      isOrgAdmin: () => {
        const r = get().user?.role
        return r === 'org_admin' || r === 'admin' || r === 'super_admin'
      },
      canAccessDept: (dept: string) => {
        const perms = get().permissions
        if (!perms) return dept === 'general'
        if (perms.see_all_depts) return true
        return perms.allowed_depts.includes(dept)
      },
    }),
    {
      name: 'natiqa-auth',
      partialize: (state) => ({ user: state.user, permissions: state.permissions }),
    }
  )
)
