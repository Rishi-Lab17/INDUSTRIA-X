/* Firebase phone auth (verification only). Initialized solely from
   VITE_FIREBASE_* env vars. If unconfigured, every helper reports it —
   the UI shows "not configured" instead of faking verification. */
import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  RecaptchaVerifier,
  signInWithPhoneNumber,
  type ConfirmationResult,
} from "firebase/auth";

let app: FirebaseApp | null = null;

export function isFirebaseConfigured(): boolean {
  return Boolean(import.meta.env.VITE_FIREBASE_API_KEY as string | undefined)
    && Boolean(import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined)
    && Boolean(import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined);
}

function getApp(): FirebaseApp {
  if (!isFirebaseConfigured()) {
    throw new Error("Mobile verification is not configured on this deployment.");
  }
  if (!app) {
    app = initializeApp({
      apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string,
      authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string,
      projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string,
    });
  }
  return app;
}

export async function sendPhoneCode(phone: string, containerId: string): Promise<ConfirmationResult> {
  const auth = getAuth(getApp());
  const verifier = new RecaptchaVerifier(auth, containerId, { size: "invisible" });
  return signInWithPhoneNumber(auth, phone, verifier);
}
