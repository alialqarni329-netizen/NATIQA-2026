'use client'
import { useState, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { orgApi } from '@/lib/api'
import toast, { Toaster } from 'react-hot-toast'

function InvitationContent() {
    const router = useRouter()
    const searchParams = useSearchParams()
    const token = searchParams.get('token')

    const [invitation, setInvitation] = useState<any>(null)
    const [loading, setLoading] = useState(true)
    const [fullName, setFullName] = useState('')
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [submitting, setSubmitting] = useState(false)

    useEffect(() => {
        if (!token) {
            toast.error('رابط الدعوة غير صالح')
            setLoading(false)
            return
        }

        async function fetchInvitation() {
            try {
                const { data } = await orgApi.getInvitation(token as string)
                setInvitation(data)
            } catch (e: any) {
                toast.error(e.response?.data?.detail || 'رابط الدعوة منتهي الصلاحية أو غير صالح')
            } finally {
                setLoading(false)
            }
        }

        fetchInvitation()
    }, [token])

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault()
        if (password !== confirmPassword) {
            toast.error('كلمات المرور غير متطابقة')
            return
        }
        if (password.length < 8) {
            toast.error('كلمة المرور يجب أن تكون 8 رموز على الأقل')
            return
        }

        setSubmitting(true)
        try {
            await orgApi.acceptInvitation({
                token: token as string,
                full_name: fullName,
                password: password
            })
            toast.success('تم تفعيل الحساب بنجاح! جاري تحويلك لتسجيل الدخول...')
            setTimeout(() => router.push('/auth/login'), 2000)
        } catch (e: any) {
            toast.error(e.response?.data?.detail || 'فشل تفعيل الحساب')
        } finally {
            setSubmitting(false)
        }
    }

    if (loading) {
        return (
            <div style={{ minHeight: '100vh', background: '#030711', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontFamily: "'Tajawal', sans-serif" }}>
                جاري التحقق من الدعوة...
            </div>
        )
    }

    if (!invitation && !loading) {
        return (
            <div style={{ minHeight: '100vh', background: '#030711', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#fff', fontFamily: "'Tajawal', sans-serif", gap: 20 }}>
                <div style={{ fontSize: 64 }}>⚠️</div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>عذراً، رابط الدعوة هذا غير صالح أو انتهت صلاحيته.</div>
                <button onClick={() => router.push('/auth/login')} style={{ padding: '10px 24px', borderRadius: 10, background: 'rgba(59,130,246,.1)', border: '1px solid rgba(59,130,246,.2)', color: '#3b82f6', cursor: 'pointer' }}>
                    العودة لتسجيل الدخول
                </button>
            </div>
        )
    }

    return (
        <div className="fu" style={{ width: '100%', maxWidth: 450, background: 'rgba(12,24,41,0.6)', backdropFilter: 'blur(12px)', border: '1px solid rgba(59,130,246,0.15)', borderRadius: 24, padding: '40px 32px', boxShadow: '0 20px 40px rgba(0,0,0,0.4)' }}>
            <div style={{ textAlign: 'center', marginBottom: 32 }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>🤝</div>
                <h1 style={{ fontSize: 22, fontWeight: 800, color: '#fff', marginBottom: 8 }}>انضم إلى فريق {invitation.org_name}</h1>
                <p style={{ fontSize: 13, color: '#5b7fa6' }}>أنت مدعو للانضمام إلى منصة ناطقة (Natiqa) بصلاحية {invitation.role === 'org_admin' ? 'مسؤول' : 'موظف'}</p>
            </div>

            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                    <label style={{ display: 'block', fontSize: 12, color: '#5b7fa6', marginBottom: 8, fontWeight: 600 }}>الاسم الكامل</label>
                    <input
                        type="text"
                        value={fullName}
                        onChange={e => setFullName(e.target.value)}
                        required
                        dir="rtl"
                        style={{ width: '100%', background: 'rgba(6,13,26,0.7)', border: '1px solid rgba(59,130,246,0.15)', borderRadius: 12, padding: '14px 16px', color: '#ccd9ef', fontSize: 14, outline: 'none' }}
                    />
                </div>

                <div>
                    <label style={{ display: 'block', fontSize: 12, color: '#5b7fa6', marginBottom: 8, fontWeight: 600 }}>البريد الإلكتروني</label>
                    <input
                        type="email"
                        value={invitation.email}
                        disabled
                        style={{ width: '100%', background: 'rgba(6,13,26,0.4)', border: '1px solid rgba(59,130,246,0.05)', borderRadius: 12, padding: '14px 16px', color: '#3a5472', fontSize: 14, cursor: 'not-allowed' }}
                    />
                </div>

                <div>
                    <label style={{ display: 'block', fontSize: 12, color: '#5b7fa6', marginBottom: 8, fontWeight: 600 }}>تعيين كلمة المرور</label>
                    <input
                        type="password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        required
                        style={{ width: '100%', background: 'rgba(6,13,26,0.7)', border: '1px solid rgba(59,130,246,0.15)', borderRadius: 12, padding: '14px 16px', color: '#ccd9ef', fontSize: 14, outline: 'none' }}
                    />
                </div>

                <div>
                    <label style={{ display: 'block', fontSize: 12, color: '#5b7fa6', marginBottom: 8, fontWeight: 600 }}>تأكيد كلمة المرور</label>
                    <input
                        type="password"
                        value={confirmPassword}
                        onChange={e => setConfirmPassword(e.target.value)}
                        required
                        style={{ width: '100%', background: 'rgba(6,13,26,0.7)', border: '1px solid rgba(59,130,246,0.15)', borderRadius: 12, padding: '14px 16px', color: '#ccd9ef', fontSize: 14, outline: 'none' }}
                    />
                </div>

                <button
                    type="submit"
                    disabled={submitting}
                    style={{
                        marginTop: 8,
                        padding: '16px',
                        borderRadius: 14,
                        background: 'linear-gradient(135deg, #1e40af, #3b82f6)',
                        color: '#fff',
                        fontSize: 15,
                        fontWeight: 700,
                        border: 'none',
                        cursor: submitting ? 'not-allowed' : 'pointer',
                        boxShadow: '0 4px 15px rgba(59,130,246,0.3)',
                        transition: 'all 0.2s'
                    }}
                >
                    {submitting ? 'جاري تفعيل الحساب...' : 'تفعيل الحساب والانضمام'}
                </button>
            </form>

            <div style={{ marginTop: 24, textAlign: 'center', fontSize: 11, color: '#2a4a6e' }}>
                عن طريق الانضمام واصلت الموافقة على شروط الخدمة وسياسة الخصوصية لمنصة ناطقة.
            </div>
        </div>
    )
}

export default function AcceptInvitationPage() {
    return (
        <div style={{ minHeight: '100vh', background: '#030711', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, fontFamily: "'Tajawal', sans-serif" }}>
            <Toaster position="top-center" reverseOrder={false} />
            <Suspense fallback={<div style={{ color: '#fff' }}>جاري التحميل...</div>}>
                <InvitationContent />
            </Suspense>

            <style jsx global>{`
        @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap');
        
        .fu { animation: fu .6s cubic-bezier(0.16, 1, 0.3, 1) both; }
        @keyframes fu {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
        </div>
    )
}
