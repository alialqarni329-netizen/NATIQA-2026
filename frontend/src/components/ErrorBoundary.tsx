'use client'
/**
 * ErrorBoundary — يلتقط أخطاء React غير المتوقعة ويعرض واجهة بديلة
 * بدلاً من شاشة بيضاء فارغة.
 */
import React, { Component, ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  errorId: string
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, errorId: '' }
  }

  static getDerivedStateFromError(): State {
    const errorId = Math.random().toString(36).substring(2, 10).toUpperCase()
    return { hasError: true, errorId }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // في بيئة الإنتاج يمكن إرسال الخطأ لـ Sentry أو نظام مراقبة
    console.error('[NATIQA Error Boundary]', {
      error: error.message,
      componentStack: info.componentStack,
    })
  }

  handleReset = () => {
    this.setState({ hasError: false, errorId: '' })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div style={{
          minHeight: '100vh',
          background: '#060d1a',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: "'Tajawal', sans-serif",
          direction: 'rtl',
        }}>
          <div style={{
            background: '#0c1829',
            border: '1px solid rgba(239,68,68,.3)',
            borderRadius: '16px',
            padding: '48px',
            maxWidth: '480px',
            width: '90%',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>⚠️</div>
            <h2 style={{ color: '#f87171', fontSize: '20px', marginBottom: '12px' }}>
              حدث خطأ غير متوقع
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '14px', marginBottom: '8px' }}>
              نعتذر عن هذا الخلل. يُرجى إعادة المحاولة.
            </p>
            <p style={{ color: '#475569', fontSize: '12px', marginBottom: '24px' }}>
              رمز الخطأ: <code style={{ color: '#64748b' }}>{this.state.errorId}</code>
            </p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <button
                onClick={this.handleReset}
                style={{
                  background: '#1e3a5f',
                  color: '#93c5fd',
                  border: '1px solid #1e40af',
                  borderRadius: '8px',
                  padding: '10px 20px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontFamily: "'Tajawal', sans-serif",
                }}
              >
                إعادة المحاولة
              </button>
              <button
                onClick={() => { window.location.href = '/' }}
                style={{
                  background: 'transparent',
                  color: '#64748b',
                  border: '1px solid #1e293b',
                  borderRadius: '8px',
                  padding: '10px 20px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontFamily: "'Tajawal', sans-serif",
                }}
              >
                الرئيسية
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
