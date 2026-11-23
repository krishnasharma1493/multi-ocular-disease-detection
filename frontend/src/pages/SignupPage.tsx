import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { env } from '../lib/env';
import { apiError, apiErrorMessage, apiStatus } from '../lib/api/types';
import { dayStamp } from '../lib/format';
import { Footer } from '../components/AppShell';
import { Logo } from '../components/Lens';

const signupSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, 'Enter your name')
      .max(80, 'Name must be 80 characters or fewer'),
    email: z
      .string()
      .trim()
      .min(1, 'Enter your email')
      .max(254, 'Email must be 254 characters or fewer')
      .email('Enter a valid email address'),
    password: z
      .string()
      .min(8, 'Password must be at least 8 characters')
      .max(200, 'Password must be 200 characters or fewer'),
    confirmPassword: z.string().min(1, 'Confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords must match',
    path: ['confirmPassword'],
  });

type SignupForm = z.infer<typeof signupSchema>;

const CHART: [string, string, string, string][] = [
  ['RETINA', '20/200', 'clamp(64px, 11vw, 160px)/1.02', '0.05em'],
  ['SCREEN', '20/100', 'clamp(46px, 7.8vw, 112px)/1.05', '0.07em'],
  ['FOUR', '20/70', 'clamp(34px, 5.6vw, 80px)/1.1', '0.09em'],
  ['DISEASES', '20/50', 'clamp(26px, 3.9vw, 56px)/1.2', '0.11em'],
  ['ONE PHOTO', '20/40', 'clamp(20px, 2.7vw, 38px)/1.4', '0.14em'],
];

