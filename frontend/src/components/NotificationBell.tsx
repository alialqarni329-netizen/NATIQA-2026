'use client'
import { useState, useEffect, useRef } from 'react'
import { notificationApi } from '@/lib/api'
import toast from 'react-hot-toast'

export default function NotificationBell() {
    const [notifs, setNotifs] = useState<any[]>([])
    const [open, setOpen] = useState(false)
    const [loading, setLoading] = useState(false)
    const menuRef = useRef<HTMLDivElement>(null)

    const unreadCount = notifs.filter(n => !n.is_read).length

    const loadNotifs = async () => {
        try {
            const { data } = await notificationApi.list()
            setNotifs(data)
        } catch (err) {
            console.error('Failed to load notifications', err)
        }
    }

    useEffect(() => {
        loadNotifs()
        const interval = setInterval(loadNotifs, 30000) // Poll every 30s
        return () => clearInterval(interval)
    }, [])

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                setOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    const handleMarkRead = async (id: string) => {
        try {
            await notificationApi.markRead(id)
            setNotifs(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
        } catch (err) {
            toast.error('فشل تحديث الحالة')
        }
    }

    const handleMarkAllRead = async () => {
        try {
            setLoading(true)
            await notificationApi.markAllRead()
            setNotifs(prev => prev.map(n => ({ ...n, is_read: true })))
            toast.success('تم تحديد الكل كمقروء')
        } catch (err) {
            toast.error('فشل التحديث')
        } finally {
            setLoading(false)
        }
    }

    const getTimeLabel = (dateStr: string) => {
        const d = new Date(dateStr)
        return d.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
    }

    return (
        <div style={{ position: 'relative' }} ref={menuRef}>
            <button
                onClick={() => setOpen(!open)}
                style={{
                    background: 'none', border: 'none', cursor: 'pointer', position: 'relative',
                    padding: 8, color: open ? '#3b82f6' : '#5b7fa6', transition: 'all .2s'
                }}
                onMouseOver={e => e.currentTarget.style.color = '#3b82f6'}
                onMouseOut={e => e.currentTarget.style.color = open ? '#3b82f6' : '#5b7fa6'}
            >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                    <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                </svg>
                {unreadCount > 0 && (
                    <span style={{
                        position: 'absolute', top: 6, right: 6, width: 8, height: 8,
                        background: '#ef4444', borderRadius: '50%', border: '2px solid #060d1a',
                        animation: 'pulse 2s infinite'
                    }} />
                )}
            </button>

            {open && (
                <div style={{
                    position: 'absolute', top: 'calc(100% + 10px)', left: 0, width: 320,
                    background: 'rgba(12, 24, 41, 0.98)', border: '1px solid rgba(59, 130, 246, 0.2)',
                    borderRadius: 14, boxShadow: '0 20px 50px rgba(0,0,0,0.6)', zIndex: 100,
                    overflow: 'hidden', animation: 'slideUp 0.2s cubic-bezier(.22,.68,0,1.1)'
                }}>
                    <div style={{
                        padding: '14px 16px', borderBottom: '1px solid rgba(59, 130, 246, 0.1)',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        background: 'rgba(59, 130, 246, 0.05)'
                    }}>
                        <span style={{ fontSize: 13, fontWeight: 800, color: '#e2ecff' }}>الإشعارات</span>
                        {unreadCount > 0 && (
                            <button
                                onClick={handleMarkAllRead}
                                disabled={loading}
                                style={{ background: 'none', border: 'none', color: '#3b82f6', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }}
                            >
                                تحديد الكل كمقروء
                            </button>
                        )}
                    </div>

                    <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                        {notifs.length === 0 ? (
                            <div style={{ padding: 40, textAlign: 'center', color: '#2a4a6e', fontSize: 12 }}>
                                لا توجد إشعارات حالياً
                            </div>
                        ) : (
                            notifs.map(n => (
                                <div
                                    key={n.id}
                                    onClick={() => !n.is_read && handleMarkRead(n.id)}
                                    style={{
                                        padding: '14px 16px', borderBottom: '1px solid rgba(59, 130, 246, 0.05)',
                                        background: n.is_read ? 'transparent' : 'rgba(59, 130, 246, 0.04)',
                                        cursor: n.is_read ? 'default' : 'pointer', transition: 'all .2s',
                                        position: 'relative'
                                    }}
                                    onMouseOver={e => !n.is_read && (e.currentTarget.style.background = 'rgba(59, 130, 246, 0.08)')}
                                    onMouseOut={e => !n.is_read && (e.currentTarget.style.background = 'rgba(59, 130, 246, 0.04)')}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                                        <span style={{
                                            fontSize: 10, fontWeight: 900, textTransform: 'uppercase',
                                            color: n.type === 'error' ? '#f87171' : n.type === 'success' ? '#10b981' : '#3b82f6'
                                        }}>
                                            {n.type === 'error' ? 'تنبيه' : n.type === 'success' ? 'نجاح' : 'معلومات'}
                                        </span>
                                        <span style={{ fontSize: 9, color: '#2a4a6e' }}>{getTimeLabel(n.created_at)}</span>
                                    </div>
                                    <div style={{ fontSize: 12, fontWeight: n.is_read ? 400 : 700, color: n.is_read ? '#5b7fa6' : '#ccd9ef', lineHeight: 1.5 }}>
                                        {n.title}
                                    </div>
                                    <div style={{ fontSize: 11, color: '#2a4a6e', marginTop: 3 }}>
                                        {n.message}
                                    </div>
                                    {!n.is_read && (
                                        <div style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', width: 6, height: 6, borderRadius: '50%', background: '#3b82f6' }} />
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}

            <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.3); }
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(8px) scale(0.97); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
        </div>
    )
}
