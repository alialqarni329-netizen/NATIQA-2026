"""
app/core/emails.py
══════════════════════════════════════════════════════════════════
Email Templates — NATIQA Platform

All templates return fully self-contained HTML strings with inline
CSS only (no external stylesheets, except Google Fonts @import which
degrades gracefully in clients that block it).

Design: RTL Arabic • Slate/Blue theme • Responsive single-column
"""
from __future__ import annotations


def get_welcome_email_template(business_name: str, otp: str) -> str:

    """
    Returns a premium, responsive RTL HTML email for OTP verification.

    Args:
        business_name: The registering company's name (personalises the greeting).
        otp:           The 6-digit plaintext OTP code to display.

    Returns:
        A complete HTML document string ready to send as the email body.
    """
    # Digit cells — each digit rendered in its own box for that classic
    # "verification code" look familiar from banking apps.
    digit_cells = "".join(
        f'<td style="'
        f'width:48px;height:56px;'
        f'background:#1e3a5f;'          # deep navy cell
        f'border-radius:10px;'
        f'text-align:center;'
        f'vertical-align:middle;'
        f'font-size:28px;font-weight:700;'
        f'letter-spacing:0;'
        f'color:#60a5fa;'                # electric blue digit
        f'font-family:monospace;'
        f'margin:0 4px;">'
        f'{digit}</td>'
        for digit in otp
    )

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>رمز التحقق من ناطقة</title>
  <!--[if !mso]><!-->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet" />
  <!--<![endif]-->
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#f1f5f9; font-family:'Tajawal',Arial,sans-serif; direction:rtl; }}
    @media only screen and (max-width:620px) {{
      .container {{ width:100% !important; padding:0 12px !important; }}
      .header-logo {{ font-size:26px !important; }}
      .digit-table {{ gap:6px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Tajawal',Arial,sans-serif;direction:rtl;">

  <!-- Outer wrapper -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f1f5f9;min-height:100vh;padding:32px 16px;">
    <tr>
      <td align="center">

        <!-- Card -->
        <table role="presentation" class="container" width="580" cellpadding="0" cellspacing="0" border="0"
               style="max-width:580px;width:100%;border-radius:20px;overflow:hidden;
                      box-shadow:0 20px 60px rgba(0,0,0,0.18);">

          <!-- ── HEADER ─────────────────────────────────────────────── -->
          <tr>
            <td style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 60%,#1d4ed8 100%);
                       padding:40px 40px 36px;text-align:center;">
              <!-- Brand mark -->
              <div style="display:inline-block;background:rgba(255,255,255,0.08);
                          border:1px solid rgba(255,255,255,0.15);
                          border-radius:16px;padding:10px 28px;margin-bottom:16px;">
                <span class="header-logo"
                      style="font-size:30px;font-weight:800;color:#ffffff;
                             letter-spacing:1px;font-family:'Tajawal',Arial,sans-serif;">
                  ناطقة
                </span>
                <span style="font-size:13px;color:#93c5fd;font-weight:500;
                             margin-right:8px;letter-spacing:2px;font-family:Arial,sans-serif;">
                  NATIQA
                </span>
              </div>
              <p style="color:#93c5fd;font-size:14px;font-weight:500;margin:0;letter-spacing:0.5px;">
                منصة الذكاء الاصطناعي للمؤسسات
              </p>
            </td>
          </tr>

          <!-- ── BODY ──────────────────────────────────────────────── -->
          <tr>
            <td style="background:#ffffff;padding:44px 44px 36px;">

              <!-- Greeting -->
              <p style="font-size:22px;font-weight:700;color:#0f172a;margin:0 0 8px;">
                مرحباً بك في ناطقة 👋
              </p>
              <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 28px;">
                شكراً لتسجيل
                <strong style="color:#1d4ed8;">{business_name}</strong>
                في منصة ناطقة.<br/>
                للتحقق من بريدك الإلكتروني وإتمام إنشاء حسابك، يرجى استخدام الرمز أدناه:
              </p>

              <!-- OTP block label -->
              <p style="font-size:13px;font-weight:600;color:#64748b;
                         text-transform:uppercase;letter-spacing:1.5px;
                         margin:0 0 14px;text-align:center;">
                رمز التحقق المؤقت
              </p>

              <!-- OTP digit boxes -->
              <div style="background:#0f172a;border-radius:16px;
                          padding:24px 20px;text-align:center;margin-bottom:16px;">
                <table role="presentation" cellpadding="0" cellspacing="8"
                       style="margin:0 auto;display:inline-table;">
                  <tr>
                    {digit_cells}
                  </tr>
                </table>
              </div>

              <!-- Expiry notice -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="width:100%;background:#eff6ff;border-radius:10px;
                            border-right:4px solid #3b82f6;margin-bottom:28px;">
                <tr>
                  <td style="padding:14px 18px;">
                    <p style="font-size:13px;color:#1e40af;font-weight:600;margin:0 0 2px;">
                      ⏱ الرمز صالح لمدة 15 دقيقة فقط
                    </p>
                    <p style="font-size:12px;color:#3b82f6;margin:0;">
                      إذا انتهت صلاحيته، يمكنك طلب رمز جديد من صفحة التسجيل.
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Divider -->
              <hr style="border:none;border-top:1px solid #e2e8f0;margin:0 0 24px;" />

              <!-- Steps -->
              <p style="font-size:14px;font-weight:700;color:#334155;margin:0 0 12px;">
                الخطوات التالية بعد التحقق:
              </p>
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;">
                <tr>
                  <td style="padding:8px 0;">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="width:32px;height:32px;background:#dbeafe;border-radius:50%;
                                   text-align:center;vertical-align:middle;
                                   font-size:14px;font-weight:700;color:#1d4ed8;">1</td>
                        <td style="padding-right:14px;font-size:13px;color:#475569;line-height:1.5;">
                          سيراجع فريقنا طلبك ويرسل لك إشعاراً بالموافقة خلال 24 ساعة
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:8px 0;">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="width:32px;height:32px;background:#dbeafe;border-radius:50%;
                                   text-align:center;vertical-align:middle;
                                   font-size:14px;font-weight:700;color:#1d4ed8;">2</td>
                        <td style="padding-right:14px;font-size:13px;color:#475569;line-height:1.5;">
                          بعد الموافقة، يمكنك تسجيل الدخول وبدء تحليل مستنداتك فوراً
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- ── FOOTER ─────────────────────────────────────────────── -->
          <tr>
            <td style="background:#f8fafc;border-top:1px solid #e2e8f0;
                       padding:28px 44px;text-align:center;">

              <!-- Security warning -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="width:100%;background:#fff7ed;border-radius:8px;
                            border-right:3px solid #f97316;margin-bottom:20px;">
                <tr>
                  <td style="padding:12px 16px;">
                    <p style="font-size:12px;color:#9a3412;font-weight:600;margin:0;">
                      🔒 تنبيه أمني: لا تشارك هذا الرمز مع أي شخص آخر أبداً.
                      لن يطلب منك فريق ناطقة رمز التحقق عبر الهاتف أو الدردشة.
                    </p>
                  </td>
                </tr>
              </table>

              <p style="font-size:12px;color:#94a3b8;margin:0 0 4px;">
                تلقّيت هذا البريد لأن هذا العنوان تم إدخاله في نموذج التسجيل.
              </p>
              <p style="font-size:12px;color:#94a3b8;margin:0 0 16px;">
                إذا لم تطلب هذا، يمكنك تجاهل هذه الرسالة بأمان.
              </p>
              <p style="font-size:12px;color:#cbd5e1;margin:0;">
                © 2026 ناطقة — NATIQA Enterprise AI · جميع الحقوق محفوظة
              </p>
            </td>
          </tr>

        </table>
        <!-- /Card -->

      </td>
    </tr>
  </table>

</body>
</html>"""


def get_approval_email_template(business_name: str, login_url: str = "https://app.natiqa.ai") -> str:
    """
    Returns a premium RTL Arabic HTML email notifying the user their account was approved.

    Args:
        business_name: The approved company's name.
        login_url:     The URL of the login page — embedded in the CTA button.

    Returns:
        A complete, self-contained HTML email string.
    """
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>تمت الموافقة على حسابك في ناطقة</title>
  <!--[if !mso]><!-->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet" />
  <!--<![endif]-->
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#f1f5f9; font-family:'Tajawal',Arial,sans-serif; direction:rtl; }}
    @media only screen and (max-width:620px) {{
      .container {{ width:100% !important; padding:0 12px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Tajawal',Arial,sans-serif;direction:rtl;">

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f1f5f9;min-height:100vh;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" class="container" width="580" cellpadding="0" cellspacing="0" border="0"
               style="max-width:580px;width:100%;border-radius:20px;overflow:hidden;
                      box-shadow:0 20px 60px rgba(0,0,0,0.18);">

          <!-- ── HEADER ─────────────────────────────────────────────── -->
          <tr>
            <td style="background:linear-gradient(135deg,#052e16 0%,#065f46 55%,#059669 100%);
                       padding:44px 40px 40px;text-align:center;">
              <!-- Checkmark badge -->
              <div style="display:inline-flex;align-items:center;justify-content:center;
                          width:72px;height:72px;border-radius:50%;
                          background:rgba(255,255,255,0.15);
                          border:2px solid rgba(255,255,255,0.3);
                          margin-bottom:20px;font-size:36px;">
                ✅
              </div>
              <div style="display:inline-block;background:rgba(255,255,255,0.08);
                          border:1px solid rgba(255,255,255,0.15);
                          border-radius:16px;padding:8px 24px;margin-bottom:14px;">
                <span style="font-size:26px;font-weight:800;color:#ffffff;letter-spacing:1px;
                             font-family:'Tajawal',Arial,sans-serif;">ناطقة</span>
                <span style="font-size:12px;color:#6ee7b7;font-weight:500;margin-right:8px;
                             letter-spacing:2px;font-family:Arial,sans-serif;">NATIQA</span>
              </div>
              <p style="color:#6ee7b7;font-size:20px;font-weight:700;margin:0;">
                تمت الموافقة على حسابك! 🎉
              </p>
            </td>
          </tr>

          <!-- ── BODY ──────────────────────────────────────────────── -->
          <tr>
            <td style="background:#ffffff;padding:44px 44px 36px;">

              <!-- Greeting -->
              <p style="font-size:22px;font-weight:700;color:#0f172a;margin:0 0 12px;">
                مبروك، انضم {business_name} إلى ناطقة!
              </p>
              <p style="font-size:15px;color:#475569;line-height:1.8;margin:0 0 32px;">
                يسعدنا إخبارك أن فريق ناطقة راجع طلبك وأجرى التحقق اللازم.
                <strong style="color:#059669;">حسابك نشط الآن</strong> ويمكنك بدء استخدام المنصة فوراً.
              </p>

              <!-- CTA Button -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="margin:0 auto 32px;">
                <tr>
                  <td style="border-radius:12px;background:linear-gradient(135deg,#059669,#047857);">
                    <a href="{login_url}"
                       style="display:inline-block;padding:16px 48px;
                              font-size:16px;font-weight:700;color:#ffffff;
                              text-decoration:none;font-family:'Tajawal',Arial,sans-serif;
                              letter-spacing:0.5px;">
                      تسجيل الدخول الآن ←
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Divider -->
              <hr style="border:none;border-top:1px solid #e2e8f0;margin:0 0 28px;" />

              <!-- What's next -->
              <p style="font-size:14px;font-weight:700;color:#334155;margin:0 0 16px;">
                ابدأ رحلتك مع ناطقة في 3 خطوات:
              </p>

              <!-- Step 1 -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="width:100%;margin-bottom:12px;">
                <tr>
                  <td style="vertical-align:top;width:40px;">
                    <div style="width:36px;height:36px;background:#d1fae5;border-radius:50%;
                                text-align:center;line-height:36px;
                                font-size:16px;font-weight:700;color:#059669;">1</div>
                  </td>
                  <td style="padding-right:14px;vertical-align:middle;">
                    <p style="font-size:14px;font-weight:600;color:#0f172a;margin:0 0 2px;">
                      أنشئ مشروعك الأول
                    </p>
                    <p style="font-size:13px;color:#64748b;margin:0;line-height:1.5;">
                      جرّب رفع مستنداتك وابدأ تحليلها فوراً بالذكاء الاصطناعي
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Step 2 -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="width:100%;margin-bottom:12px;">
                <tr>
                  <td style="vertical-align:top;width:40px;">
                    <div style="width:36px;height:36px;background:#d1fae5;border-radius:50%;
                                text-align:center;line-height:36px;
                                font-size:16px;font-weight:700;color:#059669;">2</div>
                  </td>
                  <td style="padding-right:14px;vertical-align:middle;">
                    <p style="font-size:14px;font-weight:600;color:#0f172a;margin:0 0 2px;">
                      استكشف لوحة التحليلات
                    </p>
                    <p style="font-size:13px;color:#64748b;margin:0;line-height:1.5;">
                      راقب استخدام المستندات واستفسارات الذكاء الاصطناعي لفريقك في الوقت الفعلي
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Step 3 -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="width:100%;margin-bottom:28px;">
                <tr>
                  <td style="vertical-align:top;width:40px;">
                    <div style="width:36px;height:36px;background:#d1fae5;border-radius:50%;
                                text-align:center;line-height:36px;
                                font-size:16px;font-weight:700;color:#059669;">3</div>
                  </td>
                  <td style="padding-right:14px;vertical-align:middle;">
                    <p style="font-size:14px;font-weight:600;color:#0f172a;margin:0 0 2px;">
                      فعّل المصادقة الثنائية (2FA)
                    </p>
                    <p style="font-size:13px;color:#64748b;margin:0;line-height:1.5;">
                      أضف طبقة حماية إضافية لحسابك من إعدادات الأمان
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Plan notice -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="width:100%;background:#eff6ff;border-radius:10px;
                            border-right:4px solid #3b82f6;margin-bottom:0;">
                <tr>
                  <td style="padding:14px 18px;">
                    <p style="font-size:13px;color:#1e40af;font-weight:600;margin:0 0 4px;">
                      📦 خطتك الحالية: المجاني (Free)
                    </p>
                    <p style="font-size:12px;color:#3b82f6;margin:0;">
                      يتضمن: 3 مستندات · 5 ميغابايت للملف · 20 سؤال ذكاء اصطناعي يومياً.
                      يمكنك الترقية في أي وقت من لوحة الإعدادات.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- ── FOOTER ─────────────────────────────────────────────── -->
          <tr>
            <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:26px 44px;text-align:center;">
              <p style="font-size:12px;color:#94a3b8;margin:0 0 6px;">
                هذا البريد أُرسل لأن حسابك في ناطقة تمت الموافقة عليه.
              </p>
              <p style="font-size:12px;color:#94a3b8;margin:0 0 14px;">
                إذا لم تتوقع هذا البريد، يرجى التواصل معنا فوراً عبر support@natiqa.ai
              </p>
              <p style="font-size:12px;color:#cbd5e1;margin:0;">
                © 2026 ناطقة — NATIQA Enterprise AI · جميع الحقوق محفوظة
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""


def get_trial_reminder_email_template(business_name: str, days_left: int) -> str:
    """
    Returns a premium RTL HTML reminder email sent when the Golden Trial
    is about to expire (typically day 13 / 2 days before end).

    Args:
        business_name: Company name shown in the greeting.
        days_left:     Number of days remaining (usually 1 or 2).
    """
    days_word = "يوم" if days_left == 1 else "أيام"
    urgency_color = "#DC2626" if days_left == 1 else "#D97706"  # red if 1 day, amber otherwise

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>تنتهي تجربتك الذهبية قريباً — ناطقة</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap');
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0f172a; font-family: 'IBM Plex Sans Arabic', Arial, sans-serif; -webkit-font-smoothing: antialiased; }}
  </style>
</head>
<body style="background:#0f172a; margin:0; padding:32px 16px;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background:#1e293b; border-radius:16px; overflow:hidden; box-shadow:0 25px 50px rgba(0,0,0,0.5);">

          <!-- ── Header gradient (amber/gold) ── -->
          <tr>
            <td style="background:linear-gradient(135deg,#92400e 0%,#d97706 50%,#f59e0b 100%); padding:48px 40px; text-align:center;">
              <div style="font-size:56px; margin-bottom:16px;">⏳</div>
              <h1 style="color:#fff; font-size:28px; font-weight:700; margin-bottom:8px;">
                تجربتك الذهبية تنتهي قريباً!
              </h1>
              <p style="color:#fde68a; font-size:16px;">لا تفقد مزاياك الاحترافية</p>
            </td>
          </tr>

          <!-- ── Countdown badge ── -->
          <tr>
            <td style="padding:0 40px; text-align:center;">
              <div style="margin:-24px auto 0; display:inline-block; background:{urgency_color}; color:#fff; padding:12px 32px; border-radius:50px; font-size:20px; font-weight:700; box-shadow:0 8px 24px rgba(0,0,0,0.3);">
                ⚡ متبقٍ {days_left} {days_word} فقط!
              </div>
            </td>
          </tr>

          <!-- ── Body ── -->
          <tr>
            <td style="padding:40px;">
              <p style="color:#94a3b8; font-size:15px; line-height:1.7; margin-bottom:24px;">
                مرحباً <strong style="color:#f1f5f9;">{business_name}</strong>،
              </p>
              <p style="color:#94a3b8; font-size:15px; line-height:1.7; margin-bottom:32px;">
                تجربتك الذهبية المجانية على منصة <strong style="color:#f59e0b;">ناطقة</strong> ستنتهي خلال <strong style="color:{urgency_color};">{days_left} {days_word}</strong>.
                لا تدع هذه الميزات الاحترافية تختفي — قم بالترقية الآن للحفاظ عليها إلى الأبد.
              </p>

              <!-- Features you'll lose -->
              <div style="background:#0f172a; border:1px solid #334155; border-radius:12px; padding:24px; margin-bottom:32px;">
                <p style="color:#f59e0b; font-size:14px; font-weight:600; margin-bottom:16px; text-transform:uppercase; letter-spacing:1px;">
                  ⭐ المزايا التي ستفقدها بعد التجربة:
                </p>
                {{
                  "محلل مستندات AI غير محدود": "∞",
                  "رفع ملفات حتى 50 ميغابايت":  "50MB",
                  "100 مستند في المشاريع":         "100",
                  "تقارير متقدمة وتحليلات":        "📊",
                }}
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding:8px 0; border-bottom:1px solid #1e293b;">
                      <span style="color:#94a3b8; font-size:14px;">🔮 محلل مستندات AI غير محدود</span>
                      <span style="color:#f59e0b; font-weight:700; float:left;">∞</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:8px 0; border-bottom:1px solid #1e293b;">
                      <span style="color:#94a3b8; font-size:14px;">📁 رفع ملفات حتى 50 ميغابايت</span>
                      <span style="color:#f59e0b; font-weight:700; float:left;">50 MB</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:8px 0; border-bottom:1px solid #1e293b;">
                      <span style="color:#94a3b8; font-size:14px;">📚 100 مستند في مشاريعك</span>
                      <span style="color:#f59e0b; font-weight:700; float:left;">100</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:8px 0;">
                      <span style="color:#94a3b8; font-size:14px;">📊 تقارير وتحليلات متقدمة</span>
                      <span style="color:#f59e0b; font-weight:700; float:left;">✓</span>
                    </td>
                  </tr>
                </table>
              </div>

              <!-- CTA button -->
              <div style="text-align:center; margin-bottom:32px;">
                <a href="https://natiqa.ai/upgrade"
                   style="display:inline-block; background:linear-gradient(135deg,#d97706,#f59e0b); color:#fff; text-decoration:none; padding:16px 48px; border-radius:50px; font-size:18px; font-weight:700; box-shadow:0 8px 24px rgba(245,158,11,0.4); transition:transform 0.2s;">
                  ترقّ للخطة الاحترافية الآن ←
                </a>
                <p style="color:#475569; font-size:12px; margin-top:12px;">سعر خاص متاح لعملاء التجربة الذهبية</p>
              </div>

              <!-- Reminder of what happens after -->
              <div style="background:#1e293b; border:1px solid #f59e0b33; border-radius:10px; padding:16px; text-align:center;">
                <p style="color:#64748b; font-size:13px; line-height:1.6;">
                  إذا لم تقم بالترقية، سيتحول حسابك تلقائياً إلى الخطة المجانية (3 مستندات · 5 MB · 20 سؤال/يوم) بعد انتهاء التجربة.
                </p>
              </div>
            </td>
          </tr>

          <!-- ── Footer ── -->
          <tr>
            <td style="background:#0f172a; padding:24px 40px; border-top:1px solid #1e293b; text-align:center;">
              <p style="color:#334155; font-size:12px; margin-bottom:8px;">
                © 2026 ناطقة · جميع الحقوق محفوظة
              </p>
              <p style="color:#334155; font-size:12px;">
                أسئلة؟ <a href="mailto:support@natiqa.ai" style="color:#f59e0b; text-decoration:none;">support@natiqa.ai</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
def get_invitation_email_template(org_name: str, invite_url: str) -> str:
    """
    Returns a premium RTL Arabic HTML email for organization invitations.
    """
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>دعوة للانضمام إلى {org_name} في ناطقة</title>
  <!--[if !mso]><!-->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet" />
  <!--<![endif]-->
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#f1f5f9; font-family:'Tajawal',Arial,sans-serif; direction:rtl; }}
    @media only screen and (max-width:620px) {{
      .container {{ width:100% !important; padding:0 12px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Tajawal',Arial,sans-serif;direction:rtl;">

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f1f5f9;min-height:100vh;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" class="container" width="580" cellpadding="0" cellspacing="0" border="0"
               style="max-width:580px;width:100%;border-radius:20px;overflow:hidden;
                      box-shadow:0 20px 60px rgba(0,0,0,0.18);">

          <!-- ── HEADER ─────────────────────────────────────────────── -->
          <tr>
            <td style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 60%,#1d4ed8 100%);
                       padding:44px 40px 40px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.08);
                          border:1px solid rgba(255,255,255,0.15);
                          border-radius:16px;padding:8px 24px;margin-bottom:14px;">
                <span style="font-size:26px;font-weight:800;color:#ffffff;letter-spacing:1px;
                             font-family:'Tajawal',Arial,sans-serif;">ناطقة</span>
                <span style="font-size:12px;color:#93c5fd;font-weight:500;margin-right:8px;
                             letter-spacing:2px;font-family:Arial,sans-serif;">NATIQA</span>
              </div>
              <p style="color:#93c5fd;font-size:18px;font-weight:700;margin:0;">
                دعوة انضمام لفريق العمل
              </p>
            </td>
          </tr>

          <!-- ── BODY ──────────────────────────────────────────────── -->
          <tr>
            <td style="background:#ffffff;padding:44px 44px 36px;">

              <!-- Header Text -->
              <p style="font-size:20px;font-weight:700;color:#0f172a;margin:0 0 12px; text-align:center;">
                أهلاً بك! 👋
              </p>
              <p style="font-size:16px;color:#475569;line-height:1.8;margin:0 0 32px; text-align:center;">
                تلقيت دعوة من مؤسسة <strong style="color:#1d4ed8;">{org_name}</strong> للانضمام إلى فريق عملهم على منصة <strong>ناطقة</strong>.
              </p>

              <!-- CTA Button -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0"
                     style="margin:0 auto 32px;">
                <tr>
                  <td style="border-radius:12px;background:linear-gradient(135deg,#1d4ed8,#1e40af);">
                    <a href="{invite_url}"
                       style="display:inline-block;padding:16px 48px;
                              font-size:16px;font-weight:700;color:#ffffff;
                              text-decoration:none;font-family:'Tajawal',Arial,sans-serif;
                              letter-spacing:0.5px;">
                      قبول الدعوة وإكمال الحساب ←
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Security notice -->
              <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:20px; margin-bottom:28px;">
                <p style="font-size:13px; color:#64748b; line-height:1.6; margin:0;">
                  بمجرد قبول الدعوة، ستتمكن من الوصول إلى المشاريع والمستندات المشتركة لفريقك، والبدء في استخدام قدرات الذكاء الاصطناعي السيادي في ناطقة.
                </p>
              </div>

              <!-- Expiry check -->
              <p style="font-size:12px; color:#94a3b8; text-align:center; margin-bottom:0;">
                ⏱ هذه الدعوة صالحة لمدة 48 ساعة فقط.
              </p>
            </td>
          </tr>

          <!-- ── FOOTER ─────────────────────────────────────────────── -->
          <tr>
            <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:26px 44px;text-align:center;">
              <p style="font-size:12px;color:#cbd5e1;margin:0;">
                © 2026 ناطقة — NATIQA Enterprise AI · جميع الحقوق محفوظة
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""
