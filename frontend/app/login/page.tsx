import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return <main className="center-page"><section className="login-card"><p className="eyebrow">Downloader admin</p><h1>Sign in</h1><p>Private activity dashboard. Your access token is never sent to the browser.</p><LoginForm /></section></main>;
}