export function SignupPage() {
  const { register: registerUser, status } = useAuth();
  const navigate = useNavigate();
  const [conflict, setConflict] = useState(false);
  const [today] = useState(() => dayStamp(new Date()));

  const form = useForm<SignupForm>({
    resolver: zodResolver(signupSchema),
    defaultValues: { name: '', email: '', password: '', confirmPassword: '' },
  });

  useEffect(() => {
    document.title = 'Sign up · RetinaScreen';
  }, []);

  const onSubmit = form.handleSubmit(async (values) => {
    setConflict(false);
    try {
      await registerUser(values.name.trim(), values.email.trim(), values.password);
      navigate('/', { replace: true });
    } catch (err) {
      if (apiStatus(err) === 409 || apiError(err)?.code === 'CONFLICT') {
        setConflict(true);
        form.setError('email', {
          message: 'An account with this email already exists',
        });
      } else {
        const errorBody = apiError(err);
        if (errorBody?.fields) {
          for (const [field, msgs] of Object.entries(errorBody.fields)) {
            if (field === 'name' || field === 'email' || field === 'password') {
              form.setError(field as keyof SignupForm, { message: msgs.join(', ') });
            }
          }
        }
        form.setError('root', { message: apiErrorMessage(err) });
      }
    }
  });

  if (status === 'authenticated' || env.VITE_AUTH_DISABLED) {
    return <Navigate to="/" replace />;
  }

  const { errors, isSubmitting } = form.formState;
  const nameError = !!errors.name;
  const emailError = !!errors.email;
  const pwError = !!errors.password;
  const confirmPwError = !!errors.confirmPassword;

  return (
    <div className="login">
      <div className="login-left">
        <div className="login-top">
          <Logo />
          <span className="login-brand">RetinaScreen</span>
          <span className="eyebrow login-unit">PATIENT PORTAL · {today}</span>
        </div>
        <div className="login-chart" aria-hidden="true">
          {CHART.map(([word, acuity, font, ls], i) => (
            <div
              key={word}
              className="chart-row"
              style={i === CHART.length - 1 ? { borderBottomColor: 'var(--ink)' } : undefined}
            >
              <span className="n">{i + 1}</span>
              <span className="chart-w" style={{ font: `500 ${font} var(--serif)`, letterSpacing: ls }}>
                {word}
              </span>
              <span className="acuity">{acuity}</span>
            </div>
          ))}
          <div className="eyebrow" style={{ marginTop: 18, fontSize: 11, lineHeight: 1.6, letterSpacing: '0.1em' }}>
            MYOPIA · CATARACT · GLAUCOMA · DIABETIC RETINOPATHY
          </div>
        </div>
      </div>
      <div className="login-right">
        <svg className="login-target" width="620" height="620" viewBox="0 0 620 620" aria-hidden="true">
          <circle cx="310" cy="310" r="300" fill="none" stroke="#DCD4C3" />
          <circle cx="310" cy="310" r="220" fill="none" stroke="#DCD4C3" />
          <circle cx="310" cy="310" r="120" fill="none" stroke="#E2DBCB" />
          <line x1="0" y1="310" x2="620" y2="310" stroke="#DCD4C3" />
          <line x1="310" y1="0" x2="310" y2="620" stroke="#DCD4C3" />
        </svg>
        <main id="main" className="login-card">
          <form onSubmit={onSubmit} noValidate aria-labelledby="signup-h">
            <div className="login-head">
              <span className="eyebrow">PATIENT REGISTRATION</span>
              <h1 id="signup-h">Create an account</h1>
            </div>
            <div className="login-field">
              <label htmlFor="name" className={`label${nameError ? ' c-err' : ''}`}>
                FULL NAME
              </label>
              <input
                id="name"
                type="text"
                autoComplete="name"
                className={`line-input${nameError ? ' bad' : ''}`}
                aria-invalid={nameError}
                aria-describedby={nameError ? 'name-err' : undefined}
                {...form.register('name')}
              />
              {errors.name && (
                <span id="name-err" className="field-err" role="alert">
                  ▲ {errors.name.message}
                </span>
              )}
            </div>
            <div className="login-field">
              <label htmlFor="email" className={`label${emailError ? ' c-err' : ''}`}>
                EMAIL
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                className={`line-input${emailError ? ' bad' : ''}`}
                aria-invalid={emailError}
                aria-describedby={emailError ? 'email-err' : undefined}
                {...form.register('email')}
              />
              {errors.email && (
                <span id="email-err" className="field-err" role="alert">
                  <span>▲ {errors.email.message}</span>
                  {conflict && (
                    <>
                      {' · '}
                      <Link to="/login" className="link" style={{ fontSize: 11 }}>
                        Sign in
                      </Link>
                    </>
                  )}
                </span>
              )}
            </div>
            <div className="login-field">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <label htmlFor="password" className={`label${pwError ? ' c-err' : ''}`}>
                  PASSWORD
                </label>
                <span className="eyebrow mute" style={{ fontSize: 10, letterSpacing: '0.12em' }}>
                  MIN 8 CHARACTERS
                </span>
              </div>
              <input
                id="password"
                type="password"
                autoComplete="new-password"
                className={`line-input mono pw${pwError ? ' bad' : ''}`}
                aria-invalid={pwError}
                aria-describedby={pwError ? 'pw-err' : undefined}
                {...form.register('password')}
              />
              {errors.password && (
                <span id="pw-err" className="field-err" role="alert">
                  ▲ {errors.password.message}
                </span>
              )}
            </div>
            <div className="login-field">
              <label htmlFor="confirmPassword" className={`label${confirmPwError ? ' c-err' : ''}`}>
                CONFIRM PASSWORD
              </label>
              <input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                className={`line-input mono pw${confirmPwError ? ' bad' : ''}`}
                aria-invalid={confirmPwError}
                aria-describedby={confirmPwError ? 'confirm-pw-err' : undefined}
                {...form.register('confirmPassword')}
              />
              {errors.confirmPassword && (
                <span id="confirm-pw-err" className="field-err" role="alert">
                  ▲ {errors.confirmPassword.message}
                </span>
              )}
            </div>
            {errors.root && (
              <div aria-live="assertive">
                <span className="field-err">
                  ▲ {errors.root.message}
                </span>
              </div>
            )}
            <div className="login-actions">
              <button type="submit" className="btn-primary" disabled={isSubmitting}>
                <span>{isSubmitting ? 'Creating account…' : 'Create account'}</span>
                <span className="glyph" aria-hidden="true">
                  →
                </span>
              </button>
              <span className="demo-note" style={{ justifyContent: 'center' }}>
                Already have an account?{' '}
                <Link to="/login" className="link">
                  Sign in
                </Link>
              </span>
            </div>
          </form>
        </main>
      </div>
      <div className="login-foot">
        <Footer />
      </div>
    </div>
  );
}
