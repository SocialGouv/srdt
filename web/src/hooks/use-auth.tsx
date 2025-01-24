"use client";

import { createContext, useContext, useState } from "react";

interface AuthContextType {
  hasValidatedAuth: boolean;
  setHasValidatedAuth: (value: boolean) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [hasValidatedAuth, setHasValidatedAuth] = useState(false);

  return (
    <AuthContext.Provider value={{ hasValidatedAuth, setHasValidatedAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
