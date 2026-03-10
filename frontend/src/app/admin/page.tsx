'use client'
import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import { usersApi } from '@/lib/api'
import toast from 'react-hot-toast'

/* ─── Types ─────────────────────────────────────────────── */
type UserEntry = {
  id: string; email: string; full_name: string; role: string
  is_active: boolean; allowed_depts: string[]; created_at: string; last_login: string | null
}
type Tab = 'users' | 'create' | 'audit'

/* ─── Constants ─────────────────────────────────────────── */
const ALL_DEPTS = [
  { id: 'financial', label: 'المالية',         icon: '💰', color: '#3b82f6' },
  { id: 'hr',        label: 'الموارد البشرية', icon: '👥', color: '#10b981' },
  { id: 'legal',     label: 'القانوني',         icon: '⚖️', color: '#8b5cf6' },
  { id: 'technical', label: 'التقني',           icon: '⚙️', color: '#f59e0b' },
  { id: 'sales',     label: 'المبيعات',         icon: '📈', color: '#ec4899' },
  { id: 'admin',     label: 'الإداري',          icon: '📋', color: '#6b7280' },
  { id: 'general',   label: 'عام',              icon: '📄', color: '#4b5563' },
]

const ROLES = [
  { id: 'viewer',      label: 'مشاهد',          icon: '👁',  color: '#6b7280', desc: 'قراءة فقط · general' },
  { id: 'analyst',     label: 'محلل',            icon: '🔍',  color: '#3b82f6', desc: 'تحليل وقراءة' },
  { id: 'hr_analyst',  label: 'محلل HR',         icon: '👥',  color: '#10b981', desc: 'HR + admin + general' },
  { id: 'admin',       label: 'مدير',            icon: '⚡',  color: '#f59e0b', desc: 'إدارة كاملة + جميع الأقسام' },
  { id: 'super_admin', label: 'مدير عام',        icon: '👑',  color: '#8b5cf6', desc: 'صلاحيات غير محدودة' },
]

const ROLE_DEPTS: Record<string, string[]> = {
  viewer:      ['general'],
  analyst:     ['general'],
  hr_analyst:  ['hr', 'admin', 'general'],
  admin:       ['financial','hr','legal','technical','sales','admin','general'],
  super_admin: ['financial','hr','legal','technical','sales','admin','general'],
}

const ROLE_COLOR: Record<string, string> = {
  viewer: '#6b7280', analyst: '#3b82f6', hr_analyst: '#10b981',
  admin: '#f59e0b', super_admin: '#8b5cf6',
}

const DEPT_COLOR: Record<string, string> = {
  financial: '#3b82f6', hr: '#10b981', legal: '#8b5cf6',
  technical: '#f59e0b', sales: '#ec4899', admin: '#6b7280', general: '#4b5563',
}

/* ─── Helpers ───────────────────────────────────────────── */
const Spin = ({ s = 16, c = '#fff' }: { s?: number; c?: string }) => (
  <div style={{ width: s, height: s, border: `2px solid ${c}33`, borderTopColor: c, borderRadius: '50%', animation: 'spin 1s linear infinite', flexShrink: 0 }} />
)

