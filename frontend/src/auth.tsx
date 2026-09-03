import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, type User } from "./api";

interface Ctx {
  user: User | null;
  company: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthCtx = createContext<Ctx>({} as Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [company, setCompany] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api.me()
      .then((m) => {
        setUser(m.user);
        setCompany(m.company.name);
      })
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const r = await api.login({ email, password });
    setToken(r.access_token);
    const m = await api.me();
    setUser(m.user);
    setCompany(m.company.name);
  }

  async function logout() {
    try {
      await api.logout();
    } catch {
      /* session already dead — still clear locally */
    }
    setToken(null);
    setUser(null);
    setCompany(null);
  }

  return <AuthCtx.Provider value={{ user, company, loading, login, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
