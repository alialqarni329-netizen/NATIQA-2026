'use client'
import { useEffect, useState, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import { dashApi, projectsApi, docsApi, chatApi, docStatusApi, autoOrganizerApi, orgApi } from '@/lib/api'
import toast from 'react-hot-toast'
import NotificationBell from '@/components/NotificationBell'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import DashboardAnalytics from './DashboardAnalytics'

type Project = { id: string; name: string; description?: string; status: 'active' | 'paused' | 'done' | 'archived' | 'processing'; doc_count: number; created_at: string }
type Doc = { id: string; file_name: string; department: string; status: string; chunks_count: number; file_size: number; is_encrypted: boolean; created_at: string }
type Msg = { id: string; role: string; content: string; sources?: any[]; created_at: string }

/* ─── All departments definition ──────────────────────────── */
const ALL_DEPT_DEFS = [
  { value: 'financial', label: 'المالية', icon: '💰', color: '#3b82f6' },
  { value: 'hr', label: 'الموارد البشرية', icon: '👥', color: '#10b981' },
  { value: 'legal', label: 'القانوني', icon: '⚖️', color: '#8b5cf6' },
  { value: 'technical', label: 'التقني', icon: '⚙️', color: '#f59e0b' },
  { value: 'sales', label: 'المبيعات', icon: '📈', color: '#ec4899' },
  { value: 'admin', label: 'الإداري', icon: '📋', color: '#6b7280' },
  { value: 'general', label: 'عام', icon: '📄', color: '#4b5563' },
]

const DEPTS = [
  { value: 'financial', label: 'مالي', icon: '💰' },
  { value: 'legal', label: 'قانوني', icon: '⚖️' },
  { value: 'hr', label: 'موارد بشرية', icon: '👥' },
  { value: 'technical', label: 'تقني', icon: '⚙️' },
  { value: 'admin', label: 'إداري', icon: '📋' },
  { value: 'general', label: 'عام', icon: '📄' },
]
const DEPT_COLOR: Record<string, string> = { financial: '#3b82f6', legal: '#8b5cf6', hr: '#10b981', technical: '#f59e0b', admin: '#6b7280', general: '#4b5563' }
const CARD_COLS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6']

/* ─── Quick Actions per file type ─────────────────────── */
const FILE_ACTIONS: Record<string, { label: string; icon: string; query: string }[]> = {
  xlsx: [
    { icon: '📊', label: 'تحليل الأرقام', query: 'حلّل البيانات الرقمية وأبرز أهم الأرقام' },
    { icon: '∑', label: 'الإجماليات', query: 'ما إجماليات كل عمود؟' },
    { icon: '⇄', label: 'مقارنة الأعمدة', query: 'قارن بين الأعمدة وأبرز الفروقات' },
    { icon: '📋', label: 'تقرير تنفيذي', query: 'اكتب تقريراً تنفيذياً عن هذه البيانات' },
  ],
  csv: [
    { icon: '📊', label: 'تحليل الأرقام', query: 'حلّل البيانات الرقمية وأبرز أهم الأرقام' },
    { icon: '∑', label: 'الإجماليات', query: 'ما إجماليات كل عمود؟' },
    { icon: '⚠', label: 'الشذوذات', query: 'هل توجد قيم شاذة أو غير طبيعية؟' },
    { icon: '📋', label: 'تقرير تنفيذي', query: 'اكتب تقريراً تنفيذياً عن هذه البيانات' },
  ],
  pdf: [
    { icon: '📄', label: 'ملخص تنفيذي', query: 'اعطني ملخصاً تنفيذياً لهذا الملف' },
    { icon: '✦', label: 'أبرز النقاط', query: 'ما أبرز النقاط في هذا المستند؟' },
    { icon: '💡', label: 'التوصيات', query: 'ما التوصيات الواردة؟' },
    { icon: '✅', label: 'الإجراءات', query: 'ما الإجراءات المطلوبة من هذا المستند؟' },
  ],
  docx: [
    { icon: '📄', label: 'ملخص تنفيذي', query: 'اعطني ملخصاً تنفيذياً' },
    { icon: '✦', label: 'أبرز النقاط', query: 'ما أبرز النقاط في هذا المستند؟' },
    { icon: '💡', label: 'التوصيات', query: 'ما التوصيات الواردة؟' },
    { icon: '🔑', label: 'الكلمات المفتاحية', query: 'ما الكلمات والمفاهيم المفتاحية؟' },
  ],
  pptx: [
    { icon: '🖼', label: 'ملخص الشرائح', query: 'لخّص محتوى كل شريحة بنقطة واحدة' },
    { icon: '💬', label: 'الرسائل الرئيسية', query: 'ما الرسائل الرئيسية في هذا العرض؟' },
    { icon: '📊', label: 'الأرقام والبيانات', query: 'استخرج كل الأرقام والإحصائيات الواردة' },
  ],
  default: [
    { icon: '🔍', label: 'تحليل شامل', query: 'حلّل هذا الملف وأبرز أهم محتوياته' },
    { icon: '📄', label: 'ملخص تنفيذي', query: 'اعطني ملخصاً تنفيذياً مختصراً' },
    { icon: '✦', label: 'أبرز النقاط', query: 'ما أبرز النقاط والمعلومات؟' },
    { icon: '💡', label: 'التوصيات', query: 'ما التوصيات المستخلصة؟' },
  ],
}
const getExt = (name: string) => name.split('.').pop()?.toLowerCase() || 'default'
const getActs = (docs: Doc[]) => { if (!docs.length) return FILE_ACTIONS.default; const e = getExt(docs[docs.length - 1].file_name); return FILE_ACTIONS[e] || FILE_ACTIONS.default }

/* ─── Content-type detector ───────────────────────────── */
function detectType(text: string): 'table' | 'report' | 'plain' {
  const lines = text.split('\n')
  const tableLine = lines.filter(l => l.includes('|'))
  if (tableLine.length > 2 && text.includes('|')) return 'table'
  if (text.length > 800 && (/^#+\s/m.test(text) || /\*\*[^*]+\*\*/g.test(text))) return 'report'
  return 'plain'
}

/* ─── Lock SVG ────────────────────────────────────────── */
const Lock = ({ size = 14, color = '#10b981', animated = false }: { size?: number; color?: string; animated?: boolean }) => (
  <svg className={animated ? 'lock-anim' : ''} width={size} height={size} viewBox="0 0 24 24"
    fill="none" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    <rect x="3" y="11" width="18" height="11" rx="3" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    <circle cx="12" cy="16.5" r="1.2" fill={color} stroke="none" />
  </svg>
)

/* ─── Report Card ─────────────────────────────────────── */
function ReportCard({ content, type }: { content: string; type: 'table' | 'report' | 'plain' }) {
  const [collapsed, setCollapsed] = useState(false)
  if (type === 'plain') return <div className="prose-ar"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>
  const badge = type === 'table' ? { label: '📊 جدول', color: '#3b82f6' } : { label: '📋 تقرير', color: '#10b981' }

  function exportTxt() {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
    a.download = `natiqa-${Date.now()}.txt`; a.click(); toast.success('تم التصدير')
  }
  return (
    <div style={{ background: 'rgba(8,16,32,.92)', border: '1px solid rgba(59,130,246,.22)', borderRadius: 14, overflow: 'hidden', margin: '.2em 0' }}>
      {/* header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 16px', background: 'rgba(59,130,246,.07)', borderBottom: '1px solid rgba(59,130,246,.14)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ padding: '2px 9px', borderRadius: 20, fontSize: 10, fontWeight: 700, background: `${badge.color}18`, color: badge.color, border: `1px solid ${badge.color}33` }}>{badge.label}</span>
          <span style={{ fontSize: 10, color: '#2a4a6e', fontFamily: "'JetBrains Mono'" }}>{content.length > 1000 ? `${(content.length / 1000).toFixed(1)}k` : content.length} حرف</span>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {[{ l: '↓ تصدير', fn: exportTxt }, { l: collapsed ? '↕ توسيع' : '↕ طي', fn: () => setCollapsed(c => !c) }].map(({ l, fn }) => (
            <button key={l} onClick={fn} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 9px', background: 'rgba(59,130,246,.09)', border: '1px solid rgba(59,130,246,.18)', borderRadius: 7, fontSize: 10, color: '#5b7fa6', cursor: 'pointer', fontFamily: "'Tajawal',sans-serif", transition: 'all .15s' }}
              onMouseOver={e => (e.currentTarget.style.color = '#8eaed4')} onMouseOut={e => (e.currentTarget.style.color = '#5b7fa6')}>{l}</button>
          ))}
        </div>
      </div>
      {/* body */}
      {!collapsed
        ? <div style={{ padding: 16 }}><div className="prose-ar"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div></div>
        : <div style={{ padding: '9px 16px', color: '#2a4a6e', fontSize: 11, fontStyle: 'italic' }}>{content.slice(0, 110).replace(/[#*|]/g, '').trim()}…</div>
      }
    </div>
  )
}

/* ─── Spin ────────────────────────────────────────────── */
const Spin = ({ s = 18, c = '#fff' }: { s?: number; c?: string }) => (
  <div style={{ width: s, height: s, border: `2px solid ${c}33`, borderTopColor: c, borderRadius: '50%', animation: 'spin 1s linear infinite', flexShrink: 0 }} />
)

/* ─── CSS ─────────────────────────────────────────────── */
const CSS = `
*{box-sizing:border-box;margin:0;padding:0}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1e3a5f;border-radius:4px}
.card{background:#0c1829;border:1px solid rgba(59,130,246,.12);border-radius:16px;transition:border-color .2s,transform .22s,box-shadow .22s}
.card:hover{border-color:rgba(59,130,246,.3);transform:translateY(-2px);box-shadow:0 14px 40px rgba(0,0,0,.45)}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 13px;border-radius:10px;cursor:pointer;font-size:13px;color:#5b7fa6;border:1px solid transparent;transition:all .18s}
.nav-item:hover{background:rgba(59,130,246,.08);color:#8eaed4}
.nav-item.active{background:rgba(59,130,246,.14);border-color:rgba(59,130,246,.28);color:#e2ecff;font-weight:700}
.proj-row{display:flex;align-items:center;gap:7px;padding:8px 10px;border-radius:9px;border:1px solid transparent;cursor:pointer;transition:all .18s;width:100%}
.proj-row:hover{background:rgba(59,130,246,.07);border-color:rgba(59,130,246,.18)}
.proj-row.active{background:rgba(59,130,246,.13);border-color:rgba(59,130,246,.32)}
.btn{cursor:pointer;border:none;font-family:'Tajawal',Arial,sans-serif;transition:all .18s}
.btn:hover{opacity:.85;transform:translateY(-1px)}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important}
.row-hover:hover{background:rgba(59,130,246,.04)}
.drop-zone{border:2px dashed rgba(59,130,246,.2);border-radius:12px;transition:all .22s;cursor:pointer}
.drop-zone.dragging{border-color:#3b82f6;background:rgba(59,130,246,.05)}
.drop-zone.has-file{border-color:#10b981;background:rgba(16,185,129,.05)}
.fu{animation:fadeUp .45s cubic-bezier(.22,.68,0,1.2) both}
.qa-btn{display:flex;align-items:center;gap:7px;padding:7px 13px;background:rgba(59,130,246,.07);border:1px solid rgba(59,130,246,.14);border-radius:9px;cursor:pointer;font-size:12px;color:#5b7fa6;white-space:nowrap;font-family:'Tajawal',sans-serif;transition:all .18s}
.qa-btn:hover{background:rgba(59,130,246,.14);border-color:rgba(59,130,246,.32);color:#8eaed4;transform:translateY(-1px)}
.plus-menu{position:absolute;bottom:calc(100% + 10px);right:0;background:#0c1829;border:1px solid rgba(59,130,246,.22);border-radius:14px;overflow:hidden;z-index:50;min-width:215px;box-shadow:0 18px 52px rgba(0,0,0,.65);animation:slideUp .2s cubic-bezier(.22,.68,0,1.1)}
.pm-item{display:flex;align-items:center;gap:10px;padding:11px 16px;font-size:13px;color:#8eaed4;cursor:pointer;transition:background .15s;font-family:'Tajawal',sans-serif;border-bottom:1px solid rgba(59,130,246,.07)}
.pm-item:last-child{border-bottom:none}
.pm-item:hover{background:rgba(59,130,246,.1)}
.pm-label{padding:7px 16px 5px;font-size:9px;color:#2a4a6e;letter-spacing:.16em;font-weight:700;text-transform:uppercase}
.prose-ar p{margin:.4em 0;line-height:1.9}
.prose-ar ul,.prose-ar ol{padding-right:1.3em;margin:.4em 0}
.prose-ar li{margin:.2em 0}
.prose-ar strong{color:#10b981}
.prose-ar code{background:rgba(59,130,246,.15);padding:1px 5px;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:.88em}
.prose-ar table{width:100%;border-collapse:collapse;margin:.6em 0;font-size:12px}
.prose-ar th{padding:8px 12px;background:rgba(59,130,246,.12);color:#8eaed4;font-weight:700;border:1px solid rgba(59,130,246,.18);text-align:right}
.prose-ar td{padding:8px 12px;border:1px solid rgba(59,130,246,.09);color:#ccd9ef;line-height:1.6}
.prose-ar tr:hover td{background:rgba(59,130,246,.04)}
.lock-anim{animation:lockGlow 3.5s ease-in-out infinite}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes slideUp{from{opacity:0;transform:translateY(8px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes dotBounce{0%,80%,100%{transform:scale(0);opacity:.3}40%{transform:scale(1);opacity:1}}
@keyframes pulse{0%,100%{opacity:.6;transform:scale(1)}50%{opacity:1;transform:scale(1.2)}}
@keyframes lockGlow{0%,100%{filter:drop-shadow(0 0 2px rgba(16,185,129,0))}60%{filter:drop-shadow(0 0 5px rgba(16,185,129,.55))}}
@keyframes qaIn{from{opacity:0;transform:translateX(8px)}to{opacity:1;transform:translateX(0)}}
`

/* ══════════════ DASHBOARD ════════════════════════════════ */
export default function Dashboard() {
  const { user, logout, permissions, isAdmin, isOrgAdmin, canAccessDept } = useAuthStore()
  const router = useRouter()
  const [view, setView] = useState('dash')
  const [proj, setProj] = useState<Project | null>(null)
  const [projs, setProjs] = useState<Project[]>([])
  const [clock, setClock] = useState(new Date())
  const [activeDept, setActiveDept] = useState<string | null>(null)

  useEffect(() => { if (!localStorage.getItem('access_token')) router.push('/login') }, [router])
  useEffect(() => { const t = setInterval(() => setClock(new Date()), 1000); return () => clearInterval(t) }, [])

  const loadProjects = useCallback(async () => {
    try { const { data } = await projectsApi.list(); setProjs(data); setProj(p => p ?? data[0] ?? null) } catch { }
  }, [])
  useEffect(() => { loadProjects() }, [loadProjects])

  /* Departments this user can see — filtered by RBAC */
  const visibleDepts = ALL_DEPT_DEFS.filter(d => canAccessDept(d.value))
  useEffect(() => {
    if (!activeDept && visibleDepts.length > 0) setActiveDept(visibleDepts[0].value)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permissions])

  const navItems = [
    { id: 'dash', icon: '▣', label: 'لوحة التحكم' },
    { id: 'chat', icon: '◉', label: 'المحادثة الذكية' },
    { id: 'know', icon: '◈', label: 'قاعدة المعرفة' },
    { id: 'projs', icon: '⊞', label: 'المشاريع' },
  ]
  if (isAdmin()) navItems.push({ id: 'admin', icon: '⚙️', label: 'إدارة النظام' })
  if (isOrgAdmin()) navItems.push({ id: 'analytics', icon: '📈', label: 'التحليلات المتقدمة' })
  if (isOrgAdmin() && !isAdmin()) navItems.push({ id: 'team', icon: '👥', label: 'إدارة الفريق' })

  const handleNav = (id: string) => {
    if (id === 'admin') router.push('/admin/dashboard')
    else setView(id)
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', fontFamily: "'Tajawal',Arial,sans-serif", direction: 'rtl', color: '#ccd9ef', background: '#060d1a' }}>
      <style>{CSS}</style>
      {/* BG grid */}
      <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0 }}>
        <div style={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(rgba(59,130,246,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,.022) 1px,transparent 1px)', backgroundSize: '48px 48px' }} />
        <div style={{ position: 'absolute', top: '-10%', left: '15%', width: 500, height: 500, borderRadius: '50%', background: 'radial-gradient(circle,rgba(59,130,246,.07) 0%,transparent 68%)' }} />
      </div>

      {/* ── SIDEBAR ── */}
      <aside style={{ width: 244, background: 'rgba(7,13,26,.97)', borderLeft: '1px solid rgba(59,130,246,.1)', display: 'flex', flexDirection: 'column', flexShrink: 0, position: 'relative', zIndex: 10 }}>
        <div style={{ padding: '20px 16px 16px', borderBottom: '1px solid rgba(59,130,246,.1)' }}>

          {/* Logo + Lock badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 16 }}>
            <div style={{ position: 'relative', flexShrink: 0 }}>
              <div style={{
                width: 44, height: 44, borderRadius: 13,
                background: '#060d1a',
                border: '1px solid rgba(59,130,246,.2)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: 7,
                boxShadow: '0 0 20px rgba(59,130,246,.15)'
              }}>
                <img
                  src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/static/logo.png`.replace('/api/static', '/static')}
                  alt="Logo"
                  style={{ width: '100%', height: '100%', objectFit: 'contain', filter: 'drop-shadow(0 0 4px rgba(59,130,246,.4))' }}
                />
              </div>
              {/* ① Lock badge on logo */}
              <div title="البيانات محمية — AES-256-GCM · Data Masking · Zero Trust"
                style={{ position: 'absolute', bottom: -4, left: -4, width: 17, height: 17, borderRadius: '50%', background: '#070f1e', border: '1.5px solid rgba(16,185,129,.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'help', zIndex: 2 }}>
                <Lock size={8} color="#10b981" animated />
              </div>
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                <span style={{ fontWeight: 900, fontSize: 19, letterSpacing: '.06em', color: '#e2ecff', lineHeight: 1 }}>ناطقة</span>
                {/* ① Tiny SECURE chip */}
                <div title="AES-256 · Masking · Zero Trust" style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '1px 6px', background: 'rgba(16,185,129,.07)', border: '1px solid rgba(16,185,129,.18)', borderRadius: 6, cursor: 'help' }}>
                  <Lock size={7} color="#10b981" animated />
                  <span style={{ fontSize: 8, color: 'rgba(16,185,129,.8)', fontWeight: 800, letterSpacing: '.06em' }}>SECURE</span>
                </div>
              </div>
              <div style={{ fontSize: 9, color: '#315581', letterSpacing: '.18em', marginTop: 2, fontWeight: 700 }}>OFFICIAL PLATFORM</div>
            </div>
          </div>

          {/* Clock */}
          <div style={{ background: 'rgba(59,130,246,.06)', border: '1px solid rgba(59,130,246,.12)', borderRadius: 10, padding: '9px 12px', textAlign: 'center' }}>
            <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 20, fontWeight: 600, color: '#3b82f6' }}>
              {clock.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </div>
            <div style={{ fontSize: 9, color: '#2a4a6e', marginTop: 2 }}>{clock.toLocaleDateString('ar-SA', { weekday: 'short', month: 'long', day: 'numeric' })}</div>
          </div>
        </div>

        <nav style={{ padding: '12px 10px', borderBottom: '1px solid rgba(59,130,246,.1)' }}>
          {navItems.map(n => (
            <div key={n.id} className={`nav-item ${view === n.id ? 'active' : ''}`} style={{ marginBottom: 3 }} onClick={() => handleNav(n.id)}>
              <span style={{ fontFamily: 'monospace', fontSize: 14, opacity: .8 }}>{n.icon}</span>{n.label}
            </div>
          ))}
        </nav>

        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 10px' }}>
          <div style={{ fontSize: 9, color: '#2a4a6e', letterSpacing: '.16em', padding: '0 4px 8px', fontWeight: 600 }}>المشاريع</div>
          {projs.map(p => (
            <div key={p.id} className={`proj-row ${proj?.id === p.id ? 'active' : ''}`} style={{ marginBottom: 3 }} onClick={() => { setProj(p); setView('chat') }}>
              {p.status === 'processing'
                ? <Spin s={10} c="#f59e0b" />
                : <div style={{ width: 6, height: 6, borderRadius: '50%', background: p.status === 'active' ? '#10b981' : '#2a4a6e', flexShrink: 0 }} />
              }
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: proj?.id === p.id ? '#ccd9ef' : '#5b7fa6', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</div>
                <div style={{ fontSize: 10, color: '#2a4a6e', marginTop: 1 }}>{p.status === 'processing' ? 'جاري التصنيف...' : `${p.doc_count} ملفات`}</div>
              </div>
            </div>
          ))}
        </div>

        {/* User + security footer */}
        <div style={{ padding: '12px', borderTop: '1px solid rgba(59,130,246,.1)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 10 }}>
            <div style={{ width: 34, height: 34, borderRadius: 10, background: 'linear-gradient(135deg,#1e40af,#3b82f6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, flexShrink: 0 }}>{user?.full_name?.[0] || 'م'}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#ccd9ef', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{user?.full_name}</div>
              <div style={{ fontSize: 10, color: '#2a4a6e' }}>{user?.role === 'super_admin' ? 'مدير عام' : user?.role}</div>
            </div>
            <button className="btn" onClick={async () => { await logout(); router.push('/login') }} style={{ background: 'none', fontSize: 11, padding: '4px 8px', borderRadius: 7, border: '1px solid rgba(248,113,113,.2)', color: '#f87171' }}>خروج</button>
          </div>
          {/* ① Security status footer */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', background: 'rgba(16,185,129,.06)', border: '1px solid rgba(16,185,129,.18)', borderRadius: 9 }}>
            <Lock size={13} color="#10b981" animated />
            <div style={{ fontSize: 10, color: '#10b981', lineHeight: 1.45 }}>
              <div style={{ fontWeight: 800 }}>البيانات محمية ومؤمنة</div>
              <div style={{ opacity: .6, fontSize: 9 }}>AES-256 · Data Masking نشط</div>
            </div>
          </div>
        </div>
      </aside>

      {/* ── MAIN ── */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative', zIndex: 1 }}>
        <header style={{ padding: '12px 24px', borderBottom: '1px solid rgba(59,130,246,.1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(6,13,26,.85)', backdropFilter: 'blur(20px)', flexShrink: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 15, color: '#ccd9ef' }}>
            {view === 'dash' ? 'لوحة التحكم' : view === 'chat' ? `محادثة — ${proj?.name || ''}` : view === 'know' ? 'قاعدة المعرفة' : view === 'analytics' ? 'التحليلات والبيانات' : 'إدارة المشاريع'}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 13px', background: 'rgba(16,185,129,.08)', border: '1px solid rgba(16,185,129,.2)', borderRadius: 20, fontSize: 10, color: '#10b981' }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', animation: 'pulse 2s ease-in-out infinite' }} />LLM متصل
            </div>
            <NotificationBell />
            {/* ① Lock chip in header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 11px', background: 'rgba(16,185,129,.06)', border: '1px solid rgba(16,185,129,.18)', borderRadius: 20, fontSize: 10, color: 'rgba(16,185,129,.8)' }}>
              <Lock size={10} color="#10b981" animated />
              <span style={{ fontFamily: "'JetBrains Mono'", letterSpacing: '.04em' }}>AES-256</span>
            </div>
            {/* Integrations link */}
            <button onClick={() => router.push('/integrations')}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 13px', background: 'rgba(14,165,233,.08)', border: '1px solid rgba(14,165,233,.25)', borderRadius: 20, fontSize: 10, color: '#38bdf8', cursor: 'pointer', fontFamily: "'Tajawal',sans-serif", transition: 'all .18s' }}
              onMouseOver={e => (e.currentTarget.style.background = 'rgba(14,165,233,.18)')}
              onMouseOut={e => (e.currentTarget.style.background = 'rgba(14,165,233,.08)')}>
              🔗 الأنظمة المربوطة
            </button>
            {/* Admin link — admin/super_admin only */}
            {isAdmin() && (
              <button onClick={() => router.push('/admin')}
                style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 13px', background: 'rgba(139,92,246,.08)', border: '1px solid rgba(139,92,246,.25)', borderRadius: 20, fontSize: 10, color: '#a78bfa', cursor: 'pointer', fontFamily: "'Tajawal',sans-serif", transition: 'all .18s' }}
                onMouseOver={e => (e.currentTarget.style.background = 'rgba(139,92,246,.18)')}
                onMouseOut={e => (e.currentTarget.style.background = 'rgba(139,92,246,.08)')}>
                👑 لوحة المدير
              </button>
            )}
          </div>
        </header>
        {/* ── Department Tabs Bar (RBAC-filtered) ── */}
        {(view === 'know' || view === 'chat') && visibleDepts.length > 0 && (
          <div style={{ borderBottom: '1px solid rgba(59,130,246,.1)', background: 'rgba(7,13,26,.8)', padding: '0 24px', display: 'flex', gap: 4, overflowX: 'auto', flexShrink: 0, scrollbarWidth: 'none' }}>
            {visibleDepts.map(d => (
              <button key={d.value} onClick={() => setActiveDept(d.value)}
                style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '11px 16px', fontSize: 12, fontWeight: activeDept === d.value ? 800 : 600, fontFamily: "'Tajawal',sans-serif", cursor: 'pointer', border: 'none', borderBottom: `2px solid ${activeDept === d.value ? d.color : 'transparent'}`, background: 'none', color: activeDept === d.value ? d.color : '#3a5472', whiteSpace: 'nowrap', transition: 'all .18s', flexShrink: 0 }}
                onMouseOver={e => { if (activeDept !== d.value) e.currentTarget.style.color = '#8eaed4' }}
                onMouseOut={e => { if (activeDept !== d.value) e.currentTarget.style.color = '#3a5472' }}>
                <span style={{ fontSize: 15 }}>{d.icon}</span>{d.label}
                {activeDept === d.value && <div style={{ width: 5, height: 5, borderRadius: '50%', background: d.color, marginRight: 2 }} />}
              </button>
            ))}
            {/* Admin sees dept count hint */}
            {isAdmin() && (
              <div style={{ marginRight: 'auto', display: 'flex', alignItems: 'center', padding: '0 8px', fontSize: 10, color: '#2a4a6e', fontFamily: "'JetBrains Mono'", flexShrink: 0 }}>
                {visibleDepts.length} قسم مرئي
              </div>
            )}
          </div>
        )}

        <div style={{ flex: 1, overflowY: 'auto', padding: 22 }}>
          {view === 'dash' && <DashView projs={projs} setView={setView} setProj={setProj} />}
          {view === 'analytics' && <DashboardAnalytics />}
          {view === 'chat' && <ChatView proj={proj} projs={projs} setProj={setProj} activeDept={activeDept} loadProjects={loadProjects} />}
          {view === 'know' && <KnowView proj={proj} projs={projs} setProj={setProj} activeDept={activeDept} />}
          {view === 'projs' && <ProjsView projs={projs} setProjs={setProjs} setProj={setProj} setView={setView} loadProjects={loadProjects} />}
          {view === 'team' && <TeamView />}
        </div>
      </main>
    </div>
  )
}

/* ══ DASH ══════════════════════════════════════════════════ */
function DashView({ projs, setView, setProj }: any) {
  const [stats, setStats] = useState<any>(null)
  useEffect(() => { dashApi.stats().then(r => setStats(r.data)).catch(() => { }) }, [])
  const active = projs.filter((p: any) => p.status === 'active').length
  const done = projs.filter((p: any) => p.status === 'done').length
  const pieData = [{ n: 'نشطة', v: active, c: '#3b82f6' }, { n: 'مكتملة', v: done, c: '#10b981' }]
  const cards = [
    { icon: '📁', label: 'المشاريع', value: stats?.projects ?? projs.length, color: '#3b82f6' },
    { icon: '📊', label: 'الاستعلامات', value: stats?.total_queries ?? 0, color: '#10b981' },
    { icon: '📄', label: 'الملفات المستوعبة', value: stats?.documents ?? 0, color: '#f59e0b' },
    { icon: '🧩', label: 'إجمالي الـ Chunks', value: stats?.total_chunks ?? 0, color: '#8b5cf6' },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14 }}>
        {cards.map((s, i) => (
          <div key={i} className="card fu" style={{ padding: '22px 24px', position: 'relative', overflow: 'hidden', animationDelay: `${i * .07}s` }}>
            <div style={{ position: 'absolute', top: -30, right: -20, width: 90, height: 90, borderRadius: '50%', background: `radial-gradient(circle,${s.color}22 0%,transparent 70%)` }} />
            <div style={{ fontSize: 26, marginBottom: 10 }}>{s.icon}</div>
            <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 28, fontWeight: 600, color: s.color }}>{Number(s.value).toLocaleString('ar-SA')}</div>
            <div style={{ fontSize: 12, color: '#3a5472', marginTop: 6 }}>{s.label}</div>
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14 }}>
        <div className="card fu" style={{ padding: 22, animationDelay: '.1s' }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 16 }}>المشاريع</div>
          {projs.length === 0
            ? <div style={{ textAlign: 'center', padding: '40px 0', color: '#3a5472' }}><div style={{ fontSize: 44, marginBottom: 12 }}>📁</div>أنشئ مشروعك الأول</div>
            : <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>{['المشروع', 'الملفات', 'الحالة', 'التاريخ'].map(h => <th key={h} style={{ padding: '7px 14px', textAlign: 'right', fontSize: 10, color: '#2a4a6e', fontWeight: 600, borderBottom: '1px solid rgba(59,130,246,.1)' }}>{h}</th>)}</tr></thead>
              <tbody>{projs.map((p: any) => (
                <tr key={p.id} className="row-hover" style={{ borderBottom: '1px solid rgba(59,130,246,.05)', cursor: 'pointer' }} onClick={() => { setProj(p); setView('chat') }}>
                  <td style={{ padding: '11px 14px', fontSize: 13, fontWeight: 700, color: '#ccd9ef' }}>{p.name}</td>
                  <td style={{ padding: '11px 14px', fontSize: 12, color: '#5b7fa6' }}>{p.doc_count}</td>
                  <td style={{ padding: '11px 14px' }}>
                    <span style={{
                      padding: '3px 10px', borderRadius: 20, fontSize: 10, fontWeight: 700,
                      background: p.status === 'active' ? 'rgba(16,185,129,.12)' : p.status === 'processing' ? 'rgba(245,158,11,.12)' : 'rgba(59,130,246,.12)',
                      color: p.status === 'active' ? '#10b981' : p.status === 'processing' ? '#f59e0b' : '#3b82f6',
                      border: `1px solid ${p.status === 'active' ? 'rgba(16,185,129,.25)' : p.status === 'processing' ? 'rgba(245,158,11,.25)' : 'rgba(59,130,246,.22)'}`
                    }}>
                      {p.status === 'active' ? '● نشط' : p.status === 'processing' ? '⟳ جاري التصنيف' : '◎ مكتمل'}
                    </span>
                  </td>
                  <td style={{ padding: '11px 14px', fontSize: 10, color: '#2a4a6e', fontFamily: "'JetBrains Mono'" }}>{new Date(p.created_at).toLocaleDateString('ar-SA')}</td>
                </tr>
              ))}</tbody>
            </table>
          }
        </div>
        <div className="card fu" style={{ padding: 22, animationDelay: '.17s' }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 14 }}>توزيع المشاريع</div>
          {projs.length > 0
            ? <><ResponsiveContainer width="100%" height={140}>
              <PieChart><Pie data={pieData} dataKey="v" nameKey="n" innerRadius={40} outerRadius={65} paddingAngle={3} strokeWidth={0}>
                {pieData.map((d, i) => <Cell key={i} fill={d.c} />)}
              </Pie><Tooltip formatter={(v: any) => v} contentStyle={{ background: '#0c1829', border: '1px solid rgba(59,130,246,.2)', borderRadius: 8, fontSize: 11, fontFamily: "'Tajawal'" }} /></PieChart>
            </ResponsiveContainer>
              {pieData.map((d, i) => <div key={i} style={{ display: 'flex', justifyContent: 'space-between', marginTop: 7 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><div style={{ width: 8, height: 8, borderRadius: 2, background: d.c }} /><span style={{ fontSize: 11, color: '#5b7fa6' }}>{d.n}</span></div>
                <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 600, color: d.c }}>{d.v}</span>
              </div>)}</>
            : <div style={{ textAlign: 'center', padding: '40px 0', color: '#3a5472', fontSize: 12 }}>لا بيانات</div>
          }
        </div>
      </div>
    </div>
  )
}

/* ══ CHAT ══════════════════════════════════════════════════ */
function ChatView({ proj, projs, setProj, activeDept, loadProjects }: any) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [convId, setConvId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [docs, setDocs] = useState<Doc[]>([])
  const [showPlus, setShowPlus] = useState(false)
  const [uploading, setUploading] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const plusRef = useRef<HTMLDivElement>(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])
  useEffect(() => { setMsgs([]); setConvId(null) }, [proj?.id])
  useEffect(() => {
    if (!proj) return
    docsApi.list(proj.id).then(r => setDocs(r.data)).catch(() => { })
  }, [proj?.id])
  useEffect(() => {
    const h = (e: MouseEvent) => { if (plusRef.current && !plusRef.current.contains(e.target as Node)) setShowPlus(false) }
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h)
  }, [])

  async function send(txt?: string) {
    const q = txt || input.trim()
    if (!q || !proj) return
    setInput(''); setShowPlus(false)
    const tid = `ai_${Date.now()}`
    setMsgs(p => [...p,
    { id: `u_${Date.now()}`, role: 'user', content: q, created_at: new Date().toISOString() },
    { id: tid, role: 'assistant', content: '__loading__', created_at: new Date().toISOString() },
    ])
    setLoading(true)
    try {
      const { data } = await chatApi.send(proj.id, q, convId || undefined)
      if (!convId) setConvId(data.conversation_id)
      setMsgs(p => p.map(m => m.id === tid ? { ...m, content: data.answer, sources: data.sources } : m))
    } catch (e: any) { toast.error(e.response?.data?.detail || 'خطأ في الاتصال'); setMsgs(p => p.filter(m => m.id !== tid)) }
    finally { setLoading(false) }
  }

  /* ② Auto-Organizer: upload a file directly from chat */
  async function handleChatUpload(file: File) {
    if (!file || uploading) return
    setShowPlus(false)
    const uid = `u_${Date.now()}`
    const tid = `ai_${Date.now()}`
    setMsgs(p => [...p,
    { id: uid, role: 'user', content: `📎 ${file.name}`, created_at: new Date().toISOString() },
    { id: tid, role: 'assistant', content: '__loading__', created_at: new Date().toISOString() },
    ])
    setUploading(true)
    try {
      const { data } = await autoOrganizerApi.uploadInChat(file, convId || undefined)
      if (!convId) setConvId(data.conversation_id)

      // If the backend returns 'processing', it means classification is happening in background
      if (data.status === 'processing') {
        setMsgs(p => p.map(m => m.id === tid ? { ...m, content: data.answer } : m))
        // Refresh project list to show the new "Processing" project
        if (loadProjects) await loadProjects()

        // Polling project status to update UI when classification is done
        if (data.project_id) {
          const poll = setInterval(async () => {
            try {
              const { data: projsData } = await projectsApi.list()
              const updatedProj = projsData.find((p: any) => p.id === data.project_id)
              if (updatedProj && updatedProj.status !== 'processing') {
                clearInterval(poll)
                if (loadProjects) await loadProjects()
                // Update conversation messages if classification finished
                chatApi.getMessages(data.conversation_id).then(r => setMsgs(r.data))
                toast.success(`✅ تم تصنيف المشروع: ${updatedProj.name}`)
                if (proj?.status === 'processing' || !proj) setProj(updatedProj)
              }
            } catch { clearInterval(poll) }
          }, 3000)
        }
      } else {
        // Legacy flow (if backend didn't use background classification)
        setMsgs(p => p.map(m => m.id === tid ? { ...m, content: data.answer } : m))
        if (loadProjects) await loadProjects()
        if (data.project_id && data.project_id !== proj?.id) {
          toast.success(`📂 أضيف إلى مشروع: ${data.project_name}`)
        }
      }

      // Poll document status until ready (for ingestion)
      if (data.doc_id && (data.project_id || proj?.id)) {
        let attempts = 0
        const pId = data.project_id || proj?.id
        const pollDoc = setInterval(async () => {
          attempts++
          try {
            const { data: st } = await docStatusApi.check(pId, data.doc_id)
            if (st.status === 'ready') {
              clearInterval(pollDoc)
              toast.success(`✅ تمت المعالجة — ${st.chunks_count} قطعة`)
              docsApi.list(pId).then(r => setDocs(r.data)).catch(() => { })
            } else if (st.status === 'failed') {
              clearInterval(pollDoc)
              toast.error(`❌ فشلت المعالجة: ${st.processing_error?.slice(0, 80)}`)
            }
          } catch { clearInterval(pollDoc) }
          if (attempts >= 20) clearInterval(pollDoc)
        }, 3000)
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'فشل الرفع')
      setMsgs(p => p.filter(m => m.id !== tid))
    } finally {
      setUploading(false)
    }
  }

  /* ② Dynamic quick actions from latest uploaded file */
  const quickActs = getActs(docs)

  /* ② Plus-menu items */
  const plusTop = [
    { icon: '💬', label: 'محادثة جديدة', fn: () => { setMsgs([]); setConvId(null); setShowPlus(false) } },
    { icon: '📤', label: 'رفع ملف', fn: () => { fileRef.current?.click(); setShowPlus(false) } },
  ]

  if (!proj) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '60%', color: '#3a5472', gap: 12 }}>
      <div style={{ fontSize: 48 }}>📁</div><div>اختر مشروعاً من الشريط الجانبي</div>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      {/* project bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 16px', background: 'rgba(12,24,41,.8)', border: '1px solid rgba(59,130,246,.12)', borderRadius: 11, marginBottom: 14, flexShrink: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 13, color: '#ccd9ef', flex: 1 }}>{proj.name}</div>
        <select value={proj.id} onChange={e => { const p = projs.find((x: any) => x.id === e.target.value); if (p) setProj(p) }}
          style={{ background: 'rgba(6,13,26,.8)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 8, padding: '5px 10px', color: '#ccd9ef', fontSize: 12, cursor: 'pointer', fontFamily: "'Tajawal',sans-serif" }}>
          {projs.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#10b981', padding: '4px 10px', background: 'rgba(16,185,129,.08)', border: '1px solid rgba(16,185,129,.2)', borderRadius: 16 }}>
          <Lock size={9} color="#10b981" />RAG + Masking
        </div>
      </div>

      {/* messages */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 10 }}>
        {msgs.length === 0
          ? /* empty state with dynamic quick actions */
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 18 }}>
            <div style={{ fontSize: 60 }}>🧠</div>
            <div style={{ fontSize: 16, color: '#5b7fa6', fontWeight: 800 }}>RAG Engine جاهز</div>
            <div style={{ fontSize: 12, color: '#2a4a6e' }}>{proj.doc_count} ملفات · البيانات الحساسة مُقنَّعة تلقائياً</div>
            {docs.length > 0
              ? /* ① File-aware quick actions */
              <div style={{ width: '100%', maxWidth: 560 }}>
                <div style={{ fontSize: 10, color: '#2a4a6e', marginBottom: 9, letterSpacing: '.1em', fontWeight: 600, textAlign: 'center' }}>
                  إجراءات سريعة — {getExt(docs[docs.length - 1].file_name).toUpperCase()}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center' }}>
                  {quickActs.map((a, i) => (
                    <button key={i} className="qa-btn" onClick={() => send(a.query)}
                      style={{ animation: `qaIn .3s ${i * .06}s both` }}>
                      <span style={{ fontSize: 15 }}>{a.icon}</span>{a.label}
                    </button>
                  ))}
                </div>
              </div>
              : /* default suggestions when no docs yet */
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, maxWidth: 500, width: '100%' }}>
                {['حلّل الملفات المرفوعة', 'ما أبرز النقاط؟', 'اعطني ملخصاً تنفيذياً', 'ما التوصيات؟'].map((s, i) => (
                  <div key={i} className="card" style={{ padding: '12px 16px', fontSize: 12, color: '#5b7fa6', textAlign: 'center', cursor: 'pointer' }} onClick={() => send(s)}>{s}</div>
                ))}
              </div>
            }
          </div>
          : msgs.map(m => {
            const isU = m.role === 'user'
            const ctype = (!isU && m.content !== '__loading__') ? detectType(m.content) : 'plain'
            const isCard = ctype !== 'plain'
            return (
              <div key={m.id} style={{ display: 'flex', gap: 10, marginBottom: isCard ? 20 : 16, flexDirection: isU ? 'row-reverse' : 'row' }}>
                <div style={{ width: 34, height: 34, borderRadius: 10, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, background: isU ? 'linear-gradient(135deg,#1e40af,#3b82f6)' : 'rgba(12,24,41,.9)', border: '1px solid rgba(59,130,246,.18)', marginTop: 2 }}>{isU ? '👤' : '🤖'}</div>
                {/* ④ ReportCard for tables / long reports */}
                <div style={{
                  maxWidth: isCard ? '92%' : '78%', flex: isCard ? 1 : undefined,
                  padding: isCard ? 0 : '13px 17px',
                  borderRadius: isU ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
                  background: isU ? 'linear-gradient(135deg,#1e40af,#3b82f6)' : isCard ? 'transparent' : '#0c1829',
                  border: isU ? 'none' : isCard ? 'none' : '1px solid rgba(59,130,246,.12)',
                  fontSize: 13, lineHeight: 1.9, color: '#ccd9ef'
                }}>
                  {m.content === '__loading__'
                    ? <div style={{ padding: '13px 17px', background: '#0c1829', border: '1px solid rgba(59,130,246,.12)', borderRadius: '4px 16px 16px 16px' }}>
                      <div style={{ display: 'flex', gap: 5 }}>{[0, 1, 2].map(j => <div key={j} style={{ width: 7, height: 7, borderRadius: '50%', background: '#3b82f6', animation: `dotBounce 1.2s ${j * .18}s infinite` }} />)}</div>
                    </div>
                    : m.content.includes('جاري تحليل وتصنيف مشروعك')
                      ? <div style={{ padding: '13px 17px', background: 'rgba(59,130,246,.05)', border: '1px solid rgba(59,130,246,.2)', borderRadius: '4px 16px 16px 16px', display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center', textAlign: 'center' }}>
                        <div style={{ width: 34, height: 34, borderRadius: '50%', border: '3px solid rgba(59,130,246,.1)', borderTopColor: '#3b82f6', animation: 'spin 1s linear infinite' }} />
                        <div className="prose-ar" style={{ fontSize: 13, fontWeight: 700, color: '#3b82f6' }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                        </div>
                      </div>
                      : isCard
                        ? <ReportCard content={m.content} type={ctype} />
                        : <div className="prose-ar"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>
                  }
                  {m.sources && m.sources.length > 0 && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid rgba(59,130,246,.12)', padding: isCard ? '8px 2px 0' : '8px 0 0' }}>
                      <div style={{ fontSize: 10, color: '#3a5472', marginBottom: 5 }}>المصادر:</div>
                      {m.sources.map((s: any, j: number) => (
                        <span key={j} style={{ display: 'inline-block', padding: '2px 8px', margin: '2px 3px', background: 'rgba(59,130,246,.12)', border: '1px solid rgba(59,130,246,.2)', borderRadius: 8, fontSize: 10, color: '#3b82f6' }}>📄 {s.filename} ({Math.round(s.relevance * 100)}%)</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })
        }
        <div ref={endRef} />
      </div>

      {/* ① Quick actions bar — persists above input once conversation started */}
      {docs.length > 0 && msgs.length > 0 && (
        <div style={{ display: 'flex', gap: 7, overflowX: 'auto', paddingBottom: 8, paddingTop: 2, flexShrink: 0, scrollbarWidth: 'none' }}>
          {quickActs.map((a, i) => (
            <button key={i} className="qa-btn" style={{ flexShrink: 0, fontSize: 11, padding: '6px 11px' }} onClick={() => send(a.query)}>
              <span style={{ fontSize: 13 }}>{a.icon}</span>{a.label}
            </button>
          ))}
        </div>
      )}

      {/* ② Input row */}
      <div style={{ flexShrink: 0, paddingTop: 4 }}>
        <div style={{ display: 'flex', gap: 9, alignItems: 'flex-end' }}>
          {/* Plus button with dropdown menu */}
          <div ref={plusRef} style={{ position: 'relative', flexShrink: 0 }}>
            <button className="btn" onClick={() => setShowPlus(p => !p)}
              title="إجراءات سريعة"
              style={{
                width: 48, height: 48, borderRadius: 12,
                background: showPlus ? 'rgba(59,130,246,.15)' : '#0c1829',
                border: `1px solid ${showPlus ? 'rgba(59,130,246,.38)' : 'rgba(59,130,246,.15)'}`,
                color: showPlus ? '#5b9bf6' : '#3a5472',
                fontSize: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all .2s'
              }}>
              <span style={{ display: 'inline-block', transform: showPlus ? 'rotate(45deg)' : 'none', transition: 'transform .22s ease', lineHeight: 1 }}>＋</span>
            </button>
            {showPlus && (
              <div className="plus-menu">
                <div className="pm-label">إجراءات</div>
                {plusTop.map(({ icon, label, fn }) => (
                  <div key={label} className="pm-item" onClick={fn}>
                    <span style={{ fontSize: 16, width: 22, textAlign: 'center' }}>{icon}</span>{label}
                  </div>
                ))}
                {docs.length > 0 && <>
                  <div className="pm-label" style={{ borderTop: '1px solid rgba(59,130,246,.1)', paddingTop: 8 }}>
                    طلبات سريعة — {getExt(docs[docs.length - 1].file_name).toUpperCase()}
                  </div>
                  {quickActs.map((a, i) => (
                    <div key={i} className="pm-item" onClick={() => { send(a.query); setShowPlus(false) }}>
                      <span style={{ fontSize: 16, width: 22, textAlign: 'center' }}>{a.icon}</span>{a.label}
                    </div>
                  ))}
                </>}
              </div>
            )}
          </div>

          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            dir="rtl" rows={1} placeholder="اسأل عن مستندات المشروع... (Enter للإرسال)"
            style={{ flex: 1, background: '#0c1829', border: '1px solid rgba(59,130,246,.15)', borderRadius: 12, padding: '13px 16px', color: '#ccd9ef', fontSize: 13, resize: 'none', lineHeight: 1.6, minHeight: 48, maxHeight: 120, outline: 'none', fontFamily: "'Tajawal',sans-serif" }} />
          <button className="btn" onClick={() => send()} disabled={!input.trim() || loading}
            style={{ width: 48, height: 48, borderRadius: 12, background: input.trim() && !loading ? 'linear-gradient(135deg,#1e40af,#3b82f6)' : '#0c1829', border: `1px solid ${input.trim() && !loading ? '#3b82f6' : 'rgba(59,130,246,.15)'}`, color: input.trim() && !loading ? '#fff' : '#2a4a6e', fontSize: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            {loading ? <Spin /> : '➤'}
          </button>
        </div>
        {/* ① Mini security line */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: '#2a4a6e', marginTop: 6 }}>
          <Lock size={9} color="#2a4a6e" />
          AES-256 · بيانات حساسة مُقنَّعة قبل الإرسال
        </div>
        <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv,.pdf,.docx,.doc,.pptx,.txt,.md" style={{ display: 'none' }}
          onChange={e => { const f = e.target.files?.[0]; if (f) handleChatUpload(f); e.target.value = '' }} />
      </div>
    </div>
  )
}

/* ══ KNOWLEDGE ══════════════════════════════════════════════ */
function KnowView({ proj, projs, setProj, activeDept }: any) {
  const [docs, setDocs] = useState<Doc[]>([])
  const [loading, setLoading] = useState(false)
  const [dept, setDept] = useState(activeDept || 'general')
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [selFile, setSelFile] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadDocs = useCallback(async () => {
    if (!proj) return; setLoading(true)
    try { const { data } = await docsApi.list(proj.id); setDocs(data) } catch { } finally { setLoading(false) }
  }, [proj?.id])
  useEffect(() => { loadDocs() }, [loadDocs])

  async function doUpload() {
    if (!selFile || !proj) return; setUploading(true)
    const fd = new FormData(); fd.append('file', selFile); fd.append('department', dept); fd.append('language', 'ar')
    try {
      const { data: uploadData } = await docsApi.upload(proj.id, fd)
      toast.success('✅ تم رفع الملف — جاري المعالجة...')
      setSelFile(null)
      // Smart polling — يستعلم عن الحالة حتى يكتمل
      const docId = uploadData.id
      if (docId) {
        let attempts = 0
        const poll = setInterval(async () => {
          attempts++
          try {
            const { data: st } = await docStatusApi.check(proj.id, docId)
            if (st.status === 'ready') {
              clearInterval(poll)
              toast.success(`✅ معالجة مكتملة — ${st.chunks_count} قطعة`)
              loadDocs()
            } else if (st.status === 'failed') {
              clearInterval(poll)
              toast.error(`❌ فشلت المعالجة: ${st.processing_error?.slice(0, 100)}`)
              loadDocs()
            } else {
              loadDocs() // refresh list to show processing state
            }
          } catch { clearInterval(poll) }
          if (attempts >= 20) { clearInterval(poll); loadDocs() }
        }, 3000)
      } else {
        setTimeout(loadDocs, 4000); setTimeout(loadDocs, 10000)
      }
    } catch (e: any) { toast.error(e.response?.data?.detail || 'فشل الرفع') }
    finally { setUploading(false) }
  }

  async function doDelete(id: string) {
    if (!proj || !confirm('هل أنت متأكد؟')) return
    try { await docsApi.delete(proj.id, id); toast.success('تم الحذف'); loadDocs() } catch { toast.error('فشل الحذف') }
  }

  if (!proj) return <div style={{ textAlign: 'center', padding: '60px 0', color: '#3a5472' }}>اختر مشروعاً أولاً</div>
  const total = docs.reduce((a, d) => a + d.chunks_count, 0)

  /* ① Preview quick actions for selected file */
  const previewActs = selFile ? (FILE_ACTIONS[getExt(selFile.name)] || FILE_ACTIONS.default) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', flex: 1 }}>قاعدة المعرفة: {proj.name}</div>
        <select value={proj.id} onChange={e => { const p = projs.find((x: any) => x.id === e.target.value); if (p) setProj(p) }}
          style={{ background: 'rgba(12,24,41,.8)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 8, padding: '5px 10px', color: '#ccd9ef', fontSize: 12, cursor: 'pointer', fontFamily: "'Tajawal',sans-serif" }}>
          {projs.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
        {[
          { icon: '📚', label: 'إجمالي الملفات', val: docs.length, col: '#3b82f6' },
          { icon: '🧩', label: 'إجمالي الـ Chunks', val: total, col: '#10b981' },
          { icon: '🔒', label: 'مشفّرة AES-256', val: docs.filter(d => d.is_encrypted).length, col: '#f59e0b' },
        ].map((s, i) => (
          <div key={i} className="card fu" style={{ padding: '18px 20px', animationDelay: `${i * .07}s` }}>
            <div style={{ fontSize: 22, marginBottom: 8 }}>{s.icon}</div>
            <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 26, fontWeight: 600, color: s.col }}>{s.val}</div>
            <div style={{ fontSize: 11, color: '#3a5472', marginTop: 4 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div className="card fu" style={{ padding: 22, animationDelay: '.1s' }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 14 }}>رفع ملف جديد</div>
        <div className={`drop-zone ${dragOver ? 'dragging' : ''} ${selFile ? 'has-file' : ''}`}
          style={{ padding: '24px 20px', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 16 }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) setSelFile(f) }}
          onClick={() => fileRef.current?.click()}>
          <span style={{ fontSize: 36 }}>{selFile ? '📗' : '📤'}</span>
          <div style={{ flex: 1 }}>
            {selFile
              ? <>
                <div style={{ color: '#10b981', fontWeight: 700, fontSize: 14 }}>{selFile.name}</div>
                <div style={{ fontSize: 11, color: '#2a4a6e', marginTop: 3 }}>{(selFile.size / 1024).toFixed(1)} KB · سيُشفَّر قبل الحفظ</div>
                {/* ① Quick-action preview chips on file selection */}
                {previewActs && (
                  <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                    {previewActs.map((a, i) => (
                      <span key={i} style={{ padding: '2px 8px', background: 'rgba(16,185,129,.09)', border: '1px solid rgba(16,185,129,.22)', borderRadius: 7, fontSize: 10, color: 'rgba(16,185,129,.8)', animation: `qaIn .25s ${i * .05}s both` }}>
                        {a.icon} {a.label}
                      </span>
                    ))}
                  </div>
                )}
              </>
              : <>
                <div style={{ fontSize: 14, color: '#5b7fa6' }}>اسحب ملفاً أو <span style={{ color: '#3b82f6', fontWeight: 700 }}>انقر للاختيار</span></div>
                <div style={{ fontSize: 11, color: '#2a4a6e', marginTop: 3 }}>PDF · Word · Excel · CSV · PowerPoint · TXT</div>
              </>
            }
          </div>
          {selFile && <button className="btn" onClick={e => { e.stopPropagation(); setSelFile(null) }} style={{ background: 'none', color: '#2a4a6e', fontSize: 22 }}>✕</button>}
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv,.pdf,.docx,.doc,.pptx,.txt,.md" style={{ display: 'none' }} onChange={e => setSelFile(e.target.files?.[0] || null)} />
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <select value={dept} onChange={e => setDept(e.target.value)}
            style={{ background: 'rgba(6,13,26,.8)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 9, padding: '10px 14px', color: '#ccd9ef', fontSize: 13, cursor: 'pointer', fontFamily: "'Tajawal',sans-serif" }}>
            {DEPTS.map(d => <option key={d.value} value={d.value}>{d.icon} {d.label}</option>)}
          </select>
          <button className="btn" onClick={doUpload} disabled={!selFile || uploading}
            style={{ padding: '11px 26px', borderRadius: 11, background: selFile && !uploading ? 'linear-gradient(135deg,#1e40af,#3b82f6)' : 'rgba(59,130,246,.1)', color: selFile && !uploading ? '#fff' : '#2a4a6e', fontSize: 14, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 9 }}>
            {uploading && <Spin />}{uploading ? 'جاري الرفع والتشفير...' : 'رفع الملف'}
          </button>
        </div>
      </div>

      <div className="card fu" style={{ padding: 22, animationDelay: '.18s' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef' }}>المستندات ({docs.length})</div>
          <button className="btn" onClick={loadDocs} style={{ background: 'none', color: '#5b7fa6', border: '1px solid rgba(59,130,246,.15)', borderRadius: 8, padding: '5px 12px', fontSize: 12 }}>
            {loading ? <Spin s={14} c="#5b7fa6" /> : '↻ تحديث'}
          </button>
        </div>
        {docs.length === 0
          ? <div style={{ textAlign: 'center', padding: '30px 0', color: '#3a5472', fontSize: 13 }}>لا توجد ملفات</div>
          : <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>{['الملف', 'القسم', 'الحالة', 'Chunks', 'التاريخ', ''].map(h => <th key={h} style={{ padding: '7px 14px', textAlign: 'right', fontSize: 10, color: '#2a4a6e', fontWeight: 600, borderBottom: '1px solid rgba(59,130,246,.1)' }}>{h}</th>)}</tr></thead>
            <tbody>{docs.map(d => (
              <tr key={d.id} className="row-hover" style={{ borderBottom: '1px solid rgba(59,130,246,.05)' }}>
                <td style={{ padding: '11px 14px', fontSize: 12, fontWeight: 700, color: '#ccd9ef' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                    <span>{DEPTS.find(x => x.value === d.department)?.icon || '📄'}</span>
                    <span>{d.file_name}</span>
                    <span style={{ fontSize: 9, color: '#2a4a6e', fontFamily: "'JetBrains Mono'", padding: '1px 5px', background: 'rgba(59,130,246,.06)', borderRadius: 4 }}>{getExt(d.file_name).toUpperCase()}</span>
                  </div>
                </td>
                <td style={{ padding: '11px 14px' }}><span style={{ padding: '3px 9px', borderRadius: 16, fontSize: 10, fontWeight: 700, background: `${DEPT_COLOR[d.department] || '#3a5472'}18`, color: DEPT_COLOR[d.department] || '#3a5472', border: `1px solid ${DEPT_COLOR[d.department] || '#3a5472'}33` }}>{DEPTS.find(x => x.value === d.department)?.label || d.department}</span></td>
                <td style={{ padding: '11px 14px', fontSize: 12, color: d.status === 'ready' ? '#10b981' : d.status === 'processing' ? '#f59e0b' : '#f87171' }}>{d.status === 'ready' ? '✓ جاهز' : d.status === 'processing' ? '⟳ معالجة' : '✗ فشل'}</td>
                <td style={{ padding: '11px 14px', fontFamily: "'JetBrains Mono'", fontSize: 13, color: '#3b82f6' }}>{d.chunks_count}</td>
                <td style={{ padding: '11px 14px', fontSize: 10, color: '#2a4a6e', fontFamily: "'JetBrains Mono'" }}>{new Date(d.created_at).toLocaleDateString('ar-SA')}</td>
                <td style={{ padding: '11px 14px' }}><button className="btn" onClick={() => doDelete(d.id)} style={{ background: 'none', fontSize: 11, padding: '4px 9px', border: '1px solid rgba(248,113,113,.2)', borderRadius: 7, color: '#f87171' }}>حذف</button></td>
              </tr>
            ))}</tbody>
          </table>
        }
      </div>
    </div>
  )
}

/* ══ PROJECTS ════════════════════════════════════════════════ */
function ProjsView({ projs, setProjs, setProj, setView, loadProjects }: any) {
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [creating, setCreating] = useState(false)

  async function create(e: React.FormEvent) {
    e.preventDefault(); if (!name.trim()) return; setCreating(true)
    try { await projectsApi.create({ name, description: desc }); await loadProjects(); setName(''); setDesc(''); setShowForm(false); toast.success('تم إنشاء المشروع') }
    catch (e: any) { toast.error(e.response?.data?.detail || 'فشل الإنشاء') }
    finally { setCreating(false) }
  }
  async function del(id: string) {
    if (!confirm('هل أنت متأكد؟ سيتم حذف جميع الملفات والمحادثات.')) return
    try { await projectsApi.delete(id); await loadProjects(); toast.success('تم الحذف') } catch { toast.error('فشل الحذف') }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 16, color: '#ccd9ef' }}>إدارة المشاريع ({projs.length})</div>
        <button className="btn" onClick={() => setShowForm(!showForm)} style={{ padding: '10px 22px', borderRadius: 11, background: 'linear-gradient(135deg,#1e40af,#3b82f6)', color: '#fff', fontSize: 14, fontWeight: 700 }}>
          {showForm ? '↩ إلغاء' : '＋ مشروع جديد'}
        </button>
      </div>
      {showForm && (
        <form onSubmit={create} className="card fu" style={{ padding: 22, borderColor: 'rgba(59,130,246,.3)' }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 16 }}>إنشاء مشروع جديد</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            {([['الاسم *', name, setName, true], ['الوصف', desc, setDesc, false]] as any[]).map(([lbl, val, fn, req]) => (
              <div key={lbl}>
                <div style={{ fontSize: 12, color: '#5b7fa6', marginBottom: 6, fontWeight: 600 }}>{lbl}</div>
                <input value={val} onChange={(e: any) => fn(e.target.value)} required={req} dir="rtl" style={{ width: '100%', background: 'rgba(6,13,26,.7)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 10, padding: '11px 14px', color: '#ccd9ef', fontSize: 13, outline: 'none', fontFamily: "'Tajawal',sans-serif" }} />
              </div>
            ))}
          </div>
          <button type="submit" className="btn" disabled={creating || !name.trim()} style={{ padding: '10px 24px', borderRadius: 10, background: name.trim() && !creating ? 'linear-gradient(135deg,#1e40af,#3b82f6)' : 'rgba(59,130,246,.1)', color: name.trim() && !creating ? '#fff' : '#2a4a6e', fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
            {creating && <Spin s={15} />}{creating ? 'إنشاء...' : 'إنشاء المشروع'}
          </button>
        </form>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 15 }}>
        {projs.map((p: any, i: number) => (
          <div key={p.id} className="card fu" style={{ padding: 22, cursor: 'pointer', animationDelay: `${i * .07}s`, position: 'relative' }} onClick={() => { setProj(p); setView('chat') }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div style={{ width: 46, height: 46, borderRadius: 13, background: `${CARD_COLS[i % 4]}1a`, border: `1px solid ${CARD_COLS[i % 4]}33`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 24 }}>📊</div>
              <span style={{
                padding: '4px 11px', borderRadius: 20, fontSize: 10, fontWeight: 700,
                background: p.status === 'active' ? 'rgba(16,185,129,.12)' : p.status === 'processing' ? 'rgba(245,158,11,.12)' : 'rgba(59,130,246,.12)',
                color: p.status === 'active' ? '#10b981' : p.status === 'processing' ? '#f59e0b' : '#3b82f6',
                border: `1px solid ${p.status === 'active' ? 'rgba(16,185,129,.25)' : p.status === 'processing' ? 'rgba(245,158,11,.25)' : 'rgba(59,130,246,.22)'}`
              }}>
                {p.status === 'active' ? '● نشط' : p.status === 'processing' ? '⟳ جاري التصنيف' : '◎ مكتمل'}
              </span>
            </div>
            <div style={{ fontWeight: 800, fontSize: 14, color: '#ccd9ef', marginBottom: 6 }}>{p.name}</div>
            <div style={{ fontSize: 11, color: '#3a5472', marginBottom: 14, minHeight: 28, lineHeight: 1.6 }}>{p.description || '—'}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#4d6a8a', borderTop: '1px solid rgba(59,130,246,.1)', paddingTop: 12 }}>
              <span>📄 {p.doc_count} ملفات</span>
              <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10 }}>{new Date(p.created_at).toLocaleDateString('ar-SA')}</span>
            </div>
            <button className="btn" onClick={e => { e.stopPropagation(); del(p.id) }} style={{ position: 'absolute', top: 14, left: 14, background: 'none', fontSize: 11, padding: '3px 8px', border: '1px solid rgba(248,113,113,.2)', borderRadius: 7, color: '#f87171' }}>حذف</button>
          </div>
        ))}
      </div>
      {projs.length === 0 && <div style={{ textAlign: 'center', padding: '60px 0', color: '#3a5472', fontSize: 14 }}><div style={{ fontSize: 56, marginBottom: 16 }}>📁</div>ابدأ بإنشاء مشروعك الأول</div>}
    </div>
  )
}
/* ══ TEAM MANAGEMENT ════════════════════════════════════════ */
function TeamView() {
  const [team, setTeam] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('employee')
  const [inviting, setInviting] = useState(false)

  const loadTeam = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await orgApi.getTeam()
      setTeam(data)
    } catch {
      toast.error('فشل تحميل قائمة الفريق')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadTeam() }, [loadTeam])

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setInviting(true)
    try {
      await orgApi.invite(email, role)
      toast.success('تم إرسال الدعوة بنجاح')
      setEmail('')
      loadTeam()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'فشل إرسال الدعوة')
    } finally {
      setInviting(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ fontWeight: 800, fontSize: 18, color: '#ccd9ef' }}>إدارة الفريق</div>

      {/* Invite Member Card */}
      <div className="card fu" style={{ padding: 24, background: 'rgba(59,130,246,.03)', border: '1px solid rgba(59,130,246,.15)' }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 18 }}>إضافة عضو جديد</div>
        <form onSubmit={handleInvite} style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <div style={{ flex: 2 }}>
            <div style={{ fontSize: 11, color: '#5b7fa6', marginBottom: 6, fontWeight: 600 }}>البريد الإلكتروني للزميل</div>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="example@company.com"
              required
              style={{ width: '100%', background: 'rgba(6,13,26,.7)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 10, padding: '11px 14px', color: '#ccd9ef', fontSize: 13, outline: 'none', fontFamily: "'Tajawal',sans-serif" }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: '#5b7fa6', marginBottom: 6, fontWeight: 600 }}>الصلاحية</div>
            <select
              value={role}
              onChange={e => setRole(e.target.value)}
              style={{ width: '100%', background: 'rgba(6,13,26,.7)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 10, padding: '10px 14px', color: '#ccd9ef', fontSize: 13, cursor: 'pointer', fontFamily: "'Tajawal',sans-serif" }}
            >
              <option value="employee">موظف (Employee)</option>
              <option value="org_admin">مسؤول (Org-Admin)</option>
            </select>
          </div>
          <button
            type="submit"
            className="btn"
            disabled={inviting || !email.trim()}
            style={{ padding: '11px 28px', borderRadius: 11, background: 'linear-gradient(135deg,#1e40af,#3b82f6)', color: '#fff', fontSize: 14, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 9 }}
          >
            {inviting && <Spin s={16} />}
            {inviting ? 'جاري الإرسال...' : 'إرسال دعوة'}
          </button>
        </form>
      </div>

      {/* Team Members List */}
      <div className="card fu" style={{ padding: 24, animationDelay: '.1s' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef' }}>أعضاء الفريق</div>
          <button className="btn" onClick={loadTeam} style={{ background: 'none', color: '#5b7fa6', border: '1px solid rgba(59,130,246,.15)', borderRadius: 8, padding: '5px 12px', fontSize: 12 }}>
            {loading ? <Spin s={14} c="#5b7fa6" /> : '↻ تحديث'}
          </button>
        </div>

        {team.length === 0 && !loading ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#3a5472', fontSize: 13 }}>لا يوجد أعضاء في الفريق حالياً</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['العضو', 'البريد الإلكتروني', 'الدور', 'الحالة', 'تاريخ الانضمام'].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'right', fontSize: 11, color: '#2a4a6e', fontWeight: 600, borderBottom: '1px solid rgba(59,130,246,.1)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {team.map((m, i) => (
                  <tr key={m.id || i} className="row-hover" style={{ borderBottom: '1px solid rgba(59,130,246,.05)' }}>
                    <td style={{ padding: '14px', fontSize: 13, fontWeight: 700, color: '#ccd9ef' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'rgba(59,130,246,.1)', border: '1px solid rgba(59,130,246,.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>👤</div>
                        {m.full_name || '—'}
                      </div>
                    </td>
                    <td style={{ padding: '14px', fontSize: 12, color: '#5b7fa6', fontFamily: "'JetBrains Mono'" }}>{m.email}</td>
                    <td style={{ padding: '14px' }}>
                      <span style={{ padding: '4px 10px', borderRadius: 12, fontSize: 10, fontWeight: 700, background: m.role === 'org_admin' ? 'rgba(245,158,11,.1)' : 'rgba(16,185,129,.1)', color: m.role === 'org_admin' ? '#f59e0b' : '#10b981', border: `1px solid ${m.role === 'org_admin' ? 'rgba(245,158,11,.2)' : 'rgba(16,185,129,.2)'}` }}>
                        {m.role === 'org_admin' ? 'مسؤول' : 'موظف'}
                      </span>
                    </td>
                    <td style={{ padding: '14px', fontSize: 12 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: m.is_active ? '#10b981' : '#f87171' }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: m.is_active ? '#10b981' : '#f87171' }}></span>
                        {m.is_active ? 'نشط' : 'غير نشط'}
                      </span>
                    </td>
                    <td style={{ padding: '14px', fontSize: 11, color: '#2a4a6e', fontFamily: "'JetBrains Mono'" }}>
                      {m.created_at ? new Date(m.created_at).toLocaleDateString('ar-SA') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Info Box */}
      <div style={{ padding: '15px 20px', background: 'rgba(16,185,129,.05)', border: '1px solid rgba(16,185,129,.15)', borderRadius: 12, fontSize: 12, color: '#10b981', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span>💡</span>
        <span>بصفتك مسؤول النظام (Org-Admin)، يمكنك دعوة زملائك وإدارة صلاحياتهم. الموظفون المدعوون سيصلهم بريد إلكتروني يحتوي على رابط تفعيل خاص.</span>
      </div>
    </div>
  )
}
