'use client'
import dynamic from 'next/dynamic'

function Dashboard() {
  return (
    <div style={{ background: '#060d1a', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontFamily: 'Tajawal,sans-serif', direction: 'rtl' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🏛️</div>
        <h1 style={{ fontSize: 24, marginBottom: 8 }}>مرحباً بك في ناطقة</h1>
        <p style={{ color: '#5b7fa6', marginBottom: 24 }}>المنصة تعمل ✅</p>
        <button onClick={() => { localStorage.removeItem('access_token'); window.location.href = '/login' }} style={{ padding: '10px 24px', background: '#1e40af', border: 'none', borderRadius: 10, color: '#fff', cursor: 'pointer', fontSize: 14 }}>
          تسجيل الخروج
        </button>
      </div>
    </div>
  )
}

export default dynamic(() => Promise.resolve(Dashboard), { ssr: false })
