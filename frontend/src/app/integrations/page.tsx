'use client'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import { erpApi } from '@/lib/api'
import toast from 'react-hot-toast'

const SYSTEMS = [
  { value: 'odoo',   label: 'أودو',        icon: '🟣', desc: 'Odoo ERP — مالي + موارد بشرية',    auth: 'odoo_rpc' },
  { value: 'rawa',   label: 'رواء',         icon: '🟢', desc: 'نظام رواء للموارد البشرية',         auth: 'api_key'  },
  { value: 'sap',    label: 'SAP',          icon: '🔵', desc: 'SAP S/4HANA — مالي ومخزون',        auth: 'basic'    },
  { value: 'oracle', label: 'أوراكل',       icon: '🔴', desc: 'Oracle Fusion ERP',                auth: 'oauth2'   },
  { value: 'masar',  label: 'مسار / قوى',  icon: '🟡', desc: 'أنظمة الموارد البشرية السعودية',   auth: 'api_key'  },
  { value: 'custom', label: 'نظام مخصص',   icon: '⚫', desc: 'أي نظام يدعم REST API',            auth: 'api_key'  },
]

const DATA_TYPES = [
  { value: 'budget',          label: 'الميزانية',         icon: '💰' },
  { value: 'invoices',        label: 'الفواتير',           icon: '🧾' },
  { value: 'purchase_orders', label: 'أوامر الشراء',      icon: '📦' },
  { value: 'employees',       label: 'الموظفون',           icon: '👥' },
  { value: 'leave_balance',   label: 'رصيد الإجازات',     icon: '🌴' },
  { value: 'leave_requests',  label: 'طلبات الإجازة',     icon: '📝' },
  { value: 'payroll',         label: 'الرواتب',            icon: '💵' },
  { value: 'sales',           label: 'المبيعات',           icon: '📈' },
]

