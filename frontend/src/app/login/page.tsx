'use client'
import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import toast from 'react-hot-toast'

const Spin = () => (
  <div style={{ width: 18, height: 18, border: '2px solid rgba(255,255,255,.25)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 1s linear infinite', flexShrink: 0 }} />
)

const EyeIcon = ({ open }: { open: boolean }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {open
      ? <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>
      : <><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><line x1="1" y1="1" x2="23" y2="23" /></>}
  </svg>
)

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:'Tajawal',sans-serif;direction:rtl;background:#060d1a;color:#ccd9ef}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1e3a5f;border-radius:4px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:translateY(0)}}
@keyframes lockPop{0%{transform:scale(0) rotate(-20deg);opacity:0}60%{transform:scale(1.15) rotate(4deg)}100%{transform:scale(1) rotate(0deg);opacity:1}}
@keyframes orbFloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-18px) scale(1.04)}}
@keyframes glowPulse{0%,100%{box-shadow:0 0 60px rgba(59,130,246,.35),0 0 120px rgba(59,130,246,.1)}50%{box-shadow:0 0 80px rgba(59,130,246,.55),0 0 160px rgba(59,130,246,.2)}}
@keyframes borderFlow{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes particleRise{0%{transform:translateY(0) scale(1);opacity:.7}100%{transform:translateY(-100px) scale(0);opacity:0}}
@keyframes scanLine{0%{transform:translateY(-100%)}100%{transform:translateY(400%)}}
@keyframes lockGlow{0%,100%{filter:drop-shadow(0 0 2px rgba(16,185,129,0))}60%{filter:drop-shadow(0 0 8px rgba(16,185,129,.7))}}
.field-label{font-size:11px;color:#5b7fa6;font-weight:700;letter-spacing:.08em;margin-bottom:7px;display:flex;align-items:center;gap:6px;text-transform:uppercase}
.field-wrap{position:relative;margin-bottom:18px}
.field-input{width:100%;background:rgba(6,13,26,.9);border:1.5px solid rgba(59,130,246,.15);border-radius:12px;padding:13px 44px 13px 14px;color:#ccd9ef;font-size:14px;outline:none;font-family:'Tajawal',sans-serif;transition:border-color .2s,box-shadow .2s,background .2s;direction:ltr;text-align:right}
.field-input::placeholder{color:#1e3a5f;font-family:'Tajawal',sans-serif}
.field-input:focus{border-color:rgba(59,130,246,.55);box-shadow:0 0 0 3px rgba(59,130,246,.07),inset 0 0 20px rgba(59,130,246,.03);background:rgba(8,18,36,.95)}
.field-icon{position:absolute;right:14px;top:50%;transform:translateY(-50%);pointer-events:none;display:flex;align-items:center}
.field-eye{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:#3a5472;cursor:pointer;transition:color .18s;background:none;border:none;padding:4px;display:flex;align-items:center}
.field-eye:hover{color:#8eaed4}
.submit-btn{width:100%;padding:15px;border-radius:13px;font-size:15px;font-weight:800;font-family:'Tajawal',sans-serif;cursor:pointer;border:none;position:relative;overflow:hidden;transition:transform .18s,box-shadow .18s;letter-spacing:.04em;color:#fff;margin-top:6px}
.submit-btn:not(:disabled):hover{transform:translateY(-2px);box-shadow:0 10px 40px rgba(59,130,246,.45)}
.submit-btn:active{transform:scale(.98)}
.submit-btn:disabled{cursor:not-allowed;opacity:.65}
`

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [pass, setPass] = useState('')
  const [totp, setTotp] = useState('')
  const [need2fa, setNeed2fa] = useState(false)
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [clock, setClock] = useState(new Date())
  const totpRef = useRef<HTMLInputElement>(null)

  const { login } = useAuthStore()
  const router = useRouter()

  useEffect(() => {
    if (typeof window !== 'undefined' && localStorage.getItem('access_token'))
      router.replace('/dashboard')
  }, [router])

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (need2fa) setTimeout(() => totpRef.current?.focus(), 80)
  }, [need2fa])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (loading) return
    setLoading(true)
    try {
      const res = await login(email, pass, need2fa ? totp : undefined)
      if (res?.require_2fa) {
        setNeed2fa(true)
        toast('أدخل رمز التحقق من تطبيق المصادقة', { icon: '🔐' })
      } else {
        toast.success('مرحباً بعودتك 👋')
        router.push('/dashboard')
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'بيانات الدخول غير صحيحة'
      toast.error(typeof msg === 'string' ? msg : 'فشل تسجيل الدخول')
      if (need2fa) setTotp('')
    } finally {
      setLoading(false)
    }
  }

  /* ── Particles ── */
  const pts = Array.from({ length: 20 }, (_, i) => ({
    x: (i * 19 + 5) % 96, y: (i * 31 + 9) % 90,
    size: 1.5 + (i % 3) * .8,
    dur: 2.5 + (i % 4) * .7, delay: i * .28,
  }))

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#060d1a', display: 'flex', position: 'relative', direction: 'rtl' }}>
      <style>{CSS}</style>

      {/* Grid */}
      <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', backgroundImage: 'linear-gradient(rgba(59,130,246,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,.022) 1px,transparent 1px)', backgroundSize: '52px 52px' }} />

      {/* Orbs */}
      <div style={{ position: 'absolute', top: '-12%', right: '-6%', width: 620, height: 620, borderRadius: '50%', background: 'radial-gradient(circle,rgba(59,130,246,.1) 0%,transparent 65%)', animation: 'orbFloat 9s ease-in-out infinite', pointerEvents: 'none' }} />
      <div style={{ position: 'absolute', bottom: '-18%', left: '-8%', width: 500, height: 500, borderRadius: '50%', background: 'radial-gradient(circle,rgba(16,185,129,.055) 0%,transparent 65%)', pointerEvents: 'none' }} />

      {/* Particles */}
      {pts.map((p, i) => (
        <div key={i} style={{
          position: 'absolute', left: p.x + '%', top: p.y + '%',
          width: p.size, height: p.size, borderRadius: '50%',
          background: 'rgba(59,130,246,.5)', pointerEvents: 'none',
          animation: `particleRise ${p.dur}s ${p.delay}s ease-in infinite`,
        }} />
      ))}

      {/* ══ LEFT — Brand panel ══ */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: '48px 72px', position: 'relative' }}>

        {/* Clock top-left */}
        <div style={{ position: 'absolute', top: 28, right: 32, fontFamily: "'JetBrains Mono'", fontSize: 11, color: '#1e3a5f', letterSpacing: '.06em' }}>
          {clock.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          &nbsp;·&nbsp;
          {clock.toLocaleDateString('ar-SA', { weekday: 'short', day: 'numeric', month: 'short' })}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 36, animation: 'fadeUp .7s .1s both' }}>

          {/* ① Main logo */}
          <div style={{ position: 'relative' }}>
            <div style={{
              width: 120, height: 120, borderRadius: 32,
              background: '#060d1a',
              border: '2px solid rgba(59,130,246,.2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: 18,
              boxShadow: '0 0 40px rgba(59,130,246,.15), inset 0 0 20px rgba(59,130,246,.05)',
              animation: 'glowPulse 4s ease-in-out infinite',
            }}>
              <img
                src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/static/logo.png`.replace('/api/static', '/static')}
                alt="Natiqa Logo"
                style={{ width: '100%', height: '100%', objectFit: 'contain', filter: 'drop-shadow(0 0 8px rgba(59,130,246,.5))' }}
              />
            </div>

            {/* Lock badge */}
            <div title="AES-256 · Zero Trust · 2FA" style={{
              position: 'absolute', bottom: -10, left: -10, width: 36, height: 36,
              borderRadius: '50%', background: '#060d1a', border: '2px solid rgba(16,185,129,.6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              animation: 'lockPop .5s .6s both',
              boxShadow: '0 0 15px rgba(16,185,129,.3)',
            }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'lockGlow 3.5s ease-in-out infinite' }}>
                <rect x="3" y="11" width="18" height="11" rx="3" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                <circle cx="12" cy="16.5" r="1.4" fill="#10b981" stroke="none" />
              </svg>
            </div>
          </div>

          {/* ② Title */}
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 60, fontWeight: 900, letterSpacing: '.08em', lineHeight: 1, color: '#e2ecff', textShadow: '0 0 40px rgba(59,130,246,.3)' }}>ناطقة</div>
            <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center' }}>
              <div style={{ height: 1, width: 28, background: 'rgba(59,130,246,.3)' }} />
              <span style={{ fontSize: 10, color: '#2a4a6e', letterSpacing: '.2em', fontFamily: "'JetBrains Mono'" }}>ENTERPRISE AI PLATFORM</span>
              <div style={{ height: 1, width: 28, background: 'rgba(59,130,246,.3)' }} />
            </div>
          </div>

          {/* ③ Feature list */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9, width: '100%', maxWidth: 340 }}>
            {[
              { i: '🔒', t: 'تشفير AES-256-GCM لجميع الملفات', c: 'rgba(16,185,129,.1)', b: 'rgba(16,185,129,.2)' },
              { i: '🧩', t: 'RAG متقدم + تقنية إخفاء البيانات', c: 'rgba(59,130,246,.08)', b: 'rgba(59,130,246,.18)' },
              { i: '👥', t: 'نظام الأدوار والصلاحيات RBAC', c: 'rgba(245,158,11,.07)', b: 'rgba(245,158,11,.18)' },
              { i: '🛡', t: 'مصادقة ثنائية 2FA + Zero Trust', c: 'rgba(139,92,246,.07)', b: 'rgba(139,92,246,.18)' },
            ].map((f, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '10px 16px', borderRadius: 11,
                background: f.c, border: `1px solid ${f.b}`,
                animation: `fadeUp .5s ${.35 + i * .1}s both`,
              }}>
                <span style={{ fontSize: 18, flexShrink: 0 }}>{f.i}</span>
                <span style={{ fontSize: 12, color: '#5b7fa6', lineHeight: 1.4 }}>{f.t}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ position: 'absolute', bottom: 24, fontSize: 10, color: '#1a2e47', fontFamily: "'JetBrains Mono'", letterSpacing: '.1em' }}>
          v4.0 · Anthropic Claude + Ollama LLM
        </div>
      </div>

      {/* ── Divider ── */}
      <div style={{ width: 1, background: 'linear-gradient(to bottom,transparent 5%,rgba(59,130,246,.1) 30%,rgba(59,130,246,.22) 50%,rgba(59,130,246,.1) 70%,transparent 95%)', flexShrink: 0 }} />

      {/* ══ RIGHT — Login form ══ */}
      <div style={{
        width: 500, display: 'flex', flexDirection: 'column', justifyContent: 'center',
        padding: '56px 56px', background: 'rgba(7,13,26,.7)', backdropFilter: 'blur(28px)',
        position: 'relative', overflow: 'hidden',
      }}>

        {/* Scan line effect */}
        <div style={{
          position: 'absolute', left: 0, right: 0, height: 1,
          background: 'linear-gradient(90deg,transparent,rgba(59,130,246,.15),transparent)',
          animation: 'scanLine 6s linear infinite', pointerEvents: 'none',
        }} />

        <div style={{ animation: 'fadeUp .6s .2s both' }}>

          {/* Header */}
          <div style={{ marginBottom: 34 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <div style={{ width: 4, height: 28, borderRadius: 2, background: 'linear-gradient(to bottom,#3b82f6,#10b981)' }} />
              <h2 style={{ fontSize: 26, fontWeight: 900, color: '#e2ecff' }}>
                {need2fa ? 'التحقق الثنائي' : 'تسجيل الدخول'}
              </h2>
            </div>
            <p style={{ fontSize: 12, color: '#3a5472', lineHeight: 1.7, paddingRight: 14 }}>
              {need2fa
                ? 'افتح تطبيق Google Authenticator وأدخل الرمز المكوّن من 6 أرقام'
                : 'أدخل بريدك الإلكتروني وكلمة المرور للوصول إلى لوحة التحكم'
              }
            </p>
          </div>

          <form onSubmit={handleSubmit}>
            {!need2fa ? (
              <>
                {/* Email field */}
                <div className="field-wrap">
                  <div className="field-label">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,12 2,6" /></svg>
                    البريد الإلكتروني
                  </div>
                  <input className="field-input" type="email" value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="user@company.com" required autoComplete="email"
                  />
                  <span className="field-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2a4a6e" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,12 2,6" /></svg>
                  </span>
                </div>

                {/* Password field */}
                <div className="field-wrap">
                  <div className="field-label">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
                    كلمة المرور
                  </div>
                  <input className="field-input" type={showPw ? 'text' : 'password'} value={pass}
                    onChange={e => setPass(e.target.value)}
                    placeholder="••••••••" required autoComplete="current-password"
                  />
                  <span className="field-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2a4a6e" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
                  </span>
                  <button type="button" className="field-eye" onClick={() => setShowPw(p => !p)}>
                    <EyeIcon open={showPw} />
                  </button>
                </div>
              </>
            ) : (
              /* 2FA */
              <div className="field-wrap" style={{ textAlign: 'center' }}>
                <div className="field-label" style={{ justifyContent: 'center' }}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
                  رمز التحقق
                </div>
                <input ref={totpRef} className="field-input" type="text" inputMode="numeric"
                  maxLength={6} value={totp}
                  onChange={e => setTotp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000" required
                  style={{
                    fontSize: 28, letterSpacing: '0.5em', textAlign: 'center', direction: 'ltr',
                    borderColor: 'rgba(16,185,129,.3)', fontFamily: "'JetBrains Mono'",
                  }}
                />
                {/* TOTP progress dots */}
                <div style={{ display: 'flex', justifyContent: 'center', gap: 6, marginTop: 10 }}>
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} style={{ width: 8, height: 8, borderRadius: '50%', background: totp.length > i ? '#10b981' : 'rgba(59,130,246,.15)', transition: 'background .15s' }} />
                  ))}
                </div>
                <button type="button" onClick={() => { setNeed2fa(false); setTotp('') }}
                  style={{ marginTop: 14, background: 'none', border: 'none', color: '#3a5472', fontSize: 12, cursor: 'pointer', fontFamily: "'Tajawal'" }}>
                  ← العودة لإدخال كلمة المرور
                </button>
              </div>
            )}

            {/* Submit button */}
            <button type="submit" className="submit-btn"
              disabled={loading || (need2fa ? totp.length !== 6 : !email.trim() || !pass.trim())}
              style={{
                background: loading
                  ? 'rgba(30,64,175,.4)'
                  : 'linear-gradient(135deg,#1e40af,#3b82f6,#2563eb)',
                backgroundSize: '200% 200%',
                animation: loading ? undefined : 'borderFlow 3s linear infinite',
              }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                {loading && <Spin />}
                <span>{loading ? 'جارٍ التحقق من هويتك...' : need2fa ? '✓ تأكيد الهوية' : '← دخول إلى المنصة'}</span>
              </div>
            </button>
          </form>

          {/* Security indicator */}
          <div style={{
            marginTop: 30, padding: '12px 16px', borderRadius: 10,
            background: 'rgba(16,185,129,.04)', border: '1px solid rgba(16,185,129,.13)',
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, animation: 'lockGlow 3.5s ease-in-out infinite' }}>
              <rect x="3" y="11" width="18" height="11" rx="3" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              <circle cx="12" cy="16.5" r="1.2" fill="#10b981" stroke="none" />
            </svg>
            <span style={{ fontSize: 11, color: '#10b981', opacity: .8, lineHeight: 1.5 }}>
              اتصال مشفّر TLS 1.3 · JWT + AES-256 · جلسات موثوقة
            </span>
          </div>

          {/* Footer */}
          <div style={{ marginTop: 24, textAlign: 'center', fontSize: 10, color: '#1a2e47', fontFamily: "'JetBrains Mono'", letterSpacing: '.08em' }}>
            NATIQA Enterprise · IAM v4.0 · {new Date().getFullYear()} ©
          </div>
        </div>
      </div>
    </div>
  )
}
