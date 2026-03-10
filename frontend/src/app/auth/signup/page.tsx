'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
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
html,body{height:100%;overflow:auto}
body{font-family:'Tajawal',sans-serif;direction:rtl;background:#060d1a;color:#ccd9ef}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1e3a5f;border-radius:4px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:translateY(0)}}
@keyframes orbFloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-18px) scale(1.04)}}
@keyframes glowPulse{0%,100%{box-shadow:0 0 60px rgba(99,102,241,.35),0 0 120px rgba(99,102,241,.1)}50%{box-shadow:0 0 80px rgba(99,102,241,.55),0 0 160px rgba(99,102,241,.2)}}
@keyframes borderFlow{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes particleRise{0%{transform:translateY(0) scale(1);opacity:.7}100%{transform:translateY(-100px) scale(0);opacity:0}}
@keyframes scanLine{0%{transform:translateY(-100%)}100%{transform:translateY(400%)}}
.field-label{font-size:11px;color:#5b7fa6;font-weight:700;letter-spacing:.08em;margin-bottom:7px;display:flex;align-items:center;gap:6px;text-transform:uppercase}
.field-wrap{position:relative;margin-bottom:16px}
.field-input{width:100%;background:rgba(6,13,26,.9);border:1.5px solid rgba(99,102,241,.15);border-radius:12px;padding:13px 44px 13px 14px;color:#ccd9ef;font-size:14px;outline:none;font-family:'Tajawal',sans-serif;transition:border-color .2s,box-shadow .2s,background .2s;direction:ltr;text-align:right}
.field-input::placeholder{color:#1e3a5f;font-family:'Tajawal',sans-serif}
.field-input:focus{border-color:rgba(99,102,241,.55);box-shadow:0 0 0 3px rgba(99,102,241,.07),inset 0 0 20px rgba(99,102,241,.03);background:rgba(8,18,36,.95)}
.field-select{width:100%;background:rgba(6,13,26,.9);border:1.5px solid rgba(99,102,241,.15);border-radius:12px;padding:13px 44px 13px 14px;color:#ccd9ef;font-size:14px;outline:none;font-family:'Tajawal',sans-serif;cursor:pointer;direction:rtl;-webkit-appearance:none;transition:border-color .2s}
.field-select:focus{border-color:rgba(99,102,241,.55);box-shadow:0 0 0 3px rgba(99,102,241,.07)}
.field-icon{position:absolute;right:14px;top:50%;transform:translateY(-50%);pointer-events:none;display:flex;align-items:center}
.field-eye{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:#3a5472;cursor:pointer;transition:color .18s;background:none;border:none;padding:4px;display:flex;align-items:center}
.field-eye:hover{color:#8eaed4}
.submit-btn{width:100%;padding:15px;border-radius:13px;font-size:15px;font-weight:800;font-family:'Tajawal',sans-serif;cursor:pointer;border:none;position:relative;overflow:hidden;transition:transform .18s,box-shadow .18s;letter-spacing:.04em;color:#fff;margin-top:6px}
.submit-btn:not(:disabled):hover{transform:translateY(-2px);box-shadow:0 10px 40px rgba(99,102,241,.45)}
.submit-btn:active{transform:scale(.98)}
.submit-btn:disabled{cursor:not-allowed;opacity:.65}
`

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'

export default function SignupPage() {
    const [form, setForm] = useState({
        email: '', full_name: '', password: '',
        business_name: '', document_type: 'cr', document_number: '',
        terms_accepted: false,
    })
    const [showPw, setShowPw] = useState(false)
    const [loading, setLoading] = useState(false)
    const [done, setDone] = useState(false)
    const router = useRouter()

    const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
        setForm(f => ({ ...f, [k]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value }))

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault()
        if (loading) return
        if (!form.terms_accepted) {
            toast.error('يجب الموافقة على الشروط والسياسات للمتابعة')
            return
        }
        setLoading(true)
        try {
            const res = await fetch(`${API_URL}/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(form),
            })
            const data = await res.json()
            if (!res.ok) {
                const msg = data?.detail
                toast.error(typeof msg === 'string' ? msg : 'فشل التسجيل، تحقق من البيانات')
                return
            }
            setDone(true)
            toast.success('تم التسجيل! تحقق من بريدك للتفعيل 📧')
        } catch {
            toast.error('تعذّر الاتصال بالخادم')
        } finally {
            setLoading(false)
        }
    }

    const pts = Array.from({ length: 16 }, (_, i) => ({
        x: (i * 19 + 5) % 96, y: (i * 31 + 9) % 90,
        size: 1.5 + (i % 3) * .8,
        dur: 2.5 + (i % 4) * .7, delay: i * .28,
    }))

    return (
        <div style={{ minHeight: '100vh', background: '#060d1a', display: 'flex', position: 'relative', direction: 'rtl', alignItems: 'center', justifyContent: 'center', padding: '32px 16px' }}>
            <style>{CSS}</style>

            {/* Grid */}
            <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', backgroundImage: 'linear-gradient(rgba(99,102,241,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(99,102,241,.022) 1px,transparent 1px)', backgroundSize: '52px 52px' }} />

            {/* Orbs */}
            <div style={{ position: 'fixed', top: '-12%', right: '-6%', width: 620, height: 620, borderRadius: '50%', background: 'radial-gradient(circle,rgba(99,102,241,.09) 0%,transparent 65%)', animation: 'orbFloat 9s ease-in-out infinite', pointerEvents: 'none' }} />
            <div style={{ position: 'fixed', bottom: '-18%', left: '-8%', width: 500, height: 500, borderRadius: '50%', background: 'radial-gradient(circle,rgba(16,185,129,.05) 0%,transparent 65%)', pointerEvents: 'none' }} />

            {/* Particles */}
            {pts.map((p, i) => (
                <div key={i} style={{ position: 'fixed', left: p.x + '%', top: p.y + '%', width: p.size, height: p.size, borderRadius: '50%', background: 'rgba(99,102,241,.5)', pointerEvents: 'none', animation: `particleRise ${p.dur}s ${p.delay}s ease-in infinite` }} />
            ))}

            {/* Card */}
            <div style={{ position: 'relative', zIndex: 10, width: '100%', maxWidth: 540, background: 'rgba(7,13,26,.85)', backdropFilter: 'blur(28px)', borderRadius: 24, border: '1px solid rgba(99,102,241,.12)', padding: '44px 48px', animation: 'fadeUp .6s .1s both', boxShadow: '0 24px 80px rgba(0,0,0,.5)' }}>

                {/* Scan line */}
                <div style={{ position: 'absolute', left: 0, right: 0, height: 1, background: 'linear-gradient(90deg,transparent,rgba(99,102,241,.15),transparent)', animation: 'scanLine 6s linear infinite', pointerEvents: 'none' }} />

                {done ? (
                    /* ── Success State ── */
                    <div style={{ textAlign: 'center', padding: '20px 0', animation: 'fadeUp .4s both' }}>
                        <div style={{ fontSize: 64, marginBottom: 20 }}>📧</div>
                        <h2 style={{ fontSize: 24, fontWeight: 900, color: '#e2ecff', marginBottom: 12 }}>تم إرسال رمز التحقق!</h2>
                        <p style={{ color: '#5b7fa6', lineHeight: 1.8, marginBottom: 28 }}>
                            طلبك قيد المراجعة من فريق ناطقة.<br />تحقق من بريدك الإلكتروني لتفعيل حسابك، ثم انتظر موافقة المسؤول.
                        </p>
                        <button onClick={() => router.push('/login')} style={{ background: 'linear-gradient(135deg,#4338ca,#6366f1)', border: 'none', color: '#fff', padding: '14px 36px', borderRadius: 12, fontSize: 15, fontWeight: 800, fontFamily: "'Tajawal'", cursor: 'pointer' }}>
                            العودة لتسجيل الدخول ←
                        </button>
                    </div>
                ) : (
                    <>
                        {/* Header */}
                        <div style={{ marginBottom: 30 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
                                <div style={{
                                    width: 48, height: 48, borderRadius: 14,
                                    background: '#060d1a',
                                    border: '1px solid rgba(99,102,241,.2)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    padding: 8,
                                    animation: 'glowPulse 4s ease-in-out infinite',
                                    boxShadow: '0 0 20px rgba(99,102,241,.15)'
                                }}>
                                    <img
                                        src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/static/logo.png`.replace('/api/static', '/static')}
                                        alt="Natiqa Logo"
                                        style={{ width: '100%', height: '100%', objectFit: 'contain', filter: 'drop-shadow(0 0 4px rgba(99,102,241,.5))' }}
                                    />
                                </div>
                                <div>
                                    <h1 style={{ fontSize: 22, fontWeight: 900, color: '#e2ecff', lineHeight: 1.2 }}>تسجيل منشأة جديدة</h1>
                                    <p style={{ fontSize: 11, color: '#2a4a6e', fontFamily: "'JetBrains Mono'", letterSpacing: '.1em' }}>NATIQA ENTERPRISE SIGNUP</p>
                                </div>
                            </div>
                            <p style={{ fontSize: 12, color: '#3a5472', lineHeight: 1.7, marginTop: 10 }}>
                                أنشئ حسابك المؤسسي للوصول إلى منصة ناطقة للذكاء الاصطناعي. يتطلب بريدًا مؤسسيًا وسجل تجاري.
                            </p>
                        </div>

                        <form onSubmit={handleSubmit}>
                            {/* Company Name */}
                            <div className="field-wrap">
                                <div className="field-label">
                                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z" /><line x1="3" y1="6" x2="21" y2="6" /><path d="M16 10a4 4 0 01-8 0" /></svg>
                                    اسم الشركة / المنشأة
                                </div>
                                <input id="business_name" className="field-input" type="text" value={form.business_name}
                                    onChange={set('business_name')} placeholder="شركة الأفق للتقنية" required minLength={2} />
                                <span className="field-icon">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2a4a6e" strokeWidth="2"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z" /><line x1="3" y1="6" x2="21" y2="6" /></svg>
                                </span>
                            </div>

                            {/* Full Name */}
                            <div className="field-wrap">
                                <div className="field-label">
                                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                                    الاسم الكامل (المسؤول)
                                </div>
                                <input id="full_name" className="field-input" type="text" value={form.full_name}
                                    onChange={set('full_name')} placeholder="محمد أحمد العتيبي" required minLength={2} />
                                <span className="field-icon">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2a4a6e" strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                                </span>
                            </div>

                            {/* Email */}
                            <div className="field-wrap">
                                <div className="field-label">
                                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,12 2,6" /></svg>
                                    البريد المؤسسي
                                </div>
                                <input id="email" className="field-input" type="email" value={form.email}
                                    onChange={set('email')} placeholder="admin@yourcompany.com" required autoComplete="email" />
                                <span className="field-icon">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2a4a6e" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,12 2,6" /></svg>
                                </span>
                            </div>

                            {/* Document Type + Number */}
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 12, marginBottom: 16 }}>
                                <div>
                                    <div className="field-label">نوع الوثيقة</div>
                                    <div style={{ position: 'relative' }}>
                                        <select id="document_type" className="field-select" value={form.document_type} onChange={set('document_type')}>
                                            <option value="cr">سجل تجاري (CR)</option>
                                            <option value="freelance">وثيقة عمل حر</option>
                                        </select>
                                        <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: '#2a4a6e' }}>▾</span>
                                    </div>
                                </div>
                                <div>
                                    <div className="field-label">رقم الوثيقة</div>
                                    <input id="document_number" className="field-input" type="text" value={form.document_number}
                                        onChange={set('document_number')} placeholder="1010XXXXXX" required minLength={5} />
                                </div>
                            </div>

                            {/* Password */}
                            <div className="field-wrap">
                                <div className="field-label">
                                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
                                    كلمة المرور
                                </div>
                                <input id="password" className="field-input" type={showPw ? 'text' : 'password'} value={form.password}
                                    onChange={set('password')} placeholder="8+ أحرف وأرقام" required minLength={8} autoComplete="new-password" />
                                <span className="field-icon">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2a4a6e" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
                                </span>
                                <button type="button" className="field-eye" onClick={() => setShowPw(p => !p)}>
                                    <EyeIcon open={showPw} />
                                </button>
                            </div>

                            {/* Terms Checkbox */}
                            <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-start', gap: 10, padding: '0 4px' }}>
                                <input
                                    id="terms_accepted"
                                    type="checkbox"
                                    checked={form.terms_accepted}
                                    onChange={set('terms_accepted')}
                                    style={{
                                        marginTop: 4,
                                        width: 16,
                                        height: 16,
                                        accentColor: '#6366f1',
                                        cursor: 'pointer',
                                        background: 'rgba(6,13,26,.9)',
                                        border: '1.5px solid rgba(99,102,241,.3)'
                                    }}
                                />
                                <label htmlFor="terms_accepted" style={{ fontSize: 13, color: '#5b7fa6', lineHeight: 1.5, cursor: 'pointer' }}>
                                    أوافق على <a href="/docs/privacy-policy.pdf" target="_blank" style={{ color: '#6366f1', textDecoration: 'none', borderBottom: '1px solid rgba(99,102,241,.3)', fontWeight: 700 }}>سياسة الخصوصية</a> و <a href="/docs/acceptable-use.pdf" target="_blank" style={{ color: '#6366f1', textDecoration: 'none', borderBottom: '1px solid rgba(99,102,241,.3)', fontWeight: 700 }}>سياسة الاستخدام المقبول</a>
                                </label>
                            </div>

                            {/* Submit */}
                            <button type="submit" id="signup-submit" className="submit-btn"
                                disabled={loading || !form.terms_accepted || !form.email.trim() || !form.password.trim() || !form.business_name.trim() || !form.document_number.trim()}
                                style={{
                                    background: (loading || !form.terms_accepted) ? 'rgba(67,56,202,.4)' : 'linear-gradient(135deg,#4338ca,#6366f1,#818cf8)',
                                    backgroundSize: '200% 200%',
                                    animation: (loading || !form.terms_accepted) ? undefined : 'borderFlow 3s linear infinite',
                                }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                                    {loading && <Spin />}
                                    <span>{loading ? 'جارٍ إنشاء الحساب...' : '← إنشاء حساب المنشأة'}</span>
                                </div>
                            </button>
                        </form>

                        {/* Link to login */}
                        <div style={{ marginTop: 24, textAlign: 'center' }}>
                            <span style={{ fontSize: 13, color: '#3a5472' }}>لديك حساب بالفعل؟ </span>
                            <a href="/login" style={{ fontSize: 13, color: '#6366f1', fontWeight: 700, textDecoration: 'none' }}>تسجيل الدخول ←</a>
                        </div>

                        {/* Security note */}
                        <div style={{ marginTop: 20, padding: '10px 14px', borderRadius: 10, background: 'rgba(16,185,129,.04)', border: '1px solid rgba(16,185,129,.13)', display: 'flex', alignItems: 'center', gap: 10 }}>
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                                <rect x="3" y="11" width="18" height="11" rx="3" /><path d="M7 11V7a5 5 0 0110 0v4" /><circle cx="12" cy="16.5" r="1.2" fill="#10b981" stroke="none" />
                            </svg>
                            <span style={{ fontSize: 11, color: '#10b981', opacity: .8, lineHeight: 1.5 }}>
                                بياناتك مشفّرة بـ AES-256 · Data Masking تلقائي قبل أي إرسال خارجي
                            </span>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
