"use client";
import { push } from "@socialgouv/matomo-next";
import { useEffect, useRef } from "react";
import { useAuth } from "@/hooks/use-auth";
import { ALLOWED_EMAIL_DOMAINS, DOMAIN_TO_DEPARTMENT } from "@/constants";

// Custom dimension ID for department tracking (configure this in Matomo admin)
const DEPARTMENT_DIMENSION_ID = 1;

/**
 * Extract department from email address based on allowed domains
 */
function getDepartmentFromEmail(
  email: string | null | undefined
): string | null {
  if (!email) return null;

  const emailLower = email.toLowerCase();
  const domain = ALLOWED_EMAIL_DOMAINS.find((d) =>
    emailLower.endsWith(`@${d}`)
  );

  if (domain) {
    return DOMAIN_TO_DEPARTMENT[domain] || domain;
  }

  return null;
}

/**
 * Generate a secure hash (24 chars) from an email for Matomo user ID
 * Uses SHA-256 via Web Crypto API for proper anonymization
 */
async function hashEmail(email: string): Promise<string> {
  const normalized = email.toLowerCase().trim();

  // Add a salt prefix to protect against rainbow table attacks
  const salted = `srdt-matomo:${normalized}`;

  // Use Web Crypto API for secure hashing
  const encoder = new TextEncoder();
  const data = encoder.encode(salted);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);

  // Convert to hex and take first 24 chars
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return hashHex.slice(0, 24);
}

/**
 * Tracks the authenticated user in Matomo with a hashed user ID and department.
 * Must be used inside a SessionProvider.
 */
export function MatomoUserTracking() {
  const { user, isAuthenticated } = useAuth();

  // Track the email that was successfully set to prevent duplicates
  const trackedEmailRef = useRef<string | null>(null);
  // Track if an async operation is in progress to prevent race conditions
  const isSettingUpRef = useRef(false);

  // Set user ID and department when user is authenticated
  useEffect(() => {
    if (!isAuthenticated || !user?.email) return;

    // Skip if already tracking this email or if setup is in progress
    if (trackedEmailRef.current === user.email || isSettingUpRef.current)
      return;

    const currentEmail = user.email;
    isSettingUpRef.current = true;

    const setupUserTracking = async () => {
      try {
        const hashedUserId = await hashEmail(currentEmail);

        // Verify email hasn't changed during async operation
        if (currentEmail !== user.email) {
          isSettingUpRef.current = false;
          return;
        }

        // Set the hashed user ID
        push(["setUserId", hashedUserId]);

        // Set department as custom dimension if available
        const department = getDepartmentFromEmail(currentEmail);
        if (department) {
          push(["setCustomDimension", DEPARTMENT_DIMENSION_ID, department]);
        }

        trackedEmailRef.current = currentEmail;
      } finally {
        isSettingUpRef.current = false;
      }
    };

    setupUserTracking();
  }, [isAuthenticated, user?.email]);

  // Reset user ID tracking on logout
  useEffect(() => {
    if (!isAuthenticated && trackedEmailRef.current) {
      push(["resetUserId"]);
      trackedEmailRef.current = null;
    }
  }, [isAuthenticated]);

  return null;
}
