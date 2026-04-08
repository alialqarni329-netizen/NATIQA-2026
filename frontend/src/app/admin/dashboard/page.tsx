'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore, useAuthHydrated } from '@/lib/store'
import { adminApi } from '@/lib/api'
import toast from 'react-hot-toast'
import NotificationBell from '@/components/NotificationBell'
import DashboardAnalytics from '@/app/dashboard/DashboardAnalytics'

// ─── Icons (Inline SVGs for performance & reliability) ────────────────
const UsersIcon = ({ size = 20 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
)
const BuildingIcon = ({ size = 20 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="4" y="2" width="16" height="20" rx="2" ry="2" /><line x1="9" y1="22" x2="9" y2="2" /><line x1="15" y1="22" x2="15" y2="2" />
        <line x1="4" y1="6" x2="9" y2="6" /><line x1="4" y1="10" x2="9" y2="10" /><line x1="4" y1="14" x2="9" y2="14" />
        <line x1="15" y1="6" x2="20" y2="6" /><line x1="15" y1="10" x2="20" y2="10" /><line x1="15" y1="14" x2="20" y2="14" />
    </svg>
)
const FileTextIcon = ({ size = 20 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
    </svg>
)
const RefreshIcon = ({ size = 18 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M23 4v6h-6" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
)
const DownloadIcon = ({ size = 18 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v4M7 10l5 5 5-5M12 15V3" />
    </svg>
)
const ChevronDownIcon = ({ size = 16 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="6 9 12 15 18 9" />
    </svg>
)

type Stats = {
    users: { total: number; pending: number };
    organizations: { total: number; active: number };
    documents: { total: number };
}

type Org = {
    id: string;
    name: string;
    document_type: string;
    document_number: string;
    subscription_plan: string;
    is_active: boolean;
    created_at: string;
}

export default function AdminDashboard() {
    const router = useRouter()
    const hydrated = useAuthHydrated()
    const user = useAuthStore((state) => state.user)
    const [stats, setStats] = useState<Stats | null>(null)
    const [orgs, setOrgs] = useState<Org[]>([])
    const [loading, setLoading] = useState(true)
    const [fetchError, setFetchError] = useState<string | null>(null)
    const [exporting, setExporting] = useState<string | null>(null)
    const [showExportMenu, setShowExportMenu] = useState(false)
    const [view, setView] = useState<'overview' | 'analytics'>('overview')

    useEffect(() => {
        if (!hydrated) return
        if (user?.role !== 'admin' && user?.role !== 'super_admin') {
            toast.error('Access Denied')
            router.push('/dashboard')
            return
        }
        fetchData()
    }, [hydrated, user, router])

    if (!hydrated) {
        return (
            <div className="min-h-screen bg-[#0a0a0c] flex items-center justify-center">
                <div className="w-10 h-10 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
            </div>
        )
    }

    const fetchData = async () => {
        setLoading(true)
        setFetchError(null)
        try {
            // First attempt to use /api/admin/stats which is for Organization stats
            // and /admin-portal/api/stats for global platform stats if needed.
            // dashboard/page.tsx uses adminApi.stats() which is /api/admin/stats
            const [sRes, oRes] = await Promise.all([
                adminApi.stats(),
                adminApi.listOrganizations()
            ])
            setStats(sRes.data)
            setOrgs(oRes.data)
        } catch (err: any) {
            console.error('Admin data fetch error:', err?.response?.status, err)

            // Silently try fallback to portalStats if main admin stats fail
            try {
                const sRes = await adminApi.portalStats()
                setStats(sRes.data)
                const oRes = await adminApi.listOrganizations()
                setOrgs(oRes.data)
            } catch (fallbackErr: any) {
                toast.error('فشل تحميل بيانات الإدارة')
                setFetchError(`فشل في تحميل البيانات (Status: ${err?.response?.status || 'Unknown'})`)
            }
        } finally {
            setLoading(false)
        }
    }

    const handleExport = async (format: 'word' | 'pptx' | 'powerbi') => {
        setExporting(format)
        setShowExportMenu(false)
        try {
            if (format === 'powerbi') {
                const res = await adminApi.exportPowerBi()
                const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
                const url = window.URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `Natiqa_PowerBI_Feed_${new Date().toISOString().split('T')[0]}.json`
                a.click()
                toast.success('تم تصدير ملف Power BI بنجاح')
            } else {
                const res = format === 'word' ? await adminApi.exportWord() : await adminApi.exportPptx()
                const url = window.URL.createObjectURL(new Blob([res.data]))
                const a = document.createElement('a')
                a.href = url
                a.download = `Natiqa_Export_${new Date().toISOString().split('T')[0]}.${format === 'word' ? 'docx' : 'pptx'}`
                a.click()
                toast.success(`تم تصدير ملف ${format.toUpperCase()} بنجاح`)
            }
        } catch (err) {
            toast.error('فشل التصدير، حاول مرة أخرى')
        } finally {
            setExporting(null)
        }
    }

    if (!user || (user?.role !== 'admin' && user?.role !== 'super_admin')) {
        return (
            <div className="min-h-screen bg-[#0a0a0c] flex items-center justify-center">
                <div className="w-10 h-10 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-[#0a0a0c] text-slate-200 p-6 md:p-10 font-sans selection:bg-blue-500/30">
            {/* ─── Header ────────────────────────────────────────── */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-10">
                <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-center p-2 shadow-lg shadow-blue-500/10">
                        <img src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/static/logo.png`.replace('/api/static', '/static')} alt="Logo" className="w-full h-full object-contain" />
                    </div>
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
                            لوحة تحكم المسؤول
                        </h1>
                        <p className="text-slate-500 mt-1">إدارة المنصة والمؤسسات والمستخدمين</p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    <button
                        onClick={fetchData}
                        disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 bg-slate-800/50 hover:bg-slate-700/50 rounded-xl border border-slate-700/50 transition-all active:scale-95 disabled:opacity-50"
                    >
                        {loading ? (
                            <span className="animate-spin">
                                <RefreshIcon size={18} />
                            </span>
                        ) : (
                            <RefreshIcon size={18} />
                        )}
                        <span className="hidden sm:inline">تحديث</span>
                    </button>

                    <div className="relative">
                        <button
                            onClick={() => setShowExportMenu(!showExportMenu)}
                            disabled={!!exporting}
                            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl transition-all active:scale-95 disabled:opacity-50 shadow-lg shadow-indigo-600/20"
                        >
                            {exporting ? (
                                <span className="animate-spin">
                                    <RefreshIcon size={18} />
                                </span>
                            ) : (
                                <DownloadIcon size={18} />
                            )}
                            <span>تصدير البيانات</span>
                            <ChevronDownIcon size={14} />
                        </button>

                        {showExportMenu && (
                            <div className="absolute left-0 top-full mt-2 w-56 bg-[#16161a] border border-slate-800 rounded-xl shadow-2xl z-[100] overflow-hidden animate-in fade-in slide-in-from-top-2">
                                <button onClick={() => handleExport('word')} className="w-full text-right px-4 py-3 hover:bg-slate-800 flex items-center justify-between group transition-colors">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center text-blue-500">W</div>
                                        <span className="text-sm">تقرير Word (.docx)</span>
                                    </div>
                                </button>
                                <button onClick={() => handleExport('pptx')} className="w-full text-right px-4 py-3 hover:bg-slate-800 flex items-center justify-between group transition-colors border-t border-slate-800/50">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 rounded-lg bg-orange-500/10 flex items-center justify-center text-orange-500">P</div>
                                        <span className="text-sm">عرض PPTX (.pptx)</span>
                                    </div>
                                </button>
                                <button onClick={() => handleExport('powerbi')} className="w-full text-right px-4 py-3 hover:bg-slate-800 flex items-center justify-between group transition-colors border-t border-slate-800/50">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 rounded-lg bg-yellow-500/10 flex items-center justify-center text-yellow-500">PI</div>
                                        <span className="text-sm">تغذية Power BI (JSON)</span>
                                    </div>
                                </button>
                            </div>
                        )}
                    </div>

                    <NotificationBell />
                </div>
            </div>

            {/* ─── View Switcher ────────────────────────────────── */}
            <div className="flex gap-4 mb-8 bg-slate-900/50 p-1 rounded-xl border border-slate-800 w-fit">
                <button
                    onClick={() => setView('overview')}
                    className={`px-6 py-2 rounded-lg text-sm font-bold transition-all ${view === 'overview' ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20' : 'text-slate-500 hover:text-slate-300'}`}
                >
                    نظرة عامة
                </button>
                <button
                    onClick={() => setView('analytics')}
                    className={`px-6 py-2 rounded-lg text-sm font-bold transition-all ${view === 'analytics' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20' : 'text-slate-500 hover:text-slate-300'}`}
                >
                    التحليلات المتقدمة
                </button>
            </div>

            {fetchError ? (
                <div className="flex flex-col items-center justify-center py-20 bg-slate-900/50 rounded-2xl border border-red-500/20">
                    <div className="w-16 h-16 bg-red-500/10 text-red-500 flex items-center justify-center rounded-full mb-4">
                        <svg width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    </div>
                    <h3 className="text-xl font-bold text-white mb-2">إخفاق في تحميل البيانات</h3>
                    <p className="text-slate-400 mb-6">{fetchError}</p>
                    <button onClick={fetchData} className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg flex items-center gap-2 transition-colors">
                        <RefreshIcon size={18} />
                        إعادة المحاولة
                    </button>
                </div>
            ) : loading && !stats ? (
                <div className="flex items-center justify-center py-20">
                    <div className="flex flex-col items-center gap-4">
                        <div className="w-10 h-10 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin"></div>
                        <p className="text-slate-400">جاري تحميل البيانات...</p>
                    </div>
                </div>
            ) : view === 'analytics' ? (
                <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                    <DashboardAnalytics isGlobal={true} />
                </div>
            ) : (
                <>
                    {/* ─── Stats Grid ────────────────────────────────────── */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                        <StatCard
                            title="إجمالي المستخدمين"
                            value={stats?.users.total || 0}
                            subValue={`${stats?.users.pending || 0} في انتظار الموافقة`}
                            icon={<UsersIcon size={24} />}
                            color="blue"
                        />
                        <StatCard
                            title="إجمالي الشركات"
                            value={stats?.organizations.total || 0}
                            subValue={`${stats?.organizations.active || 0} شركة نشطة`}
                            icon={<BuildingIcon size={24} />}
                            color="indigo"
                        />
                        <StatCard
                            title="المستندات المعالجة"
                            value={stats?.documents.total || 0}
                            subValue="عبر كافة المؤسسات"
                            icon={<FileTextIcon size={24} />}
                            color="emerald"
                        />
                    </div>

                    {/* ─── Organizations Table ───────────────────────────── */}
                    <div className="bg-[#111114] rounded-2xl border border-slate-800/50 overflow-hidden shadow-2xl">
                        <div className="p-6 border-b border-slate-800/50 flex items-center justify-between">
                            <h2 className="text-xl font-semibold">المؤسسات المسجلة</h2>
                            <span className="text-xs font-medium px-2 py-1 bg-blue-500/10 text-blue-400 rounded-lg border border-blue-500/20">
                                {orgs.length} مؤسسة
                            </span>
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full text-right">
                                <thead>
                                    <tr className="bg-slate-800/20 text-slate-400 text-sm uppercase tracking-wider">
                                        <th className="px-6 py-4 font-medium">الشركة</th>
                                        <th className="px-6 py-4 font-medium">الاشتراك</th>
                                        <th className="px-6 py-4 font-medium">تاريخ التسجيل</th>
                                        <th className="px-6 py-4 font-medium">الحالة</th>
                                        <th className="px-6 py-4 font-medium">الإجراءات</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-800/50">
                                    {orgs.map((org) => (
                                        <tr key={org.id} className="hover:bg-slate-800/20 transition-colors group">
                                            <td className="px-6 py-5">
                                                <div className="flex flex-col">
                                                    <span className="font-semibold text-slate-100">{org.name}</span>
                                                    <span className="text-xs text-slate-500 mt-0.5 uppercase">{org.document_type}: {org.document_number}</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-5">
                                                <span className={`text-xs px-2.5 py-1 rounded-full font-medium border ${getPlanStyle(org.subscription_plan)}`}>
                                                    {org.subscription_plan}
                                                </span>
                                            </td>
                                            <td className="px-6 py-5 text-slate-400 text-sm">
                                                {new Date(org.created_at).toLocaleDateString('ar-SA')}
                                            </td>
                                            <td className="px-6 py-5">
                                                <div className="flex items-center gap-2">
                                                    <div className={`w-2 h-2 rounded-full ${org.is_active ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-slate-600'}`}></div>
                                                    <span className="text-sm font-medium">{org.is_active ? 'نشط' : 'غير نشط'}</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-5 text-left">
                                                <button className="text-slate-400 hover:text-blue-400 transition-colors text-sm font-medium opacity-0 group-hover:opacity-100">
                                                    إدارة التفاصيل
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                    {orgs.length === 0 && !loading && (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-10 text-center text-slate-500">
                                                لا توجد مؤسسات مسجلة حالياً
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

function StatCard({ title, value, subValue, icon, color }: { title: string; value: number | string; subValue: string; icon: React.ReactNode; color: 'blue' | 'indigo' | 'emerald' }) {
    const colors = {
        blue: 'from-blue-500/20 to-blue-600/5 text-blue-400 border-blue-500/20',
        indigo: 'from-indigo-500/20 to-indigo-600/5 text-indigo-400 border-indigo-500/20',
        emerald: 'from-emerald-500/20 to-emerald-600/5 text-emerald-400 border-emerald-500/20',
    }

    return (
        <div className={`bg-gradient-to-br ${colors[color]} p-6 rounded-2xl border backdrop-blur-sm shadow-xl transition-all hover:translate-y-[-2px]`}>
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-slate-400 text-sm font-medium mb-1">{title}</p>
                    <p className="text-4xl font-bold tracking-tight text-white mb-2">{value}</p>
                    <p className="text-xs opacity-70">{subValue}</p>
                </div>
                <div className={`p-3 bg-white/5 rounded-xl border border-white/10 ${colors[color].split(' ')[2]}`}>
                    {icon}
                </div>
            </div>
        </div>
    )
}

function getPlanStyle(plan: string) {
    switch (plan.toLowerCase()) {
        case 'free': return 'bg-slate-500/10 text-slate-400 border-slate-500/20'
        case 'trial': return 'bg-blue-500/10 text-blue-400 border-blue-500/20'
        case 'pro': return 'bg-amber-500/10 text-amber-400 border-amber-500/20'
        case 'enterprise': return 'bg-purple-500/10 text-purple-400 border-purple-500/20'
        default: return 'bg-slate-500/10 text-slate-400 border-slate-500/20'
    }
}
