'use client'
import { useState, useEffect } from 'react'
import {
    LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { analyticsApi } from '@/lib/api'
import toast from 'react-hot-toast'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#f87171']
const GRADIENTS = {
    blue: ['#1e40af', '#3b82f6'],
    green: ['#065f46', '#10b981'],
    orange: ['#9a3412', '#f59e0b'],
    purple: ['#5b21b6', '#8b5cf6']
}

function Spin({ s = 18, c = '#fff' }) {
    return (
        <div style={{ width: s, height: s, border: `2px solid ${c}33`, borderTopColor: c, borderRadius: '50%', animation: 'spin .8s linear infinite' }} />
    )
}

export default function DashboardAnalytics({ isGlobal = false }: { isGlobal?: boolean }) {
    const [data, setData] = useState<any>(null)
    const [loading, setLoading] = useState(true)
    const [days, setDays] = useState(30)

    useEffect(() => {
        async function fetchStats() {
            setLoading(true)
            try {
                const { data: res } = await analyticsApi.getSummary(days)
                setData(res)
            } catch {
                toast.error('فشل تحميل الإحصائيات')
            } finally {
                setLoading(false)
            }
        }
        fetchStats()
    }, [days])

    if (loading && !data) {
        return (
            <div style={{ padding: 40, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, color: '#5b7fa6' }}>
                <Spin c="#3b82f6" /> جاري تحليل البيانات...
            </div>
        )
    }

    const cards = data?.cards || {}
    const growth = data?.growth || []
    const userStats = data?.user_stats || []
    const fileDist = data?.file_distribution || []

    const totalEmployees = cards.total_employees ?? 0
    const totalFiles = cards.total_files ?? 0
    const storageUsedBytes = cards.storage_used ?? 0
    const storageUsedMb = storageUsedBytes / (1024 * 1024)
    const activeProjects = cards.active_projects ?? 0

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, paddingBottom: 20 }}>
            {/* Header & Filter */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: 800, fontSize: 18, color: '#ccd9ef' }}>
                    {isGlobal ? 'تحليلات المنصة الشاملة' : 'مركز التحليلات والبيانات'}
                </div>
                <div style={{ display: 'flex', background: 'rgba(6,13,26,.6)', borderRadius: 12, padding: 4, border: '1px solid rgba(59,130,246,.1)' }}>
                    {[
                        { v: 7, l: '7 أيام' },
                        { v: 30, l: '30 يوم' },
                        { v: 90, l: '90 يوم' },
                    ].map(opt => (
                        <button
                            key={opt.v}
                            onClick={() => setDays(opt.v)}
                            style={{
                                padding: '6px 16px',
                                borderRadius: 9,
                                fontSize: 12,
                                fontWeight: 700,
                                border: 'none',
                                cursor: 'pointer',
                                transition: 'all .2s',
                                background: days === opt.v ? 'linear-gradient(135deg,#1e40af,#3b82f6)' : 'transparent',
                                color: days === opt.v ? '#fff' : '#4d6a8a'
                            }}
                        >
                            {opt.l}
                        </button>
                    ))}
                </div>
            </div>

            {/* Summary Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16 }}>
                {[
                    { icon: '👥', label: isGlobal ? 'إجمالي المستخدمين' : 'أعضاء الفريق', val: totalEmployees, col: '#3b82f6' },
                    { icon: '📄', label: 'إجمالي الملفات', val: totalFiles, col: '#10b981' },
                    { icon: '💾', label: 'المساحة المستخدمة', val: `${storageUsedMb.toFixed(1)} MB`, col: '#f59e0b' },
                    { icon: '📁', label: 'المشاريع النشطة', val: activeProjects, col: '#8b5cf6' },
                ].map((s, i) => (
                    <div key={i} className="card fu" style={{ padding: '20px', animationDelay: `${i * .05}s` }}>
                        <div style={{ fontSize: 24, marginBottom: 12 }}>{s.icon}</div>
                        <div style={{ fontSize: 28, fontWeight: 800, color: s.col, fontFamily: "'JetBrains Mono', monospace" }}>{s.val}</div>
                        <div style={{ fontSize: 11, color: '#5b7fa6', fontWeight: 600, marginTop: 4 }}>{s.label}</div>
                    </div>
                ))}
            </div>

            {/* Charts Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 20 }}>
                {/* Line Chart: Files Growth */}
                <div className="card fu" style={{ padding: 24, animationDelay: '.2s' }}>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 24, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: '#10b981' }}>📈</span> نمو الأرشفة وحركة الملفات
                    </div>
                    <div style={{ width: '100%', height: 280 }}>
                        <ResponsiveContainer>
                            <LineChart data={growth}>
                                <defs>
                                    <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(59,130,246,.05)" vertical={false} />
                                <XAxis dataKey="date" stroke="#2a4a6e" fontSize={10} tickFormatter={(v) => v.split('-').slice(1).join('/')} />
                                <YAxis stroke="#2a4a6e" fontSize={10} />
                                <Tooltip
                                    contentStyle={{ background: '#0c1829', border: '1px solid rgba(59,130,246,.2)', borderRadius: 10, fontSize: 12 }}
                                    itemStyle={{ color: '#fff' }}
                                />
                                <Line
                                    type="monotone"
                                    dataKey="count"
                                    stroke="#3b82f6"
                                    strokeWidth={3}
                                    dot={{ r: 4, fill: '#3b82f6', strokeWidth: 2, stroke: '#030711' }}
                                    activeDot={{ r: 6, strokeWidth: 0 }}
                                    animationDuration={1500}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Pie Chart: Distribution */}
                <div className="card fu" style={{ padding: 24, animationDelay: '.25s' }}>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 24, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: '#f59e0b' }}>📊</span> توزيع أنواع المستندات
                    </div>
                    <div style={{ width: '100%', height: 280 }}>
                        <ResponsiveContainer>
                            <PieChart>
                                <Pie
                                    data={fileDist}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={60}
                                    outerRadius={80}
                                    paddingAngle={5}
                                    dataKey="value"
                                    animationDuration={1500}
                                >
                                    {fileDist.map((entry: any, index: number) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip
                                    contentStyle={{ background: '#0c1829', border: '1px solid rgba(59,130,246,.2)', borderRadius: 10, fontSize: 12 }}
                                />
                                <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* Bar Chart: User Stats */}
            <div className="card fu" style={{ padding: 24, animationDelay: '.3s' }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: '#ccd9ef', marginBottom: 24, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: '#8b5cf6' }}>👥</span> إحصائيات عضوية الفريق والدعوات
                </div>
                <div style={{ width: '100%', height: 240 }}>
                    <ResponsiveContainer>
                        <BarChart data={userStats} layout="vertical" barSize={32}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(59,130,246,.05)" horizontal={false} />
                            <XAxis type="number" stroke="#2a4a6e" fontSize={10} />
                            <YAxis dataKey="name" type="category" stroke="#ccd9ef" fontSize={12} width={120} />
                            <Tooltip
                                cursor={{ fill: 'rgba(59,130,246,.05)' }}
                                contentStyle={{ background: '#0c1829', border: '1px solid rgba(59,130,246,.2)', borderRadius: 10, fontSize: 12 }}
                            />
                            <Bar
                                dataKey="value"
                                radius={[0, 8, 8, 0]}
                                animationDuration={1500}
                            >
                                {userStats.map((entry: any, index: number) => (
                                    <Cell key={`cell-${index}`} fill={index === 0 ? '#10b981' : '#f59e0b'} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            <style jsx global>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .fu { animation: fu .6s cubic-bezier(0.16, 1, 0.3, 1) both; }
        @keyframes fu {
          from { opacity: 0; transform: translateY(15px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
        </div>
    )
}
