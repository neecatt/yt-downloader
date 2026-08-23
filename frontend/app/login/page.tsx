import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return <main className="center-page"><section className="login-card"><p className="eyebrow">Downloader admin</p><h1>Sign in</h1><p>Use your admin token to start a secure session. The backend API credentials stay server-side.</p><LoginForm /></section></main>;
}