export default function IntegrationsPage() {
  const router    = useRouter()
  const { user }  = useAuthStore()
  const [tab, setTab]           = useState<'systems'|'connect'|'fetch'|'chat'>('systems')
  const [systems, setSystems]   = useState<any[]>([])
  const [health, setHealth]     = useState<Record<string,boolean>>({})
  const [loading, setLoading]   = useState(false)

  // Connect form
  const [form, setForm] = useState({
    name:'', system:'odoo', base_url:'', auth_type:'odoo_rpc',
    api_key:'', username:'', password:'', database:'',
  })

  // Fetch form
  const [fetchForm, setFetchForm] = useState({ system_name:'', data_type:'budget', params:'{}' })
  const [fetchResult, setFetchResult] = useState<any>(null)

  // ERP Chat
  const [chatQ, setChatQ]         = useState('')
  const [chatAnswer, setChatAnswer] = useState('')
  const [chatLoading, setChatLoading] = useState(false)

  useEffect(() => { if (!user) router.push('/login'); else loadSystems() }, [user])

  async function loadSystems() {
    try {
      const [sysRes, hRes] = await Promise.all([erpApi.listSystems(), erpApi.health()])
      setSystems(sysRes.data.systems || [])
      setHealth(hRes.data.systems || {})
    } catch { /* ignore */ }
  }

  async function handleConnect(e: React.MouseEvent) {
    e.preventDefault()
    if (!form.name || !form.base_url) return toast.error('اسم النظام والرابط مطلوبان')
    setLoading(true)
    try {
      const res = await erpApi.connect({ ...form })
      toast.success(res.data.connected ? 'تم الربط بنجاح ✅' : 'تم التسجيل — تحقق من الإعدادات')
      setTab('systems'); loadSystems()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'فشل الربط')
    } finally { setLoading(false) }
  }

  async function handleFetch(e: React.MouseEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      let params = {}
      try { params = JSON.parse(fetchForm.params) } catch { toast.error('صيغة الـ params غير صحيحة'); return }
      const res = await erpApi.fetch({ system_name: fetchForm.system_name, data_type: fetchForm.data_type, params })
      setFetchResult(res.data)
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'فشل جلب البيانات')
    } finally { setLoading(false) }
  }

  async function handleChat(e: React.MouseEvent) {
    e.preventDefault()
    if (!chatQ.trim()) return
    setChatLoading(true); setChatAnswer('')
    try {
      const res = await erpApi.chat({ question: chatQ })
      setChatAnswer(res.data.answer)
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'فشل')
    } finally { setChatLoading(false) }
  }

  async function handleDisconnect(name: string) {
    if (!confirm(`هل تريد فصل النظام "${name}"؟`)) return
    try { await erpApi.disconnect(name); loadSystems(); toast.success('تم الفصل') }
    catch { toast.error('فشل الفصل') }
  }

  const selectedSystem = SYSTEMS.find(s => s.value === form.system)

  return (
    <div style={{ minHeight:'100vh', background:'#0f172a', color:'#e2e8f0', fontFamily:'Arial,sans-serif', direction:'rtl' }}>
      {/* Header */}
      <div style={{ background:'#1e293b', borderBottom:'1px solid #334155', padding:'16px 32px', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <button onClick={() => router.push('/dashboard')} style={{ background:'#334155', border:'none', color:'#94a3b8', padding:'6px 14px', borderRadius:6, cursor:'pointer' }}>← لوحة التحكم</button>
          <h1 style={{ margin:0, fontSize:18, fontWeight:700, color:'#f1f5f9' }}>🔗 ربط الأنظمة المحاسبية والموارد البشرية</h1>
        </div>
        <span style={{ background:'#7c3aed22', color:'#a78bfa', padding:'4px 12px', borderRadius:20, fontSize:12 }}>
          {systems.length} نظام مربوط
        </span>
      </div>

      {/* Tabs */}
      <div style={{ background:'#1e293b', padding:'0 32px', borderBottom:'1px solid #334155', display:'flex', gap:0 }}>
        {([['systems','الأنظمة المربوطة','🖥️'],['connect','ربط نظام جديد','➕'],['fetch','جلب بيانات','📊'],['chat','سؤال ذكي','🤖']] as const).map(([t,l,icon]) => (
          <button key={t} onClick={() => setTab(t as any)} style={{
            background:'none', border:'none', color: tab===t ? '#7c3aed' : '#64748b',
            padding:'14px 20px', cursor:'pointer', fontSize:13, fontWeight: tab===t ? 700 : 400,
            borderBottom: tab===t ? '2px solid #7c3aed' : '2px solid transparent',
          }}>{icon} {l}</button>
        ))}
      </div>

      <div style={{ maxWidth:900, margin:'0 auto', padding:'32px 24px' }}>

        {/* ── TAB: Systems ── */}
        {tab === 'systems' && (
          <div>
            <h2 style={{ color:'#f1f5f9', fontSize:16, marginBottom:20 }}>الأنظمة المربوطة حالياً</h2>
            {systems.length === 0 ? (
              <div style={{ background:'#1e293b', borderRadius:12, padding:40, textAlign:'center', color:'#64748b' }}>
                <div style={{ fontSize:40, marginBottom:16 }}>🔌</div>
                <div>لم يتم ربط أي نظام بعد</div>
                <button onClick={() => setTab('connect')} style={{ marginTop:16, background:'#7c3aed', color:'#fff', border:'none', padding:'10px 24px', borderRadius:8, cursor:'pointer', fontFamily:'Arial' }}>
                  ربط نظام جديد ➕
                </button>
              </div>
            ) : (
              <div style={{ display:'grid', gap:16 }}>
                {systems.map((sys: any) => {
                  const def = SYSTEMS.find(s => s.value === sys.system)
                  const ok  = health[sys.name]
                  return (
                    <div key={sys.name} style={{ background:'#1e293b', borderRadius:12, padding:20, border:'1px solid #334155', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:16 }}>
                        <div style={{ fontSize:28 }}>{def?.icon || '🔧'}</div>
                        <div>
                          <div style={{ fontWeight:700, color:'#f1f5f9', marginBottom:4 }}>{sys.name}</div>
                          <div style={{ color:'#64748b', fontSize:12 }}>{def?.label} — {sys.url}</div>
                        </div>
                      </div>
                      <div style={{ display:'flex', alignItems:'center', gap:12 }}>
                        <span style={{ background: ok ? '#16a34a22' : '#dc262622', color: ok ? '#4ade80' : '#f87171', padding:'4px 12px', borderRadius:20, fontSize:12 }}>
                          {ok === undefined ? '⏳ جاري الفحص' : ok ? '✅ متصل' : '❌ لا يتصل'}
                        </span>
                        <button onClick={() => handleDisconnect(sys.name)} style={{ background:'#dc262622', color:'#f87171', border:'1px solid #dc2626', padding:'6px 14px', borderRadius:6, cursor:'pointer', fontSize:12 }}>
                          فصل
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ── TAB: Connect ── */}
        {tab === 'connect' && (
          <div>
            <h2 style={{ color:'#f1f5f9', fontSize:16, marginBottom:20 }}>ربط نظام جديد</h2>

            {/* System selector */}
            <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:24 }}>
              {SYSTEMS.map(s => (
                <div key={s.value} onClick={() => setForm(f => ({ ...f, system: s.value, auth_type: s.auth }))}
                  style={{ background: form.system===s.value ? '#7c3aed22' : '#1e293b', border:`1px solid ${form.system===s.value ? '#7c3aed' : '#334155'}`, borderRadius:10, padding:16, cursor:'pointer', textAlign:'center' }}>
                  <div style={{ fontSize:24, marginBottom:6 }}>{s.icon}</div>
                  <div style={{ color:'#f1f5f9', fontWeight:600, fontSize:13 }}>{s.label}</div>
                  <div style={{ color:'#64748b', fontSize:11, marginTop:4 }}>{s.desc}</div>
                </div>
              ))}
            </div>

            {/* Form */}
            <div style={{ background:'#1e293b', borderRadius:12, padding:24, display:'grid', gap:16 }}>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
                <div>
                  <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>اسم مرجعي *</label>
                  <input value={form.name} onChange={e => setForm(f=>({...f,name:e.target.value}))} placeholder="مثال: odoo_main"
                    style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial', direction:'ltr' }} />
                </div>
                <div>
                  <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>رابط API *</label>
                  <input value={form.base_url} onChange={e => setForm(f=>({...f,base_url:e.target.value}))} placeholder="https://your-system.com"
                    style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial', direction:'ltr' }} />
                </div>
              </div>

              {(form.auth_type === 'api_key') && (
                <div>
                  <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>API Key</label>
                  <input type="password" value={form.api_key} onChange={e => setForm(f=>({...f,api_key:e.target.value}))} placeholder="your_api_key"
                    style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial', direction:'ltr' }} />
                </div>
              )}

              {(form.auth_type === 'odoo_rpc' || form.auth_type === 'basic') && (
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12 }}>
                  <div>
                    <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>اسم المستخدم</label>
                    <input value={form.username} onChange={e => setForm(f=>({...f,username:e.target.value}))}
                      style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial', direction:'ltr' }} />
                  </div>
                  <div>
                    <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>كلمة المرور</label>
                    <input type="password" value={form.password} onChange={e => setForm(f=>({...f,password:e.target.value}))}
                      style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial', direction:'ltr' }} />
                  </div>
                  {form.auth_type === 'odoo_rpc' && (
                    <div>
                      <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>اسم قاعدة البيانات</label>
                      <input value={form.database} onChange={e => setForm(f=>({...f,database:e.target.value}))} placeholder="company_db"
                        style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial', direction:'ltr' }} />
                    </div>
                  )}
                </div>
              )}

              <button onClick={handleConnect} disabled={loading} style={{ background: loading ? '#334155' : '#7c3aed', color:'#fff', border:'none', padding:'12px 28px', borderRadius:8, cursor: loading ? 'not-allowed' : 'pointer', fontWeight:700, fontSize:14, fontFamily:'Arial' }}>
                {loading ? '⏳ جاري الربط...' : '🔗 ربط النظام'}
              </button>
            </div>
          </div>
        )}

        {/* ── TAB: Fetch ── */}
        {tab === 'fetch' && (
          <div>
            <h2 style={{ color:'#f1f5f9', fontSize:16, marginBottom:20 }}>جلب بيانات من نظام</h2>
            <div style={{ background:'#1e293b', borderRadius:12, padding:24, display:'grid', gap:16, marginBottom:20 }}>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
                <div>
                  <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>النظام</label>
                  <select value={fetchForm.system_name} onChange={e => setFetchForm(f=>({...f,system_name:e.target.value}))}
                    style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial' }}>
                    <option value="">-- اختر النظام --</option>
                    {systems.map((s:any) => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>نوع البيانات</label>
                  <select value={fetchForm.data_type} onChange={e => setFetchForm(f=>({...f,data_type:e.target.value}))}
                    style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:13, boxSizing:'border-box', fontFamily:'Arial' }}>
                    {DATA_TYPES.map(d => <option key={d.value} value={d.value}>{d.icon} {d.label}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label style={{ color:'#94a3b8', fontSize:12, display:'block', marginBottom:6 }}>معاملات البحث (JSON)</label>
                <textarea value={fetchForm.params} onChange={e => setFetchForm(f=>({...f,params:e.target.value}))} rows={3}
                  placeholder={'{"year": 2026, "quarter": 1}'}
                  style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'10px 14px', borderRadius:8, fontSize:12, boxSizing:'border-box', fontFamily:'monospace', direction:'ltr', resize:'vertical' }} />
              </div>
              <button onClick={handleFetch} disabled={loading} style={{ background: loading ? '#334155' : '#0ea5e9', color:'#fff', border:'none', padding:'12px 28px', borderRadius:8, cursor: loading ? 'not-allowed' : 'pointer', fontWeight:700, fontFamily:'Arial' }}>
                {loading ? '⏳ جاري الجلب...' : '📊 جلب البيانات'}
              </button>
            </div>
            {fetchResult && (
              <div style={{ background:'#1e293b', borderRadius:12, padding:20 }}>
                <div style={{ color:'#4ade80', fontSize:12, marginBottom:12 }}>✅ تم الجلب من {fetchResult.system} — {fetchResult.fetched_at}</div>
                <pre style={{ color:'#e2e8f0', fontSize:12, whiteSpace:'pre-wrap', wordBreak:'break-word', margin:0, direction:'ltr' }}>
                  {JSON.stringify(fetchResult.data, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* ── TAB: Chat ── */}
        {tab === 'chat' && (
          <div>
            <h2 style={{ color:'#f1f5f9', fontSize:16, marginBottom:8 }}>سؤال ذكي — ناطقة تجلب وتجيب</h2>
            <p style={{ color:'#64748b', fontSize:13, marginBottom:20 }}>
              اسأل بالعربية وناطقة ستجلب البيانات من الأنظمة المتصلة وتجيبك بدقة.
            </p>

            <div style={{ display:'flex', flexWrap:'wrap', gap:8, marginBottom:16 }}>
              {['ما ميزانية الربع الأول لعام 2026؟', 'كم عدد الموظفين في قسم المبيعات؟', 'ما حالة أوامر الشراء المعلّقة؟', 'ما إجمالي الفواتير هذا الشهر؟'].map(q => (
                <button key={q} onClick={() => setChatQ(q)} style={{ background:'#1e293b', border:'1px solid #334155', color:'#94a3b8', padding:'6px 14px', borderRadius:20, cursor:'pointer', fontSize:12, fontFamily:'Arial' }}>{q}</button>
              ))}
            </div>

            <div style={{ background:'#1e293b', borderRadius:12, padding:20 }}>
              <textarea value={chatQ} onChange={e => setChatQ(e.target.value)} rows={3} placeholder="اسأل ناطقة عن أي بيانات من الأنظمة المربوطة..."
                style={{ width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#f1f5f9', padding:'12px 16px', borderRadius:8, fontSize:14, boxSizing:'border-box', fontFamily:'Arial', resize:'vertical', outline:'none' }} />
              <button onClick={handleChat} disabled={chatLoading || !chatQ.trim()} style={{ marginTop:12, background: chatLoading ? '#334155' : '#7c3aed', color:'#fff', border:'none', padding:'12px 28px', borderRadius:8, cursor: chatLoading ? 'not-allowed' : 'pointer', fontWeight:700, fontFamily:'Arial' }}>
                {chatLoading ? '⏳ ناطقة تفكر...' : '🤖 اسأل ناطقة'}
              </button>
            </div>

            {chatAnswer && (
              <div style={{ background:'#1e293b', borderRadius:12, padding:24, marginTop:16, borderRight:'3px solid #7c3aed' }}>
                <div style={{ color:'#a78bfa', fontSize:12, marginBottom:12 }}>🤖 إجابة ناطقة</div>
                <div style={{ color:'#e2e8f0', fontSize:14, lineHeight:1.8, whiteSpace:'pre-wrap' }}>{chatAnswer}</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
