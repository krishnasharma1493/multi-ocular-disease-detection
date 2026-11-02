import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { env } from '../lib/env';
import { apiErrorMessage, apiStatus } from '../lib/api/types';
import { dayStamp } from '../lib/format';
import { Footer } from '../components/AppShell';
import { Logo } from '../components/Lens';

const loginSchema = z.object({
  email: z.string().trim().min(3, 'Enter the account email'),
  password: z.string().min(1, 'Enter the password'),
});
type LoginForm = z.infer<typeof loginSchema>;

const CHART: [string, string, string, string][] = [
  ['RETINA', '20/200', 'clamp(64px, 11vw, 160px)/1.02', '0.05em'],
  ['SCREEN', '20/100', 'clamp(46px, 7.8vw, 112px)/1.05', '0.07em'],
  ['FOUR', '20/70', 'clamp(34px, 5.6vw, 80px)/1.1', '0.09em'],
  ['DISEASES', '20/50', 'clamp(26px, 3.9vw, 56px)/1.2', '0.11em'],
  ['ONE PHOTO', '20/40', 'clamp(20px, 2.7vw, 38px)/1.4', '0.14em'],
];

/** Only same-app paths are allowed after sign-in. */
const safeNext = (next: string | null) => (next && next.startsWith('/') && !next.startsWith('//') ? next : '/');

export function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const form = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: env.VITE_DEMO_MODE
      ? { email: env.VITE_DEMO_EMAIL ?? '', password: env.VITE_DEMO_PASSWORD ?? '' }
      : { email: '', password: '' },
  });
  useEffect(() => { document.title = 'Sign in · RetinaScreen'; }, []);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await login(values.email.trim(), values.password);
      navigate(next, { replace: true });
    } catch (err) {
      const message = apiStatus(err) === 401
        ? 'ERR 401 · EMAIL OR PASSWORD NOT RECOGNISED. USE THE DEMO ACCOUNT CARD AT THE CAMP DESK.'
        : apiErrorMessage(err).toUpperCase();
      form.setError('root', { message });
    }
  });

  if (status === 'authenticated' || env.VITE_AUTH_DISABLED) return <Navigate to={next} replace />;
  const { errors, isSubmitting } = form.formState;
  const pwError = !!errors.password || !!errors.root;

  return (
    <div className="login">
      <div className="login-left">
        <div className="login-top">
          <Logo />
          <span className="login-brand">RetinaScreen</span>
          <span className="eyebrow login-unit">FIELD UNIT · {dayStamp(new Date())}</span>
        </div>
        <div className="login-chart" aria-hidden="true">
          {CHART.map(([word, acuity, font, ls], i) => (
            <div key={word} className="chart-row" style={i === CHART.length - 1 ? { borderBottomColor: 'var(--ink)' } : undefined}>
              <span className="n">{i + 1}</span>
              <span className="chart-w" style={{ font: `500 ${font} var(--serif)`, letterSpacing: ls }}>{word}</span>
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
          <form onSubmit={onSubmit} noValidate aria-labelledby="login-h">
            <div className="login-head">
              <span className="eyebrow">SIGN IN</span>
              <h1 id="login-h">Open today’s ledger</h1>
            </div>
            <div className="login-field">
              <label htmlFor="email" className="label">EMAIL</label>
              <input id="email" type="email" autoComplete="username" className="line-input" aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'email-err' : undefined} {...form.register('email')} />
              {errors.email && <span id="email-err" className="field-err" role="alert">▲ {errors.email.message}</span>}
            </div>
            <div className="login-field">
              <label htmlFor="password" className={`label${pwError ? ' c-err' : ''}`}>PASSWORD</label>
              <input id="password" type="password" autoComplete="current-password" className={`line-input mono pw${pwError ? ' bad' : ''}`}
                aria-invalid={pwError} aria-describedby={pwError ? 'pw-err' : undefined} {...form.register('password')} />
              <div aria-live="assertive">
                {(errors.password || errors.root) && (
                  <span id="pw-err" className="field-err"><span aria-hidden="true">▲</span>{errors.password?.message ?? errors.root?.message}</span>
                )}
              </div>
            </div>
            <div className="login-actions">
              <button type="submit" className="btn-primary" disabled={isSubmitting}>
                <span>{isSubmitting ? 'Opening ledger…' : 'Begin screening'}</span><span className="glyph" aria-hidden="true">→</span>
              </button>
              <span className="demo-note"><i aria-hidden="true" />Demo accounts only{env.VITE_DEMO_MODE ? ' · details pre-filled' : ''}</span>
            </div>
          </form>
        </main>
      </div>
      <div className="login-foot"><Footer /></div>
    </div>
  );
}