const LockIcon = ({ size = 12, color = '#10b981' }: { size?: number; color?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    <rect x="3" y="11" width="18" height="11" rx="3"/>
    <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
    <circle cx="12" cy="16.5" r="1.2" fill={color} stroke="none"/>
  </svg>
)

/* ─── CSS ───────────────────────────────────────────────── */
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#060d1a}
body{font-family:'Tajawal',sans-serif;direction:rtl;color:#ccd9ef}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1e3a5f;border-radius:4px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
@keyframes slideIn{from{opacity:0;transform:translateX(12px)}to{opacity:1;transform:translateX(0)}}
@keyframes lockGlow{0%,100%{filter:drop-shadow(0 0 2px rgba(16,185,129,0))}60%{filter:drop-shadow(0 0 7px rgba(16,185,129,.65))}}
@keyframes pulse{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:1;transform:scale(1.3)}}
.card{background:#0c1829;border:1px solid rgba(59,130,246,.12);border-radius:16px;transition:border-color .22s,box-shadow .22s}
.card-hover:hover{border-color:rgba(59,130,246,.28);box-shadow:0 10px 36px rgba(0,0,0,.4)}
.tab{padding:10px 20px;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;border:1px solid transparent;transition:all .2s;display:flex;align-items:center;gap:8px;user-select:none}
.tab:hover:not(.tab-active){background:rgba(59,130,246,.06);color:#8eaed4}
.tab-active{background:rgba(59,130,246,.14);border-color:rgba(59,130,246,.3);color:#e2ecff}
.table-row{border-bottom:1px solid rgba(59,130,246,.06);transition:background .15s}
.table-row:hover td{background:rgba(59,130,246,.04)}
.input-field{width:100%;background:rgba(6,13,26,.9);border:1.5px solid rgba(59,130,246,.15);border-radius:11px;padding:11px 14px;color:#ccd9ef;font-size:13px;outline:none;font-family:'Tajawal',sans-serif;transition:border-color .2s,box-shadow .2s;direction:rtl}
.input-field:focus{border-color:rgba(59,130,246,.5);box-shadow:0 0 0 3px rgba(59,130,246,.07)}
.input-field::placeholder{color:#2a4a6e}
.btn{cursor:pointer;font-family:'Tajawal',sans-serif;border:none;transition:all .18s}
.btn:hover{opacity:.85;transform:translateY(-1px)}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important}
.dept-chip{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;transition:all .18s;user-select:none}
.dept-chip:hover{opacity:.8}
.role-card{padding:12px 16px;border-radius:11px;border:1.5px solid transparent;cursor:pointer;transition:all .2s;user-select:none}
.role-card:hover{transform:translateY(-1px)}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(8px);z-index:100;display:flex;align-items:center;justify-content:center;animation:fadeUp .2s both}
.modal{background:#0c1829;border:1px solid rgba(59,130,246,.25);border-radius:18px;width:520px;max-height:90vh;overflow-y:auto;animation:fadeUp .25s both;box-shadow:0 24px 80px rgba(0,0,0,.7)}
.field-label{font-size:11px;color:#5b7fa6;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px;display:flex;align-items:center;gap:6px}
.fu{animation:fadeUp .45s cubic-bezier(.22,.68,0,1.2) both}
`

/* ══ MAIN COMPONENT ══════════════════════════════════════════ */
export default function AdminPage() {
  const { user, isAdmin } = useAuthStore()
  const router = useRouter()

  const [activeTab, setActiveTab] = useState<Tab>('users')
  const [users, setUsers]         = useState<UserEntry[]>([])
  const [loading, setLoading]     = useState(false)
  const [editUser, setEditUser]   = useState<UserEntry | null>(null)
  const [showEdit, setShowEdit]   = useState(false)

  /* Guard */
  useEffect(() => {
    if (!localStorage.getItem('access_token')) { router.push('/login'); return }
    if (user && !isAdmin()) { toast.error('صلاحيات غير كافية'); router.push('/dashboard') }
  }, [user, isAdmin, router])

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try { const { data } = await usersApi.list(); setUsers(data) }
    catch (e: any) { toast.error(e.response?.data?.detail || 'فشل تحميل المستخدمين') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { if (isAdmin()) loadUsers() }, [isAdmin, loadUsers])

  function openEdit(u: UserEntry) { setEditUser(u); setShowEdit(true) }

  if (!user || !isAdmin()) return null

  return (
    <div style={{ minHeight: '100vh', background: '#060d1a', direction: 'rtl', fontFamily: "'Tajawal',sans-serif" }}>
      <style>{CSS}</style>

      {/* BG */}
      <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', backgroundImage: 'linear-gradient(rgba(59,130,246,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,.02) 1px,transparent 1px)', backgroundSize: '52px 52px', zIndex: 0 }} />
      <div style={{ position: 'fixed', top: '-10%', right: '-5%', width: 500, height: 500, borderRadius: '50%', background: 'radial-gradient(circle,rgba(59,130,246,.07) 0%,transparent 65%)', pointerEvents: 'none', zIndex: 0 }} />

      {/* ── Header ── */}
      <header style={{ position: 'sticky', top: 0, zIndex: 50, background: 'rgba(6,13,26,.92)', backdropFilter: 'blur(20px)', borderBottom: '1px solid rgba(59,130,246,.1)', padding: '12px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button onClick={() => router.push('/dashboard')} style={{ background: 'none', border: '1px solid rgba(59,130,246,.18)', borderRadius: 9, padding: '6px 14px', color: '#5b7fa6', cursor: 'pointer', fontSize: 12, fontFamily: "'Tajawal'", display: 'flex', alignItems: 'center', gap: 7, transition: 'all .18s' }}
            onMouseOver={e => (e.currentTarget.style.borderColor = 'rgba(59,130,246,.4)')} onMouseOut={e => (e.currentTarget.style.borderColor = 'rgba(59,130,246,.18)')}>
            ← لوحة التحكم
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>👑</div>
            <div>
              <div style={{ fontWeight: 800, fontSize: 15, color: '#e2ecff' }}>لوحة تحكم المدير</div>
              <div style={{ fontSize: 10, color: '#3a5472', fontFamily: "'JetBrains Mono'" }}>IAM · RBAC · Department Control</div>
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 14px', background: 'rgba(16,185,129,.08)', border: '1px solid rgba(16,185,129,.2)', borderRadius: 20, fontSize: 10, color: '#10b981' }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', animation: 'pulse 2s ease-in-out infinite' }} />
            {users.length} مستخدم مسجّل
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', background: 'rgba(59,130,246,.06)', border: '1px solid rgba(59,130,246,.18)', borderRadius: 20, fontSize: 10, color: '#5b7fa6' }}>
            <LockIcon size={9} />
            <span style={{ fontFamily: "'JetBrains Mono'", letterSpacing: '.04em' }}>RBAC ACTIVE</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 32, height: 32, borderRadius: 9, background: 'linear-gradient(135deg,#1e40af,#3b82f6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: '#fff' }}>
              {user.full_name?.[0] || 'م'}
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#ccd9ef' }}>{user.full_name}</div>
              <div style={{ fontSize: 10, color: '#3a5472' }}>{user.role === 'super_admin' ? 'مدير عام' : 'مدير'}</div>
            </div>
          </div>
        </div>
      </header>

      <div style={{ padding: '28px 32px', position: 'relative', zIndex: 1 }}>

        {/* ── Stat cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 26 }}>
          {[
            { icon: '👥', label: 'إجمالي المستخدمين', val: users.length, color: '#3b82f6' },
            { icon: '✅', label: 'حسابات نشطة', val: users.filter(u => u.is_active).length, color: '#10b981' },
            { icon: '🏢', label: 'الأقسام المُدارة', val: ALL_DEPTS.length, color: '#f59e0b' },
            { icon: '🔐', label: 'مستوى الأدوار', val: ROLES.length, color: '#8b5cf6' },
          ].map((s, i) => (
            <div key={i} className="card fu" style={{ padding: '20px 22px', position: 'relative', overflow: 'hidden', animationDelay: `${i * .07}s` }}>
              <div style={{ position: 'absolute', top: -25, right: -15, width: 80, height: 80, borderRadius: '50%', background: `radial-gradient(circle,${s.color}20 0%,transparent 70%)` }} />
              <div style={{ fontSize: 24, marginBottom: 8 }}>{s.icon}</div>
              <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 26, fontWeight: 600, color: s.color }}>{s.val}</div>
              <div style={{ fontSize: 11, color: '#3a5472', marginTop: 5 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* ── Tabs ── */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 22 }}>
          {[
            { id: 'users' as Tab, icon: '👥', label: 'إدارة المستخدمين' },
            { id: 'create' as Tab, icon: '➕', label: 'إضافة موظف' },
            { id: 'audit' as Tab, icon: '📋', label: 'سجل الأدوار' },
          ].map(t => (
            <div key={t.id} className={`tab ${activeTab === t.id ? 'tab-active' : ''}`} onClick={() => setActiveTab(t.id)}>
              <span>{t.icon}</span>{t.label}
            </div>
          ))}
        </div>

        {/* ── TAB VIEWS ── */}
        {activeTab === 'users' && (
          <UsersTab users={users} loading={loading} onReload={loadUsers} onEdit={openEdit} />
        )}
        {activeTab === 'create' && (
          <CreateUserTab onCreated={() => { loadUsers(); setActiveTab('users'); toast.success('تم إنشاء الحساب بنجاح') }} />
        )}
        {activeTab === 'audit' && (
          <AuditTab users={users} />
        )}
      </div>

      {/* ── Edit modal ── */}
      {showEdit && editUser && (
        <EditUserModal
          user={editUser}
          currentUserRole={user.role}
          onClose={() => { setShowEdit(false); setEditUser(null) }}
          onSaved={() => { loadUsers(); setShowEdit(false); setEditUser(null) }}
        />
      )}
    </div>
  )
}

/* ══ USERS TAB ═══════════════════════════════════════════════ */
function UsersTab({ users, loading, onReload, onEdit }: { users: UserEntry[]; loading: boolean; onReload: () => void; onEdit: (u: UserEntry) => void }) {
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')

  const filtered = users.filter(u => {
    const q = search.toLowerCase()
    const matchSearch = !q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    const matchRole   = roleFilter === 'all' || u.role === roleFilter
    return matchSearch && matchRole
  })

  async function handleDeactivate(id: string, name: string) {
    if (!confirm(`هل تريد تعطيل حساب "${name}"؟`)) return
    try { await usersApi.deactivate(id); toast.success('تم تعطيل الحساب'); onReload() }
    catch (e: any) { toast.error(e.response?.data?.detail || 'فشل العملية') }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Search + filter bar */}
      <div className="card" style={{ padding: '14px 20px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <input className="input-field" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="🔍 بحث بالاسم أو البريد الإلكتروني..." style={{ flex: 1 }} />
        <select className="input-field" value={roleFilter} onChange={e => setRoleFilter(e.target.value)} style={{ width: 160 }}>
          <option value="all">جميع الأدوار</option>
          {ROLES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <button className="btn" onClick={onReload} style={{ background: 'rgba(59,130,246,.08)', border: '1px solid rgba(59,130,246,.2)', borderRadius: 10, padding: '10px 16px', color: '#5b7fa6', fontSize: 13, display: 'flex', alignItems: 'center', gap: 7 }}>
          {loading ? <Spin s={14} c="#5b7fa6" /> : '↻'} تحديث
        </button>
      </div>

      {/* Table */}
      <div className="card fu" style={{ overflow: 'hidden', animationDelay: '.05s' }}>
        <div style={{ padding: '16px 22px', borderBottom: '1px solid rgba(59,130,246,.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontWeight: 800, fontSize: 14, color: '#ccd9ef' }}>قائمة المستخدمين ({filtered.length})</div>
          <div style={{ fontSize: 11, color: '#3a5472' }}>{users.filter(u => u.is_active).length} نشط · {users.filter(u => !u.is_active).length} معطّل</div>
        </div>
        {loading && !users.length
          ? <div style={{ padding: '40px', textAlign: 'center', display: 'flex', justifyContent: 'center' }}><Spin s={28} c="#3b82f6" /></div>
          : filtered.length === 0
            ? <div style={{ padding: '40px', textAlign: 'center', color: '#3a5472' }}>لا توجد نتائج</div>
            : <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['المستخدم', 'الدور', 'الأقسام المسموحة', 'الحالة', 'آخر دخول', 'إجراءات'].map(h => (
                      <th key={h} style={{ padding: '10px 18px', textAlign: 'right', fontSize: 10, color: '#2a4a6e', fontWeight: 700, borderBottom: '1px solid rgba(59,130,246,.1)', letterSpacing: '.06em', textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(u => (
                    <tr key={u.id} className="table-row" style={{ opacity: u.is_active ? 1 : .5 }}>
                      {/* User */}
                      <td style={{ padding: '13px 18px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div style={{ width: 36, height: 36, borderRadius: 10, background: `${ROLE_COLOR[u.role] || '#3b82f6'}22`, border: `1px solid ${ROLE_COLOR[u.role] || '#3b82f6'}44`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 15, color: ROLE_COLOR[u.role] || '#3b82f6', flexShrink: 0 }}>
                            {u.full_name?.[0] || '?'}
                          </div>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: '#ccd9ef' }}>{u.full_name}</div>
                            <div style={{ fontSize: 10, color: '#3a5472', fontFamily: "'JetBrains Mono'" }}>{u.email}</div>
                          </div>
                        </div>
                      </td>
                      {/* Role */}
                      <td style={{ padding: '13px 18px' }}>
                        <span style={{ padding: '4px 11px', borderRadius: 20, fontSize: 11, fontWeight: 700, background: `${ROLE_COLOR[u.role] || '#3b82f6'}18`, color: ROLE_COLOR[u.role] || '#3b82f6', border: `1px solid ${ROLE_COLOR[u.role] || '#3b82f6'}33`, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                          {ROLES.find(r => r.id === u.role)?.icon} {ROLES.find(r => r.id === u.role)?.label || u.role}
                        </span>
                      </td>
                      {/* Depts */}
                      <td style={{ padding: '13px 18px' }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {u.allowed_depts.slice(0, 4).map(d => {
                            const dept = ALL_DEPTS.find(x => x.id === d)
                            return (
                              <span key={d} style={{ padding: '2px 7px', borderRadius: 6, fontSize: 10, background: `${DEPT_COLOR[d] || '#3a5472'}18`, color: DEPT_COLOR[d] || '#3a5472', border: `1px solid ${DEPT_COLOR[d] || '#3a5472'}33` }}>
                                {dept?.icon} {dept?.label || d}
                              </span>
                            )
                          })}
                          {u.allowed_depts.length > 4 && (
                            <span style={{ padding: '2px 7px', borderRadius: 6, fontSize: 10, color: '#3a5472', background: 'rgba(59,130,246,.06)', border: '1px solid rgba(59,130,246,.12)' }}>+{u.allowed_depts.length - 4}</span>
                          )}
                        </div>
                      </td>
                      {/* Status */}
                      <td style={{ padding: '13px 18px' }}>
                        <span style={{ padding: '3px 10px', borderRadius: 20, fontSize: 10, fontWeight: 700, background: u.is_active ? 'rgba(16,185,129,.1)' : 'rgba(248,113,113,.1)', color: u.is_active ? '#10b981' : '#f87171', border: `1px solid ${u.is_active ? 'rgba(16,185,129,.25)' : 'rgba(248,113,113,.25)'}` }}>
                          {u.is_active ? '● نشط' : '○ معطّل'}
                        </span>
                      </td>
                      {/* Last login */}
                      <td style={{ padding: '13px 18px', fontSize: 10, color: '#3a5472', fontFamily: "'JetBrains Mono'" }}>
                        {u.last_login ? new Date(u.last_login).toLocaleDateString('ar-SA') : '—'}
                      </td>
                      {/* Actions */}
                      <td style={{ padding: '13px 18px' }}>
                        <div style={{ display: 'flex', gap: 7 }}>
                          <button onClick={() => onEdit(u)} className="btn" style={{ padding: '5px 11px', borderRadius: 8, background: 'rgba(59,130,246,.1)', border: '1px solid rgba(59,130,246,.2)', color: '#5b7fa6', fontSize: 11 }}>✏ تعديل</button>
                          {u.is_active && (
                            <button onClick={() => handleDeactivate(u.id, u.full_name)} className="btn" style={{ padding: '5px 11px', borderRadius: 8, background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.2)', color: '#f87171', fontSize: 11 }}>⊘ تعطيل</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
        }
      </div>
    </div>
  )
}

/* ══ CREATE USER TAB ═════════════════════════════════════════ */
function CreateUserTab({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({ email: '', full_name: '', password: '', role: 'analyst' })
  const [depts, setDepts] = useState<string[]>(['general'])
  const [loading, setLoading] = useState(false)
  const [showPw, setShowPw]   = useState(false)

  /* Auto-fill depts when role changes */
  function handleRoleChange(role: string) {
    setForm(f => ({ ...f, role }))
    setDepts(ROLE_DEPTS[role] || ['general'])
  }

  function toggleDept(d: string) {
    setDepts(prev => prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d])
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (depts.length === 0) { toast.error('اختر قسماً واحداً على الأقل'); return }
    setLoading(true)
    try {
      await usersApi.create({ ...form, allowed_depts: depts })
      onCreated()
      setForm({ email: '', full_name: '', password: '', role: 'analyst' })
      setDepts(['general'])
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'فشل إنشاء الحساب')
    } finally { setLoading(false) }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
      {/* Form */}
      <div className="card fu" style={{ padding: 28, animationDelay: '.05s' }}>
        <div style={{ fontWeight: 800, fontSize: 15, color: '#ccd9ef', marginBottom: 22 }}>معلومات الموظف الجديد</div>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {[
            { key: 'full_name', label: 'الاسم الكامل', type: 'text', placeholder: 'محمد العمري', icon: '👤' },
            { key: 'email',     label: 'البريد الإلكتروني', type: 'email', placeholder: 'user@company.com', icon: '✉' },
          ].map(f => (
            <div key={f.key} style={{ marginBottom: 16 }}>
              <div className="field-label"><span>{f.icon}</span>{f.label}</div>
              <input className="input-field" type={f.type} placeholder={f.placeholder} required
                value={(form as any)[f.key]}
                onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))} />
            </div>
          ))}

          {/* Password */}
          <div style={{ marginBottom: 16 }}>
            <div className="field-label"><span>🔑</span>كلمة المرور</div>
            <div style={{ position: 'relative' }}>
              <input className="input-field" type={showPw ? 'text' : 'password'} placeholder="8 أحرف على الأقل"
                required minLength={8} value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))} />
              <button type="button" onClick={() => setShowPw(p => !p)}
                style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#3a5472', cursor: 'pointer', fontSize: 13, fontFamily: "'Tajawal'" }}>
                {showPw ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          {/* Role selector */}
          <div style={{ marginBottom: 20 }}>
            <div className="field-label"><span>⚡</span>الدور الوظيفي</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {ROLES.filter(r => r.id !== 'super_admin').map(r => (
                <div key={r.id} className="role-card" onClick={() => handleRoleChange(r.id)}
                  style={{ background: form.role === r.id ? `${r.color}14` : 'rgba(6,13,26,.6)', borderColor: form.role === r.id ? `${r.color}55` : 'rgba(59,130,246,.1)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 18 }}>{r.icon}</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: form.role === r.id ? r.color : '#8eaed4' }}>{r.label}</div>
                      <div style={{ fontSize: 10, color: '#3a5472', marginTop: 1 }}>{r.desc}</div>
                    </div>
                    {form.role === r.id && <div style={{ marginRight: 'auto', width: 8, height: 8, borderRadius: '50%', background: r.color }} />}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button type="submit" disabled={loading || !form.email || !form.full_name || !form.password} className="btn"
            style={{ padding: '13px', borderRadius: 12, background: loading ? 'rgba(59,130,246,.3)' : 'linear-gradient(135deg,#1e40af,#3b82f6)', color: '#fff', fontSize: 14, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
            {loading && <Spin />}
            {loading ? 'جارٍ الإنشاء...' : '← إنشاء الحساب'}
          </button>
        </form>
      </div>

      {/* Department permissions */}
      <div className="card fu" style={{ padding: 28, animationDelay: '.1s' }}>
        <div style={{ fontWeight: 800, fontSize: 15, color: '#ccd9ef', marginBottom: 8 }}>الأقسام المسموح بالوصول إليها</div>
        <p style={{ fontSize: 12, color: '#3a5472', marginBottom: 20, lineHeight: 1.6 }}>
          حدد الأقسام التي يُسمح لهذا الموظف برؤيتها والتعامل معها. أي ملف يُرفع في قسم ما لن يظهر للموظف إلا إذا كان لديه صلاحية الوصول لذلك القسم.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {ALL_DEPTS.map(d => {
            const selected = depts.includes(d.id)
            return (
              <div key={d.id} onClick={() => toggleDept(d.id)}
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '11px 16px', borderRadius: 11, cursor: 'pointer', transition: 'all .18s', background: selected ? `${d.color}12` : 'rgba(6,13,26,.5)', border: `1.5px solid ${selected ? d.color + '44' : 'rgba(59,130,246,.08)'}`, userSelect: 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 20 }}>{d.icon}</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: selected ? d.color : '#8eaed4' }}>{d.label}</div>
                    <div style={{ fontSize: 10, color: '#3a5472', marginTop: 1, fontFamily: "'JetBrains Mono'" }}>{d.id}</div>
                  </div>
                </div>
                <div style={{ width: 20, height: 20, borderRadius: 6, border: `2px solid ${selected ? d.color : 'rgba(59,130,246,.2)'}`, background: selected ? d.color : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all .18s' }}>
                  {selected && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>}
                </div>
              </div>
            )
          })}
        </div>

        {/* Preview */}
        <div style={{ marginTop: 20, padding: '12px 16px', borderRadius: 10, background: 'rgba(59,130,246,.06)', border: '1px solid rgba(59,130,246,.15)' }}>
          <div style={{ fontSize: 10, color: '#3a5472', fontWeight: 700, letterSpacing: '.08em', marginBottom: 8 }}>PREVIEW — الصلاحيات الفعلية</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {depts.length === 0
              ? <span style={{ fontSize: 11, color: '#f87171' }}>⚠ لا توجد أقسام محددة</span>
              : depts.map(d => {
                  const dept = ALL_DEPTS.find(x => x.id === d)
                  return (
                    <span key={d} style={{ padding: '3px 9px', borderRadius: 7, fontSize: 11, background: `${dept?.color || '#3a5472'}18`, color: dept?.color || '#3a5472', border: `1px solid ${dept?.color || '#3a5472'}33` }}>
                      {dept?.icon} {dept?.label}
                    </span>
                  )
                })
            }
          </div>
        </div>
      </div>
    </div>
  )
}

/* ══ EDIT USER MODAL ═════════════════════════════════════════ */
function EditUserModal({ user, currentUserRole, onClose, onSaved }: { user: UserEntry; currentUserRole: string; onClose: () => void; onSaved: () => void }) {
  const [form, setForm]   = useState({ full_name: user.full_name, role: user.role, is_active: user.is_active })
  const [depts, setDepts] = useState<string[]>(user.allowed_depts)
  const [newPw, setNewPw] = useState('')
  const [saving, setSaving] = useState(false)
  const [tab, setTab]     = useState<'info' | 'depts' | 'password'>('info')

  function toggleDept(d: string) {
    setDepts(prev => prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d])
  }

  async function handleSave() {
    setSaving(true)
    try {
      await usersApi.update(user.id, { full_name: form.full_name, role: form.role, is_active: form.is_active, allowed_depts: depts })
      if (newPw.length >= 8) await usersApi.resetPw(user.id, newPw)
      toast.success('تم حفظ التغييرات')
      onSaved()
    } catch (e: any) { toast.error(e.response?.data?.detail || 'فشل الحفظ') }
    finally { setSaving(false) }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        {/* Modal header */}
        <div style={{ padding: '22px 28px 16px', borderBottom: '1px solid rgba(59,130,246,.1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 40, height: 40, borderRadius: 11, background: `${ROLE_COLOR[user.role] || '#3b82f6'}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700, color: ROLE_COLOR[user.role] || '#3b82f6' }}>
              {user.full_name?.[0] || '?'}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 800, color: '#e2ecff' }}>{user.full_name}</div>
              <div style={{ fontSize: 10, color: '#3a5472', fontFamily: "'JetBrains Mono'" }}>{user.email}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#3a5472', cursor: 'pointer', fontSize: 20, lineHeight: 1 }}>✕</button>
        </div>

        {/* Modal tabs */}
        <div style={{ display: 'flex', gap: 6, padding: '12px 28px', borderBottom: '1px solid rgba(59,130,246,.08)' }}>
          {[{ id: 'info', l: 'البيانات' }, { id: 'depts', l: 'الأقسام' }, { id: 'password', l: 'كلمة المرور' }].map(t => (
            <button key={t.id} onClick={() => setTab(t.id as any)} className="btn"
              style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 700, background: tab === t.id ? 'rgba(59,130,246,.14)' : 'none', border: `1px solid ${tab === t.id ? 'rgba(59,130,246,.3)' : 'transparent'}`, color: tab === t.id ? '#e2ecff' : '#5b7fa6' }}>
              {t.l}
            </button>
          ))}
        </div>

        <div style={{ padding: '22px 28px' }}>
          {tab === 'info' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <div className="field-label">الاسم الكامل</div>
                <input className="input-field" value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} />
              </div>
              <div>
                <div className="field-label">الدور الوظيفي</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                  {ROLES.filter(r => r.id !== 'super_admin' || currentUserRole === 'super_admin').map(r => (
                    <div key={r.id} className="role-card" onClick={() => { setForm(f => ({ ...f, role: r.id })); setDepts(ROLE_DEPTS[r.id] || ['general']) }}
                      style={{ background: form.role === r.id ? `${r.color}14` : 'rgba(6,13,26,.6)', borderColor: form.role === r.id ? `${r.color}55` : 'rgba(59,130,246,.1)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ fontSize: 16 }}>{r.icon}</span>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: form.role === r.id ? r.color : '#8eaed4' }}>{r.label}</div>
                          <div style={{ fontSize: 10, color: '#3a5472' }}>{r.desc}</div>
                        </div>
                        {form.role === r.id && <div style={{ marginRight: 'auto', width: 7, height: 7, borderRadius: '50%', background: r.color }} />}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderRadius: 10, background: 'rgba(248,113,113,.05)', border: '1px solid rgba(248,113,113,.15)', cursor: 'pointer' }} onClick={() => setForm(f => ({ ...f, is_active: !f.is_active }))}>
                <div style={{ width: 36, height: 20, borderRadius: 10, background: form.is_active ? '#10b981' : 'rgba(248,113,113,.4)', position: 'relative', transition: 'background .2s', flexShrink: 0 }}>
                  <div style={{ position: 'absolute', top: 2, right: form.is_active ? 18 : 2, width: 16, height: 16, borderRadius: '50%', background: '#fff', transition: 'right .2s', boxShadow: '0 1px 4px rgba(0,0,0,.4)' }} />
                </div>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: form.is_active ? '#10b981' : '#f87171' }}>{form.is_active ? 'الحساب نشط' : 'الحساب معطّل'}</div>
                  <div style={{ fontSize: 10, color: '#3a5472' }}>انقر للتبديل</div>
                </div>
              </div>
            </div>
          )}

          {tab === 'depts' && (
            <div>
              <p style={{ fontSize: 12, color: '#3a5472', marginBottom: 14, lineHeight: 1.6 }}>حدد الأقسام المسموح لهذا الموظف برؤيتها. ستنعكس التغييرات فوراً على ما يظهر له من تبويبات وملفات.</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {ALL_DEPTS.map(d => {
                  const selected = depts.includes(d.id)
                  return (
                    <div key={d.id} onClick={() => toggleDept(d.id)}
                      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 10, cursor: 'pointer', transition: 'all .18s', background: selected ? `${d.color}12` : 'rgba(6,13,26,.5)', border: `1.5px solid ${selected ? d.color + '44' : 'rgba(59,130,246,.08)'}` }}>
                      <span style={{ fontSize: 18 }}>{d.icon}</span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: selected ? d.color : '#5b7fa6' }}>{d.label}</div>
                        <div style={{ fontSize: 10, color: '#3a5472', fontFamily: "'JetBrains Mono'" }}>{d.id}</div>
                      </div>
                      <div style={{ width: 18, height: 18, borderRadius: 5, border: `2px solid ${selected ? d.color : 'rgba(59,130,246,.2)'}`, background: selected ? d.color : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all .18s' }}>
                        {selected && <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3.5"><polyline points="20 6 9 17 4 12"/></svg>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {tab === 'password' && (
            <div>
              <div className="field-label">كلمة مرور جديدة (اختياري)</div>
              <input className="input-field" type="password" placeholder="اتركه فارغاً لعدم التغيير" minLength={8}
                value={newPw} onChange={e => setNewPw(e.target.value)} />
              {newPw && newPw.length < 8 && (
                <div style={{ fontSize: 11, color: '#f87171', marginTop: 7 }}>⚠ يجب أن تكون 8 أحرف على الأقل</div>
              )}
              <div style={{ marginTop: 16, padding: '12px 16px', borderRadius: 10, background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.18)', fontSize: 11, color: '#f59e0b', lineHeight: 1.6 }}>
                ⚠ كلمة المرور الجديدة ستُرسل للموظف عبر البريد الإلكتروني (تأكد من إبلاغه مباشرة).
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 28px 24px', display: 'flex', gap: 10, justifyContent: 'flex-end', borderTop: '1px solid rgba(59,130,246,.08)' }}>
          <button className="btn" onClick={onClose} style={{ padding: '10px 20px', borderRadius: 10, background: 'none', border: '1px solid rgba(59,130,246,.18)', color: '#5b7fa6', fontSize: 13 }}>إلغاء</button>
          <button className="btn" onClick={handleSave} disabled={saving} style={{ padding: '10px 24px', borderRadius: 10, background: saving ? 'rgba(59,130,246,.3)' : 'linear-gradient(135deg,#1e40af,#3b82f6)', color: '#fff', fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
            {saving && <Spin s={14} />}
            {saving ? 'حفظ...' : '✓ حفظ التغييرات'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ══ AUDIT / ROLES TAB ═══════════════════════════════════════ */
function AuditTab({ users }: { users: UserEntry[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* Role distribution */}
      <div className="card fu" style={{ padding: 24, animationDelay: '.05s' }}>
        <div style={{ fontWeight: 800, fontSize: 14, color: '#ccd9ef', marginBottom: 18 }}>توزيع الأدوار الوظيفية</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12 }}>
          {ROLES.map(r => {
            const count = users.filter(u => u.role === r.id).length
            const pct = users.length ? Math.round(count / users.length * 100) : 0
            return (
              <div key={r.id} style={{ padding: '16px 18px', borderRadius: 12, background: `${r.color}0d`, border: `1px solid ${r.color}22`, textAlign: 'center' }}>
                <div style={{ fontSize: 28, marginBottom: 6 }}>{r.icon}</div>
                <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 24, fontWeight: 600, color: r.color }}>{count}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: r.color, opacity: .8, marginTop: 4 }}>{r.label}</div>
                <div style={{ fontSize: 10, color: '#3a5472', marginTop: 3 }}>{pct}%</div>
                <div style={{ marginTop: 8, height: 3, borderRadius: 2, background: 'rgba(59,130,246,.08)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: pct + '%', background: r.color, borderRadius: 2, transition: 'width .6s' }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Department access matrix */}
      <div className="card fu" style={{ padding: 24, animationDelay: '.1s', overflow: 'hidden' }}>
        <div style={{ fontWeight: 800, fontSize: 14, color: '#ccd9ef', marginBottom: 18 }}>
          مصفوفة الصلاحيات — من يرى ماذا؟
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
            <thead>
              <tr>
                <th style={{ padding: '8px 16px', textAlign: 'right', fontSize: 10, color: '#2a4a6e', fontWeight: 700, borderBottom: '1px solid rgba(59,130,246,.1)', width: 140 }}>القسم</th>
                {ROLES.map(r => (
                  <th key={r.id} style={{ padding: '8px 10px', textAlign: 'center', fontSize: 10, color: '#2a4a6e', fontWeight: 700, borderBottom: '1px solid rgba(59,130,246,.1)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
                      <span style={{ fontSize: 16 }}>{r.icon}</span>
                      <span style={{ color: r.color, whiteSpace: 'nowrap' }}>{r.label}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ALL_DEPTS.map(d => (
                <tr key={d.id} style={{ borderBottom: '1px solid rgba(59,130,246,.05)' }}>
                  <td style={{ padding: '10px 16px', fontSize: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 16 }}>{d.icon}</span>
                      <span style={{ fontWeight: 700, color: d.color }}>{d.label}</span>
                    </div>
                  </td>
                  {ROLES.map(r => {
                    const hasAccess = (ROLE_DEPTS[r.id] || []).includes(d.id)
                    return (
                      <td key={r.id} style={{ padding: '10px', textAlign: 'center' }}>
                        {hasAccess
                          ? <div style={{ width: 22, height: 22, borderRadius: 6, background: `${r.color}22`, border: `1px solid ${r.color}44`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto' }}>
                              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={r.color} strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                            </div>
                          : <div style={{ width: 22, height: 22, borderRadius: 6, background: 'rgba(248,113,113,.06)', border: '1px solid rgba(248,113,113,.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto' }}>
                              <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="rgba(248,113,113,.5)" strokeWidth="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                            </div>
                        }
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent users */}
      <div className="card fu" style={{ padding: 24, animationDelay: '.15s' }}>
        <div style={{ fontWeight: 800, fontSize: 14, color: '#ccd9ef', marginBottom: 16 }}>آخر الحسابات المُنشأة</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {[...users].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).slice(0, 5).map(u => (
            <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 4px', borderBottom: '1px solid rgba(59,130,246,.06)' }}>
              <div style={{ width: 34, height: 34, borderRadius: 9, background: `${ROLE_COLOR[u.role] || '#3b82f6'}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 14, color: ROLE_COLOR[u.role] || '#3b82f6', flexShrink: 0 }}>
                {u.full_name?.[0] || '?'}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#ccd9ef', display: 'flex', alignItems: 'center', gap: 8 }}>
                  {u.full_name}
                  <span style={{ padding: '1px 7px', borderRadius: 10, fontSize: 9, background: `${ROLE_COLOR[u.role]}18`, color: ROLE_COLOR[u.role], border: `1px solid ${ROLE_COLOR[u.role]}33` }}>
                    {ROLES.find(r => r.id === u.role)?.label || u.role}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: '#3a5472', marginTop: 1, fontFamily: "'JetBrains Mono'" }}>{u.email}</div>
              </div>
              <div style={{ fontSize: 10, color: '#2a4a6e', fontFamily: "'JetBrains Mono'", flexShrink: 0 }}>
                {new Date(u.created_at).toLocaleDateString('ar-SA')}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
