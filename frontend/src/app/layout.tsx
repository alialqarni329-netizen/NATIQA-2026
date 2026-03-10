import type { Metadata } from 'next'
import { Toaster } from 'react-hot-toast'

export const metadata: Metadata = {
  title: 'ناطقة — NATIQA Enterprise AI',
  description: 'منصة الذكاء الاصطناعي المؤسسي المحلية',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet" />
        <link rel="icon" type="image/png" href={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/static/logo.png`} />
      </head>
      <body style={{ margin: 0, padding: 0, background: '#060d1a' }}>
        <Toaster
          position="top-center"
          toastOptions={{
            style: {
              background: '#0c1829',
              color: '#ccd9ef',
              border: '1px solid rgba(59,130,246,.25)',
              fontFamily: "'Tajawal', sans-serif",
              direction: 'rtl',
            },
          }}
        />
        {children}
      </body>
    </html>
  )
}
